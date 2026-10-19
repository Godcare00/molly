"""Hands-free voice counterpart to app/agent/executor.py's AgentExecutor.

Owns one Gemini Live session for one conversation. Function calls coming
back from Gemini are routed through the exact same risk-classifier /
approval-engine / tool-registry pipeline text mode uses, and this yields the
same event vocabulary (approval_required, tool_started, tool_completed, ...)
plus a handful of live-only events (live_started, audio_output,
live_transcript, live_interrupted, live_stopped, live_error) - so the
existing approval card in the app keeps working completely unmodified,
whether the person taps it or answers Molly out loud.

Concurrency note: a dedicated `_pump_gemini_events` task continuously drains
the Gemini session and is the sole owner of transcript-buffering state. This
matters because handling a function call can block for minutes waiting on a
person's spoken "confirm" - if event draining happened inline in the same
loop that processes/yields events (as in AgentExecutor, which doesn't have
this problem because it isn't a live stream), Gemini's audio and the
person's "confirm" utterance would sit stuck in the pipe behind the paused
function-call handler and the session would deadlock. The pump keeps
consuming, checks each transcript fragment against the pending confirmation
immediately, and only then hands the event to the slower consumer loop.
"""

import asyncio
import base64
import json
import time
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional

import structlog

from app.agent.context import DEFAULT_SYSTEM_PROMPT
from app.agent.live_voice import parse_voice_decision, parse_voice_choice
from app.agent.state import AgentState
from app.agent.tasks import create_task, save_tool_call, update_task
from app.config import settings
from app.llm.gemini_live import GeminiLiveSession, LiveEvent, LiveFunctionCall, build_voice_system_instruction
from app.security.permissions import permission_engine
from app.security.questionnaire import questionnaire_engine, QuestionOption, QuestionnaireFallback
from app.storage.approvals import create_approval, update_approval
from app.storage.questionnaires import create_questionnaire, update_questionnaire
from app.storage.conversations import add_message, get_conversation
from app.tools.registry import RiskLevel, registry

logger = structlog.get_logger()


def _serialize_tool_output(value: Any) -> str:
    if isinstance(value, str):
        return value[: settings.max_tool_output_chars]
    try:
        return json.dumps(value, default=str)[: settings.max_tool_output_chars]
    except (TypeError, ValueError):
        return str(value)[: settings.max_tool_output_chars]


