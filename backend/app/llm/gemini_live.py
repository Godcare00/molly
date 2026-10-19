"""Thin async wrapper around a single google-genai Live API connection.

This is deliberately separate from app/llm/base.py's LLMProvider - the Live
API is a stateful, bidirectional audio WebSocket (one persistent session per
conversation), not a request/response chat completion, so it doesn't fit
that interface. One GeminiLiveSession instance == one hands-free voice
session. Callers (app/agent/live_executor.py) push audio in and consume
normalized LiveEvent objects out via `events()`.

Reference: https://ai.google.dev/gemini-api/docs/live-guide (fetched while
building this - verify against your installed `google-genai` version if
behavior looks off, the Live API surface has moved fast across releases).
"""

from dataclasses import dataclass
from typing import AsyncIterator, Optional

from google import genai
from google.genai import types

from app.config import settings

# Input: PCM16 little-endian mono, 16kHz native (Gemini resamples others).
# Output: PCM16 little-endian mono, 24kHz. These are fixed by the API, not
# configurable - the mobile client must capture/play at these exact rates.
INPUT_SAMPLE_RATE_HZ = 16000
OUTPUT_SAMPLE_RATE_HZ = 24000
INPUT_MIME_TYPE = f"audio/pcm;rate={INPUT_SAMPLE_RATE_HZ}"


@dataclass
class LiveFunctionCall:
    id: str
    name: str
    args: dict


@dataclass
class LiveEvent:
    kind: str  # audio | input_transcript | output_transcript | function_calls | interrupted | turn_complete | go_away | closed | error
    audio: Optional[bytes] = None
    text: Optional[str] = None
    function_calls: Optional[list] = None
    message: Optional[str] = None


class GeminiLiveSession:
    def __init__(self, system_instruction: str, tool_declarations: list[dict]):
        if not settings.gemini_api_key:
            raise RuntimeError("gemini_api_key is not configured (Settings > Voice)")
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._system_instruction = system_instruction
        self._tool_declarations = tool_declarations
        self._connect_cm = None
        self._session = None

    async def __aenter__(self) -> "GeminiLiveSession":
        config = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            system_instruction=types.Content(parts=[types.Part(text=self._system_instruction)]),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            tools=[{"function_declarations": self._tool_declarations}] if self._tool_declarations else None,
            # Molly conversations can run long; compress rather than hard-cut
            # the session once the model's own context window fills up. This
            # is independent of the ~10min connection-lifetime cap, which we
            # handle ourselves in live_executor.py by closing proactively.
            context_window_compression=types.ContextWindowCompressionConfig(
                sliding_window=types.SlidingWindow(),
            ),
        )
        self._connect_cm = self._client.aio.live.connect(model=settings.gemini_live_model, config=config)
        self._session = await self._connect_cm.__aenter__()
        return self

    async def __aexit__(self, *exc_info) -> None:
        if self._connect_cm is not None:
            await self._connect_cm.__aexit__(*exc_info)

    async def send_audio_chunk(self, pcm16_16k: bytes) -> None:
        await self._session.send_realtime_input(
            audio=types.Blob(data=pcm16_16k, mime_type=INPUT_MIME_TYPE)
        )

    async def send_audio_stream_end(self) -> None:
        """Flush any buffered audio - call when the mic is muted/paused so a
        half-received utterance doesn't sit stuck waiting for more input."""
        await self._session.send_realtime_input(audio_stream_end=True)

    async def send_text(self, text: str) -> None:
        """Inject text as if the user typed it (used for the app-side
        "correct" action, which doesn't have a voice equivalent)."""
        await self._session.send_realtime_input(text=text)

    async def send_tool_response(self, call_id: str, name: str, response: dict) -> None:
        await self._session.send_tool_response(
            function_responses=[types.FunctionResponse(id=call_id, name=name, response=response)]
        )

    async def events(self) -> AsyncIterator[LiveEvent]:
        async for response in self._session.receive():
            content = response.server_content
            if content:
                if content.model_turn:
                    for part in content.model_turn.parts:
                        if part.inline_data and part.inline_data.data:
                            yield LiveEvent(kind="audio", audio=part.inline_data.data)
                if content.input_transcription and content.input_transcription.text:
                    yield LiveEvent(kind="input_transcript", text=content.input_transcription.text)
                if content.output_transcription and content.output_transcription.text:
                    yield LiveEvent(kind="output_transcript", text=content.output_transcription.text)
                if content.interrupted:
                    yield LiveEvent(kind="interrupted")
                if content.turn_complete:
                    yield LiveEvent(kind="turn_complete")

            if response.tool_call and response.tool_call.function_calls:
                calls = [
                    LiveFunctionCall(id=fc.id, name=fc.name, args=dict(fc.args or {}))
                    for fc in response.tool_call.function_calls
                ]
                yield LiveEvent(kind="function_calls", function_calls=calls)

            if getattr(response, "go_away", None) is not None:
                # Server-side warning that it's about to close the connection
                # (session hitting Google's ~10min cap). live_executor.py
                # treats this the same as our own proactive timeout.
                yield LiveEvent(kind="go_away", message="Gemini is closing this session soon")

        yield LiveEvent(kind="closed")


def build_voice_system_instruction(base_prompt: str, confirm_gated_tool_names: list[str]) -> str:
    """Layer hands-free behavior on top of Molly's normal system prompt.

    Note this is a UX instruction, not the safety boundary - the backend
    (app/agent/live_executor.py) independently re-classifies every tool
    call's actual risk via the same risk classifier text mode uses, and
    gates execution on that regardless of whether the model narrated first
    or which tools are named here. A tool named here could still turn out
    to be low-risk for a given call's arguments (or vice versa); this list
    is just what to be extra cautious and vocal about by default.
    """
    tools_list = ", ".join(sorted(confirm_gated_tool_names)) or "(none configured)"
    return f"""{base_prompt}

# Hands-free voice mode

You're being used through a voice interface right now - your replies are spoken aloud and the person can't see a screen. Keep spoken replies short and conversational: a sentence or two, not a report.

These tools change something on the server and require the person's explicit spoken confirmation before you call them: {tools_list}.

Before calling any of those tools:
1. Say out loud, in one short sentence, exactly what you're about to do and why (e.g. "I'm going to restart nginx to clear the stuck worker. Say 'confirm' to go ahead, or 'cancel' to stop.").
2. Then call the tool.

Never call one of those tools silently, and never treat a vague "yeah" or "sure" as confirmation - the system will tell you whether the action was actually confirmed, cancelled, or timed out via the function result. If it comes back cancelled or timed out, say so plainly and stop; don't retry automatically or rephrase to get a different answer.

Tools not in that list (read-only checks, diagnostics, searches) don't need confirmation - just use them.

# Asking the person a question (ask_user)

If you need the person to choose between options before proceeding, speak the question and the choices yourself, out loud, in one short sentence (e.g. "Want me to restart the whole stack, or just the worker?"), then call ask_user. Don't call ask_user silently and don't repeat the question back to them - you already asked it out loud. If several options could each map to what they say, ask them to pick just one clearly named thing at a time rather than a long list. If they don't answer, the function result will tell you whether to use your own judgment or stop; follow it and say plainly what you're doing.
"""
