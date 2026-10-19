import base64
import json
from typing import Optional, List, Dict, Any, AsyncIterator, Tuple
import httpx

from app.llm.base import LLMProvider, Message, LLMResponse
from app.tools.registry import ToolSchema


class AnthropicProvider(LLMProvider):
    """Native provider for Anthropic's Messages API (Claude models)."""

    DEFAULT_BASE_URL = "https://api.anthropic.com/v1"
    ANTHROPIC_VERSION = "2023-06-01"

    # Extended-thinking token budgets per reasoning_effort level. Anthropic
    # requires max_tokens > budget_tokens, so callers with a small
    # max_tokens configured get their budget capped in _thinking_config().
    THINKING_BUDGETS = {"low": 2048, "medium": 6000, "high": 16000}

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ):
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self.api_key = api_key
        self.model = model
        self.default_temperature = temperature
        self.default_max_tokens = max_tokens
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": self.ANTHROPIC_VERSION,
                    "content-type": "application/json",
                },
                timeout=httpx.Timeout(120.0, connect=10.0),
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def supports_images(self) -> bool:
        return True

    def get_model_name(self) -> str:
        return self.model

    # ---- encoding helpers -------------------------------------------------

    def _get_mime_type(self, path: str) -> str:
        ext = path.lower().split(".")[-1]
        return {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "webp": "image/webp",
            "gif": "image/gif",
        }.get(ext, "image/png")

    def _image_block(self, img_ref: str) -> Dict:
        """Build an Anthropic image content block from a local path, a data URL,
        or a remote http(s) URL."""
        if img_ref.startswith("data:"):
            header, _, b64data = img_ref.partition(",")
            media_type = header[5:].split(";")[0] or "image/png"
            return {
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": b64data},
            }
        if img_ref.startswith("http://") or img_ref.startswith("https://"):
            return {"type": "image", "source": {"type": "url", "url": img_ref}}

        # Treat as a local file path
        with open(img_ref, "rb") as f:
            data = f.read()
        b64 = base64.b64encode(data).decode("utf-8")
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": self._get_mime_type(img_ref),
                "data": b64,
            },
        }

    # ---- message/tool conversion ------------------------------------------

    def _user_content_blocks(self, msg: Message) -> Any:
        """Build Anthropic content for a user message, tolerating either a plain
        string, a pre-built OpenAI-style content-parts list, and/or msg.images."""
        text_parts: List[str] = []
        image_refs: List[str] = []

        if isinstance(msg.content, str):
            if msg.content:
                text_parts.append(msg.content)
        elif isinstance(msg.content, list):
            for part in msg.content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text" and part.get("text"):
                    text_parts.append(part["text"])
                elif part.get("type") == "image_url":
                    url = (part.get("image_url") or {}).get("url")
                    if url:
                        image_refs.append(url)

        if msg.images:
            image_refs.extend(msg.images)

        if not image_refs:
            # Plain text is valid (and simplest) when there's nothing else to attach.
            return "\n".join(text_parts) if text_parts else ""

        blocks: List[Dict] = []
        if text_parts:
            blocks.append({"type": "text", "text": "\n".join(text_parts)})
        for ref in image_refs:
            blocks.append(self._image_block(ref))
        return blocks

    def _convert_messages(self, messages: List[Message]) -> Tuple[str, List[Dict]]:
        """Convert internal messages to (system_text, anthropic_messages)."""
        system_parts: List[str] = []
        converted: List[Dict] = []

        for msg in messages:
            if msg.role == "system":
                if msg.content:
                    system_parts.append(msg.content)

            elif msg.role == "user":
                converted.append({"role": "user", "content": self._user_content_blocks(msg)})

            elif msg.role == "assistant":
                blocks: List[Dict] = []
                # Thinking blocks (if this turn had any) must come first,
                # exactly as Anthropic originally emitted them - see
                # Message.thinking_blocks. Only meaningful/required when this
                # turn also has tool_calls, but harmless to include either
                # way since it's replaying exactly what this turn actually
                # contained.
                if msg.thinking_blocks:
                    blocks.extend(msg.thinking_blocks)
                if msg.content:
                    blocks.append({"type": "text", "text": msg.content})
                for tc in msg.tool_calls or []:
                    fn = tc.get("function", {})
                    try:
                        tool_input = json.loads(fn.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        tool_input = {}
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc.get("id"),
                            "name": fn.get("name"),
                            "input": tool_input,
                        }
                    )
                content = blocks if (msg.tool_calls or msg.thinking_blocks) else (msg.content or "")
                converted.append({"role": "assistant", "content": content})

            elif msg.role == "tool":
                converted.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": msg.tool_call_id,
                                "content": msg.content or "",
                            }
                        ],
                    }
                )

        # Anthropic requires strictly alternating user/assistant turns - merge
        # any adjacent same-role entries (e.g. consecutive tool results) into one.
        merged: List[Dict] = []
        for entry in converted:
            if merged and merged[-1]["role"] == entry["role"]:
                prev_content = merged[-1]["content"]
                new_content = entry["content"]
                prev_blocks = prev_content if isinstance(prev_content, list) else (
                    [{"type": "text", "text": prev_content}] if prev_content else []
                )
                new_blocks = new_content if isinstance(new_content, list) else (
                    [{"type": "text", "text": new_content}] if new_content else []
                )
                merged[-1]["content"] = prev_blocks + new_blocks
            else:
                merged.append(entry)

        return "\n\n".join(system_parts), merged

    def _convert_tools(self, tools: Optional[List[ToolSchema]]) -> Optional[List[Dict]]:
        if not tools:
            return None
        return [tool.to_anthropic_schema() for tool in tools]

    def _parse_response(self, data: Dict) -> LLMResponse:
        content_text: List[str] = []
        tool_calls: List[Dict] = []
        thinking_blocks: List[Dict] = []

        for block in data.get("content", []) or []:
            block_type = block.get("type")
            if block_type == "text":
                content_text.append(block.get("text", ""))
            elif block_type == "tool_use":
                tool_calls.append(
                    {
                        "id": block.get("id"),
                        "type": "function",
                        "function": {
                            "name": block.get("name"),
                            "arguments": json.dumps(block.get("input", {})),
                        },
                    }
                )
            elif block_type in ("thinking", "redacted_thinking"):
                # Stored and replayed verbatim (see Message.thinking_blocks) -
                # Anthropic includes a `signature` on "thinking" blocks that
                # it validates on replay, so this must stay byte-for-byte
                # identical to what the API sent, not reconstructed.
                thinking_blocks.append(block)

        usage_data = data.get("usage") or {}
        usage = {
            "prompt_tokens": usage_data.get("input_tokens", 0),
            "completion_tokens": usage_data.get("output_tokens", 0),
        }

        return LLMResponse(
            content="".join(content_text),
            tool_calls=tool_calls or None,
            usage=usage,
            finish_reason=data.get("stop_reason"),
            thinking_blocks=thinking_blocks or None,
        )

    def _thinking_config(self, reasoning_effort: Optional[str], max_tokens: int) -> Optional[Dict]:
        """Build the `thinking` payload field for a reasoning_effort level,
        or None if reasoning isn't requested ("off"/None/unrecognized).
        Anthropic requires max_tokens to exceed budget_tokens, so the
        budget is capped to leave room for the actual response - if
        max_tokens is too small to fit any meaningful budget, thinking is
        skipped entirely rather than sending a request that Anthropic
        would just reject."""
        if not reasoning_effort or reasoning_effort == "off":
            return None
        budget = self.THINKING_BUDGETS.get(reasoning_effort)
        if budget is None:
            return None
        # Leave at least 512 tokens for the actual answer after thinking.
        budget = min(budget, max(max_tokens - 512, 0))
        if budget < 256:
            return None
        return {"type": "enabled", "budget_tokens": budget}

    # ---- public API ---------------------------------------------------------

    async def chat(
        self,
        messages: List[Message],
        tools: Optional[List[ToolSchema]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
    ) -> LLMResponse:
        client = await self._get_client()
        system_text, anthropic_messages = self._convert_messages(messages)
        anthropic_tools = self._convert_tools(tools)
        resolved_max_tokens = max_tokens or self.default_max_tokens

        payload: Dict[str, Any] = {
            "model": model or self.model,
            "messages": anthropic_messages,
            "max_tokens": resolved_max_tokens,
        }
        thinking = self._thinking_config(reasoning_effort, resolved_max_tokens)
        if thinking:
            payload["thinking"] = thinking
            # Anthropic requires temperature=1 (or omitted) when thinking is
            # enabled - sending anything else is a 400. Silently overriding
            # here (rather than erroring) keeps "just toggle reasoning on"
            # working without the caller needing to know this constraint.
        else:
            payload["temperature"] = temperature if temperature is not None else self.default_temperature
        if system_text:
            payload["system"] = system_text
        if anthropic_tools:
            payload["tools"] = anthropic_tools

        response = await client.post("/messages", json=payload)
        response.raise_for_status()
        return self._parse_response(response.json())

    async def chat_stream(
        self,
        messages: List[Message],
        tools: Optional[List[ToolSchema]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
    ) -> AsyncIterator[str]:
        client = await self._get_client()
        system_text, anthropic_messages = self._convert_messages(messages)
        anthropic_tools = self._convert_tools(tools)
        resolved_max_tokens = max_tokens or self.default_max_tokens

        payload: Dict[str, Any] = {
            "model": model or self.model,
            "messages": anthropic_messages,
            "max_tokens": resolved_max_tokens,
            "stream": True,
        }
        thinking = self._thinking_config(reasoning_effort, resolved_max_tokens)
        if thinking:
            payload["thinking"] = thinking
        else:
            payload["temperature"] = temperature if temperature is not None else self.default_temperature
        if system_text:
            payload["system"] = system_text
        if anthropic_tools:
            payload["tools"] = anthropic_tools

        async with client.stream("POST", "/messages", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                try:
                    event = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("type")
                if event_type == "content_block_delta":
                    delta = event.get("delta", {})
                    # thinking_delta (the reasoning trace) is intentionally
                    # not yielded here - only the final text answer streams
                    # to the caller, same as before reasoning support existed.
                    if delta.get("type") == "text_delta" and delta.get("text"):
                        yield delta["text"]
                elif event_type == "message_stop":
                    break