class LiveAgentExecutor:
    def __init__(self, conversation_id: str):
        self.conversation_id = conversation_id
        self.state: Optional[AgentState] = None
        self._session: Optional[GeminiLiveSession] = None
        self._raw_events: "asyncio.Queue[LiveEvent]" = asyncio.Queue()
        self._pump_task: Optional[asyncio.Task] = None
        self._cancelled = False

        # Dual-channel approval resolution: whichever of "spoken confirm
        # word" / "app tap" resolves first wins. Only one approval is ever
        # pending at a time in live mode (Gemini function calling is
        # synchronous - it blocks on this one before issuing another).
        self._pending_approval_id: Optional[str] = None
        self._pending_voice_decision: Optional[asyncio.Future] = None
        self._app_approval_event: Optional[asyncio.Event] = None
        self._app_approval_result: Optional[Dict[str, Any]] = None

        # Tools trusted for the rest of this task via an "approve all" tap
        # in the app (spoken decisions don't currently offer this - see
        # _handle_function_call).
        self._trust_scope: set = set()

        # ask_user in voice mode: only one spoken-answer wait is ever
        # pending at a time (same reasoning as approvals - Gemini function
        # calling is synchronous), tracked separately from approval state
        # since the two can never overlap but shouldn't share a name.
        self._pending_answer_future: Optional[asyncio.Future] = None
        self._pending_answer_options: List[str] = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> AsyncGenerator[Dict, None]:
        self.state = create_task(self.conversation_id, metadata={"channel": "live_voice"})

        confirm_gated_tools = sorted(set(
            registry.get_tool_names_by_risk(RiskLevel.MODERATE)
            + registry.get_tool_names_by_risk(RiskLevel.HIGH_RISK)
            + registry.get_tool_names_by_risk(RiskLevel.DANGEROUS)
            + registry.get_tool_names_by_risk(RiskLevel.CRITICAL)
        ))
        base_prompt = DEFAULT_SYSTEM_PROMPT.format(tool_names=", ".join(registry.list_tools()))
        system_instruction = build_voice_system_instruction(base_prompt, confirm_gated_tools)

        try:
            self._session = GeminiLiveSession(
                system_instruction=system_instruction,
                tool_declarations=registry.get_all_gemini_schemas(),
            )
            await self._session.__aenter__()
        except Exception as e:
            logger.error("live_session_connect_failed", error=str(e), conversation_id=self.conversation_id)
            self.state.fail(str(e))
            update_task(self.state)
            yield {"type": "live_error", "error": f"Couldn't start voice session: {e}"}
            yield {"type": "live_stopped"}
            return

        self._pump_task = asyncio.ensure_future(self._pump_gemini_events())
        yield {"type": "live_started", "task_id": self.state.task_id}

        deadline = time.monotonic() + settings.live_session_max_minutes * 60
        try:
            while not self._cancelled:
                try:
                    event = await asyncio.wait_for(self._raw_events.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    if time.monotonic() > deadline:
                        yield {
                            "type": "live_error",
                            "error": "Voice session reached its time limit - reconnect to start a fresh one.",
                        }
                        break
                    continue

                async for out in self._handle_event(event):
                    yield out

                if event.kind == "closed":
                    break
        finally:
            await self._shutdown()
            yield {"type": "live_stopped"}

    async def stop(self) -> None:
        self._cancelled = True

    def cancel(self) -> None:
        self._cancelled = True
        # Unblock anything waiting on an approval so shutdown isn't stuck.
        if self._app_approval_event:
            self._app_approval_event.set()
        if self._pending_voice_decision and not self._pending_voice_decision.done():
            self._pending_voice_decision.cancel()
        if self._pending_answer_future and not self._pending_answer_future.done():
            self._pending_answer_future.cancel()

    async def _shutdown(self) -> None:
        if self._pump_task:
            self._pump_task.cancel()
        if self._session:
            try:
                await self._session.__aexit__(None, None, None)
            except Exception:
                pass
            self._session = None
        if self.state and not self.state.is_terminal():
            self.state.complete("voice session ended")
            update_task(self.state)

    # ------------------------------------------------------------------
    # Inbound audio (from the mobile client)
    # ------------------------------------------------------------------

    async def push_audio_chunk(self, pcm16_16k: bytes) -> None:
        if self._session:
            await self._session.send_audio_chunk(pcm16_16k)

    async def push_audio_stream_end(self) -> None:
        if self._session:
            await self._session.send_audio_stream_end()

    # ------------------------------------------------------------------
    # Approval resolution from the app (dual-channel with voice)
    # ------------------------------------------------------------------

    def resolve_approval_from_app(self, approval_id: str, action: str, instruction: str = None) -> None:
        if self._pending_approval_id == approval_id and self._app_approval_event:
            self._app_approval_result = {"action": action, "instruction": instruction}
            self._app_approval_event.set()

    # ------------------------------------------------------------------
    # Gemini event pump - see module docstring for why this is separate
    # from the consumer loop in start().
    # ------------------------------------------------------------------

    async def _pump_gemini_events(self) -> None:
        input_buf: List[str] = []
        output_buf: List[str] = []
        try:
            async for event in self._session.events():
                if event.kind == "input_transcript" and event.text:
                    input_buf.append(event.text)
                    if self._pending_voice_decision and not self._pending_voice_decision.done():
                        decision = parse_voice_decision(
                            "".join(input_buf),
                            settings.live_voice_confirm_words_list,
                            settings.live_voice_cancel_words_list,
                        )
                        if decision:
                            self._pending_voice_decision.set_result(decision)
                    if self._pending_answer_future and not self._pending_answer_future.done():
                        choice = parse_voice_choice("".join(input_buf), self._pending_answer_options)
                        if choice:
                            self._pending_answer_future.set_result(choice)
                    await self._raw_events.put(event)

                elif event.kind == "output_transcript" and event.text:
                    output_buf.append(event.text)
                    await self._raw_events.put(event)

                elif event.kind == "turn_complete":
                    if input_buf:
                        await self._raw_events.put(LiveEvent(kind="user_utterance_final", text="".join(input_buf)))
                        input_buf = []
                    if output_buf:
                        await self._raw_events.put(LiveEvent(kind="assistant_utterance_final", text="".join(output_buf)))
                        output_buf = []
                    await self._raw_events.put(event)

                else:
                    await self._raw_events.put(event)

                if event.kind == "closed":
                    return
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("live_event_pump_error", error=str(e), conversation_id=self.conversation_id)
            await self._raw_events.put(LiveEvent(kind="error", message=str(e)))
            await self._raw_events.put(LiveEvent(kind="closed"))

    # ------------------------------------------------------------------
    # Event -> WS translation
    # ------------------------------------------------------------------

    async def _handle_event(self, event: LiveEvent) -> AsyncGenerator[Dict, None]:
        if event.kind == "audio":
            yield {"type": "audio_output", "data": base64.b64encode(event.audio).decode("ascii")}

        elif event.kind == "input_transcript":
            yield {"type": "live_transcript", "role": "user", "text": event.text, "final": False}

        elif event.kind == "output_transcript":
            yield {"type": "live_transcript", "role": "assistant", "text": event.text, "final": False}

        elif event.kind == "user_utterance_final":
            text = event.text.strip()
            if text:
                add_message(self.conversation_id, "user", text, content_type="voice", metadata={"channel": "live_voice"})
                yield {"type": "live_transcript", "role": "user", "text": text, "final": True}

        elif event.kind == "assistant_utterance_final":
            text = event.text.strip()
            if text:
                add_message(self.conversation_id, "assistant", text, content_type="voice", metadata={"channel": "live_voice"})
                yield {"type": "live_transcript", "role": "assistant", "text": text, "final": True}

        elif event.kind == "interrupted":
            yield {"type": "live_interrupted"}

        elif event.kind == "function_calls":
            for call in event.function_calls:
                async for out in self._handle_function_call(call):
                    yield out

        elif event.kind in ("go_away", "error"):
            yield {"type": "live_error", "error": event.message or "Live session error"}

        # "turn_complete" and "closed" carry no direct UI event of their own.

    async def _handle_function_call(self, call: LiveFunctionCall) -> AsyncGenerator[Dict, None]:
        tool_name = call.name
        arguments = call.args or {}

        tool = registry.get(tool_name)
        if not tool:
            await self._session.send_tool_response(call.id, tool_name, {"status": "error", "error": f"Unknown tool: {tool_name}"})
            yield {"type": "tool_error", "tool_call_id": call.id, "tool": tool_name, "error": "Unknown tool"}
            return

        call_state = self.state.add_tool_call(tool_name, arguments)
        call_state.started_at = datetime.utcnow()

        if tool_name == "ask_user":
            async for out in self._handle_ask_user(call, arguments, call_state):
                yield out
            return

        assessment = permission_engine.evaluate(tool_name, arguments, arguments.get("cwd"))
        approval = None

        conv = get_conversation(self.conversation_id)
        allow_all = bool(conv.metadata.get("allow_all")) if conv else False

        if RiskLevel.requires_approval(assessment.level) and not permission_engine.requires_approval(
            assessment, allow_all=allow_all, trusted_tools=self._trust_scope, tool_name=tool_name
        ):
            approval = permission_engine.create_approval(
                task_id=self.state.task_id,
                conversation_id=self.conversation_id,
                tool_call_id=call.id,
                tool=tool_name,
                arguments=arguments,
                assessment=assessment,
            )
            approval = permission_engine.approve(approval)
            create_approval(approval)
            call_state.approval_id = approval.id

        elif permission_engine.requires_approval(
            assessment, allow_all=allow_all, trusted_tools=self._trust_scope, tool_name=tool_name
        ):
            approval = permission_engine.create_approval(
                task_id=self.state.task_id,
                conversation_id=self.conversation_id,
                tool_call_id=call.id,
                tool=tool_name,
                arguments=arguments,
                assessment=assessment,
            )
            create_approval(approval)
            call_state.approval_id = approval.id
            self.state.set_waiting_approval(approval.id)

            yield {
                "type": "approval_required",
                "approval_id": approval.id,
                "tool": tool_name,
                "risk_level": assessment.level,
                "reason": assessment.reason,
                "arguments": arguments,
            }

            decision, instruction = await self._wait_for_dual_channel_decision(approval.id)

            if decision is None:
                update_approval(permission_engine.expire(approval))
                await self._session.send_tool_response(
                    call.id, tool_name,
                    {"status": "timed_out", "message": "The person did not respond in time. Do not retry - tell them plainly it timed out."},
                )
                yield {"type": "approval_timeout", "approval_id": approval.id}
                return

            if decision == "reject":
                update_approval(permission_engine.reject(approval))
                self._persist_tool_result_message(call.id, tool_name, "User rejected the action", success=False)
                await self._session.send_tool_response(
                    call.id, tool_name,
                    {"status": "rejected", "message": "The person said no. Acknowledge and stop - do not retry or rephrase."},
                )
                yield {"type": "approval_rejected", "approval_id": approval.id}
                return

            if decision == "correct":
                update_approval(permission_engine.correct(approval, instruction or ""))
                await self._session.send_tool_response(
                    call.id, tool_name,
                    {"status": "rejected", "message": "The person wants something different - see their next message."},
                )
                yield {"type": "approval_corrected", "approval_id": approval.id, "instruction": instruction}
                if instruction:
                    await self._session.send_text(instruction)
                return

            # decision == "approve" (spoken confirm only offers this; an app
            # tap can also send "approve_all", which additionally trusts
            # this tool for the rest of the task)
            update_approval(permission_engine.approve(approval))
            if decision == "approve_all":
                self._trust_scope.add(tool_name)

        yield {"type": "tool_started", "tool_call_id": call.id, "tool": tool_name, "arguments": arguments}
        call_state.status = "executing"
        if approval:
            update_approval(permission_engine.start_execution(approval))

        try:
            result = await asyncio.wait_for(tool.execute(**arguments), timeout=tool.timeout_seconds)
            call_state.completed_at = datetime.utcnow()

            if result.success:
                call_state.status = "completed"
                call_state.result = result.output
                self._persist_tool_result_message(call.id, tool_name, result.output, success=True)
                save_tool_call(self.state.task_id, call_state)
                if approval:
                    update_approval(permission_engine.complete_execution(approval, result.output))
                await self._session.send_tool_response(call.id, tool_name, {"status": "ok", "result": result.output})
                yield {
                    "type": "tool_completed",
                    "tool_call_id": call.id,
                    "tool": tool_name,
                    "result": result.output,
                    "truncated": result.truncated,
                }
            else:
                call_state.status = "failed"
                call_state.error = result.error
                self._persist_tool_result_message(call.id, tool_name, result.error, success=False)
                if approval:
                    update_approval(permission_engine.fail_execution(approval, result.error))
                await self._session.send_tool_response(call.id, tool_name, {"status": "error", "error": result.error})
                yield {"type": "tool_failed", "tool_call_id": call.id, "tool": tool_name, "error": result.error}

        except asyncio.TimeoutError:
            call_state.status = "failed"
            call_state.error = f"Tool timed out after {tool.timeout_seconds}s"
            self._persist_tool_result_message(call.id, tool_name, call_state.error, success=False)
            if approval:
                update_approval(permission_engine.fail_execution(approval, call_state.error))
            await self._session.send_tool_response(call.id, tool_name, {"status": "error", "error": call_state.error})
            yield {"type": "tool_timeout", "tool_call_id": call.id, "tool": tool_name}

        except Exception as e:
            call_state.status = "failed"
            call_state.error = str(e)
            self._persist_tool_result_message(call.id, tool_name, str(e), success=False)
            if approval:
                update_approval(permission_engine.fail_execution(approval, str(e)))
            await self._session.send_tool_response(call.id, tool_name, {"status": "error", "error": str(e)})
            yield {"type": "tool_error", "tool_call_id": call.id, "tool": tool_name, "error": str(e)}

        finally:
            self.state.current_tool_call = None
            update_task(self.state)
            self._pending_approval_id = None
            self._pending_voice_decision = None

    async def _handle_ask_user(self, call: LiveFunctionCall, arguments: Dict, call_state) -> AsyncGenerator[Dict, None]:
        """Voice counterpart of AgentExecutor._run_questionnaire. No form:
        Molly has already spoken the question per the voice system prompt,
        so this just listens for the spoken answer, matched question-by-
        question against that question's own options via parse_voice_choice.
        Persisted the same way as text mode for a consistent audit trail.
        """
        tool_name = "ask_user"
        raw_questions = arguments.get("questions", [])
        try:
            questions = [
                QuestionOption(question=q["question"], options=q["options"], type=q.get("type", "single"))
                for q in raw_questions
            ]
        except (KeyError, TypeError) as e:
            await self._session.send_tool_response(call.id, tool_name, {"status": "error", "error": f"Malformed questions: {e}"})
            yield {"type": "questionnaire_failed", "tool_call_id": call.id, "error": str(e)}
            return

        timeout_seconds = int(arguments.get("timeout_seconds") or 300)
        try:
            fallback = QuestionnaireFallback(arguments.get("fallback") or QuestionnaireFallback.LET_MOLLY_DECIDE.value)
        except ValueError:
            fallback = QuestionnaireFallback.LET_MOLLY_DECIDE

        record = questionnaire_engine.create_questionnaire(
            task_id=self.state.task_id,
            conversation_id=self.conversation_id,
            tool_call_id=call.id,
            questions=questions,
            timeout_seconds=timeout_seconds,
            fallback=fallback,
        )
        create_questionnaire(record)
        self.state.set_waiting_questionnaire(record.id)
        yield {
            "type": "questionnaire_required",
            "questionnaire_id": record.id,
            "tool_call_id": call.id,
            "questions": [q.__dict__ for q in questions],
            "channel": "voice",
        }

        answers: List[List[str]] = []
        deadline = time.monotonic() + timeout_seconds
        timed_out = False
        for q in questions:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            picked = await self._wait_for_spoken_answer(q.options, remaining)
            if picked is None:
                timed_out = True
                break
            answers.append(picked)

        self.state.resume_from_questionnaire(record.id)

        if not timed_out:
            update_questionnaire(questionnaire_engine.answer(record, answers))
            await self._session.send_tool_response(call.id, tool_name, {"status": "ok", "result": {"answers": answers}})
            yield {"type": "questionnaire_answered", "questionnaire_id": record.id, "answers": answers}
        else:
            update_questionnaire(questionnaire_engine.time_out(record))
            if fallback == QuestionnaireFallback.CANCEL:
                await self._session.send_tool_response(
                    call.id, tool_name,
                    {"status": "timed_out", "message": "The person didn't answer. Do not retry - tell them plainly and stop."},
                )
            else:
                await self._session.send_tool_response(
                    call.id, tool_name,
                    {"status": "timed_out", "message": "The person didn't answer in time. Use your own best judgment and proceed, and say plainly that's what you're doing."},
                )
            yield {"type": "questionnaire_timeout", "questionnaire_id": record.id, "fallback": fallback.value}

        call_state.status = "completed" if not timed_out else "failed"
        save_tool_call(self.state.task_id, call_state)
        self.state.current_tool_call = None
        update_task(self.state)

    async def _wait_for_spoken_answer(self, options: List[str], timeout_seconds: float) -> Optional[List[str]]:
        """Block until a finalized user utterance resolves to one or more of
        `options` (see parse_voice_choice), or the timeout elapses."""
        self._pending_answer_future = asyncio.get_running_loop().create_future()
        self._pending_answer_options = options
        try:
            return await asyncio.wait_for(self._pending_answer_future, timeout=timeout_seconds)
        except asyncio.TimeoutError:
            return None
        finally:
            self._pending_answer_future = None
            self._pending_answer_options = []

    async def _wait_for_dual_channel_decision(self, approval_id: str):
        """Returns (decision, instruction). decision is "approve" / "reject"
        / "correct" / None (timed out). Whichever of the voice channel (a
        spoken confirm/cancel word, detected by the event pump) or the app
        channel (a tap on the approval card) resolves first wins; the other
        is simply left to fire into a resolved/cancelled future and ignored.
        """
        self._pending_approval_id = approval_id
        self._pending_voice_decision = asyncio.get_running_loop().create_future()
        self._app_approval_event = asyncio.Event()
        self._app_approval_result = None

        voice_task = asyncio.ensure_future(self._pending_voice_decision)
        app_task = asyncio.ensure_future(self._app_approval_event.wait())

        try:
            done, pending = await asyncio.wait(
                [voice_task, app_task],
                timeout=settings.approval_timeout_minutes * 60,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for p in pending:
                p.cancel()

            if voice_task in done and not voice_task.cancelled():
                return voice_task.result(), None
            if app_task in done and self._app_approval_result:
                return self._app_approval_result["action"], self._app_approval_result.get("instruction")
            return None, None
        finally:
            self._pending_approval_id = None

    def _persist_tool_result_message(self, tool_call_id: str, tool_name: str, result: Any, success: bool) -> None:
        add_message(
            self.conversation_id,
            "tool",
            _serialize_tool_output(result),
            content_type="tool_result",
            tool_call_id=tool_call_id,
            metadata={"tool_name": tool_name, "success": success, "channel": "live_voice"},
        )
