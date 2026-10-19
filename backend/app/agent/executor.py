import asyncio
import json
import time
from pathlib import Path
from typing import Optional, AsyncGenerator, Dict, Any, List
from datetime import datetime

import structlog

from app.agent.context import ContextManager
from app.agent.state import AgentState, TaskStatus, ToolCallState
from app.agent.tasks import create_task, update_task, save_tool_call
from app.agent.messages import NormalizedMessage
from app.llm.client import get_llm_provider, get_provider_for_mode, get_provider_for_model_selection
from app.llm.base import Message as LLMMessage
from app.tools.registry import registry, ToolResult, RiskLevel
from app.security.permissions import permission_engine, ApprovalRecord
from app.security.questionnaire import questionnaire_engine, QuestionOption, QuestionnaireFallback
from app.storage.approvals import create_approval, update_approval
from app.storage.questionnaires import create_questionnaire, update_questionnaire
from app.storage.conversations import add_message, get_conversation
from app.storage.files import register_generated_file
from app.storage.images import register_generated_image
from app.config import settings

# Metrics
try:
    from app.main import (
        agent_runs_total,
        agent_iterations,
        agent_tool_calls_total,
        agent_tool_duration_seconds,
        approvals_total,
        approval_duration_seconds,
        llm_requests_total,
        llm_tokens_total,
        llm_request_duration_seconds,
        llm_provider_fallback_total,
        METRICS_ENABLED,
    )
except ImportError:
    METRICS_ENABLED = False

logger = structlog.get_logger()


class AgentExecutor:
    """Core agent execution loop."""

    def __init__(self, conversation_id: str, task_id: str = None):
        self.conversation_id = conversation_id
        self.task_id = task_id or f"task_{int(time.time())}"
        self.state: Optional[AgentState] = None
        self.context = ContextManager()
        self.provider = get_llm_provider()  # default; run() may swap this for the bug-bounty override once mode is known
        self._cancelled = False
        self._approval_event: Optional[asyncio.Event] = None
        self._approval_result: Optional[Dict] = None
        self._questionnaire_event: Optional[asyncio.Event] = None
        self._questionnaire_result: Optional[Dict] = None
        self._run_start_time = time.time()
        # Tools the user has said "approve all" on during this task - skip
        # the prompt for the rest of this run only (does not persist beyond
        # this AgentExecutor instance).
        self._trust_scope: set = set()

    async def run(self, user_message: str, image_ids: List[str] = None, file_ids: List[str] = None) -> AsyncGenerator[Dict, None]:
        """Run the agent loop."""
        # Initialize task
        self.state = create_task(self.conversation_id)
        self.task_id = self.state.task_id

        # Initialize context. Mode ("general"/"bug_bounty") lives in the
        # conversation's metadata (see app/api/routes.py's ConversationCreate
        # and the PATCH .../settings endpoint) - same place/pattern as the
        # allow_all flag read later in this file.
        conv_for_mode = get_conversation(self.conversation_id)
        conv_metadata = conv_for_mode.metadata if conv_for_mode else {}
        mode = conv_metadata.get("mode") or "general"
        self.context.initialize(mode=mode)

        # An explicit per-conversation model choice (see the model picker in
        # the mobile app's ChatInput, persisted via PATCH
        # .../settings -> metadata.model) wins over the mode-based default -
        # it's the more specific, more recent user choice. Falls back to
        # get_provider_for_mode() if unset, or if the chosen model no longer
        # matches any configured chain entry (e.g. the chain was edited
        # since this conversation picked it).
        selected_model = conv_metadata.get("model")
        self.provider = None
        if selected_model:
            self.provider = get_provider_for_model_selection(selected_model, conv_metadata.get("model_provider"))
        if self.provider is None:
            self.provider = get_provider_for_mode(mode)

        # reasoning_effort ("off"/"low"/"medium"/"high", also from the
        # model/reasoning picker) is sent on every LLM call in this run, not
        # just the first. This is safe because Anthropic's extended thinking
        # requirement - that the thinking block from a prior assistant turn
        # be preserved verbatim on any later request that includes that
        # turn - is satisfied: response.thinking_blocks gets stored in both
        # the in-memory context (add_assistant_message) and the DB
        # (add_message's metadata) below, and replayed by
        # AnthropicProvider._convert_messages on every subsequent call,
        # including ones reloaded from history in a future run.
        reasoning_effort = conv_metadata.get("reasoning_effort")
        self.context.load_conversation(self.conversation_id)

        # Add user message
        user_msg = self.context.add_user_message(user_message, image_ids, file_ids)
        add_message(
            self.conversation_id,
            "user",
            user_message,
            content_type="text",
            metadata={"image_ids": image_ids or [], "file_ids": file_ids or []},
        )

        # Yield initial state
        yield {"type": "agent_started", "task": self.state.to_dict()}

        try:
            while not self._cancelled and not self.state.is_terminal():
                # Check iteration limits
                if self.state.iterations >= settings.max_iterations:
                    self.state.fail("Max iterations reached")
                    yield {"type": "agent_error", "error": "Max iterations reached"}
                    break

                if self.state.tool_calls and len(self.state.tool_calls) >= settings.max_tool_calls:
                    self.state.fail("Max tool calls reached")
                    yield {"type": "agent_error", "error": "Max tool calls reached"}
                    break

                # Check for repeated tool calls
                if self._detect_loop():
                    self.state.fail("Detected repeated tool calls - possible loop")
                    yield {"type": "agent_error", "error": "Detected repeated tool calls - possible loop"}
                    break

                # Compact context if needed
                self.context.compact_if_needed()

                # Get LLM response
                llm_messages = self.context.get_llm_messages()
                tool_schemas = self.context.get_tool_schemas()

                llm_start = time.time()
                try:
                    response = await self.provider.chat(
                        [LLMMessage(**m) for m in llm_messages],
                        tools=[registry.get_schema(t.name) for t in registry._tools.values()],
                        reasoning_effort=reasoning_effort,
                    )
                    llm_duration = time.time() - llm_start

                    # When the provider is a fallback chain, response.model_used
                    # reflects whichever provider actually served the request
                    # (which may not be the configured primary), so metrics and
                    # logs stay accurate after a failover.
                    used_model = response.model_used or settings.llm_model

                    if METRICS_ENABLED:
                        llm_requests_total.labels(model=used_model, status="success").inc()
                        llm_request_duration_seconds.labels(model=used_model).observe(llm_duration)
                        if response.usage:
                            llm_tokens_total.labels(model=used_model, type="prompt").inc(response.usage.get("prompt_tokens", 0))
                            llm_tokens_total.labels(model=used_model, type="completion").inc(response.usage.get("completion_tokens", 0))
                        if response.provider_attempts and llm_provider_fallback_total is not None:
                            for failed_attempt in response.provider_attempts:
                                llm_provider_fallback_total.labels(
                                    from_provider=failed_attempt["name"],
                                    to_provider=response.provider or used_model,
                                ).inc()

                    if response.provider_attempts:
                        logger.warning(
                            "llm_fallback_used",
                            failed_providers=[a["name"] for a in response.provider_attempts],
                            served_by=response.provider,
                            model=used_model,
                        )
                except Exception as e:
                    if METRICS_ENABLED:
                        llm_requests_total.labels(model=settings.llm_model, status="error").inc()
                    self.state.fail(f"LLM error: {str(e)}")
                    yield {"type": "agent_error", "error": f"LLM error: {str(e)}"}
                    break

                # Handle response
                if response.tool_calls:
                    # Persist the assistant's tool-call turn *before* executing
                    # any tools. Both the Anthropic and OpenAI APIs require a
                    # tool_result/tool message to be immediately preceded by
                    # the assistant turn that issued the matching tool call —
                    # otherwise the next LLM request (later this run, or a
                    # future turn reloaded from the DB) is malformed and the
                    # provider will reject it.
                    self.context.add_assistant_message(response.content, response.tool_calls, response.thinking_blocks)
                    add_message(
                        self.conversation_id,
                        "assistant",
                        response.content or "",
                        content_type="tool_call",
                        tool_calls=response.tool_calls,
                        metadata={"thinking_blocks": response.thinking_blocks} if response.thinking_blocks else None,
                    )

                    # Tool calls - process each
                    for tool_call in response.tool_calls:
                        async for event in self._execute_tool_call(tool_call):
                            yield event
                        if self.state.is_terminal() or self._cancelled:
                            break
                else:
                    # Final response
                    attachments = self.state.metadata.get("attachments", [])
                    self.context.add_assistant_message(response.content)
                    add_message(
                        self.conversation_id,
                        "assistant",
                        response.content,
                        metadata={"attachments": attachments} if attachments else None,
                    )
                    self.state.complete(response.content)
                    yield {
                        "type": "agent_completed",
                        "response": response.content,
                        **({"attachments": attachments} if attachments else {}),
                    }
                    break

        except asyncio.CancelledError:
            self.state.cancel()
            yield {"type": "agent_cancelled"}
            if METRICS_ENABLED:
                agent_runs_total.labels(status="cancelled").inc()
        except Exception as e:
            self.state.fail(f"Execution error: {str(e)}")
            yield {"type": "agent_error", "error": str(e)}
            if METRICS_ENABLED:
                agent_runs_total.labels(status="failed").inc()
        finally:
            if METRICS_ENABLED and self.state.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                agent_runs_total.labels(status=self.state.status.value).inc()
                agent_iterations.observe(self.state.iterations)
            update_task(self.state)

    def _persist_tool_result(self, tool_call_id: str, tool_name: str, result: Any, success: bool) -> None:
        """Record a tool result in the in-memory context *and* the DB.

        Every tool_use/tool_calls entry emitted by the assistant must be
        followed by exactly one matching tool result, or the next request to
        the LLM (this run, or a future one reloaded from the DB) is malformed.
        Using the context's own (possibly truncated) content keeps the two
        copies of the message consistent.
        """
        msg = self.context.add_tool_result(tool_call_id, tool_name, result, success=success)
        add_message(
            self.conversation_id,
            "tool",
            msg.content,
            content_type="tool_result",
            tool_call_id=tool_call_id,
            metadata={"tool_name": tool_name, "success": success},
        )

    async def _register_shared_attachment(self, result: ToolResult) -> Optional[Dict[str, Any]]:
        """Turn a successful share_file result into a persisted, downloadable
        attachment for this conversation.

        The tool (app/tools/sharing.py) only validates the source path and
        signals intent via `result.metadata["share_as_attachment"]` — it has
        no conversation_id to work with. The executor is the layer that does,
        so it's the one that actually copies the file into conversation
        storage and gives it a file_id/image_id. Runs after the tool result
        is already persisted, so a failure here never orphans a tool_result.
        """
        if not result.metadata.get("share_as_attachment"):
            return None

        source_path = result.metadata.get("resolved_path")
        filename = result.metadata.get("share_filename")
        mime_type = result.metadata.get("share_mime_type")
        kind = (result.output or {}).get("kind", "file") if isinstance(result.output, dict) else "file"

        try:
            if kind == "image":
                image_meta = await register_generated_image(self.conversation_id, source_path, mime_type)
                attachment = {
                    "type": "image",
                    "id": image_meta.id,
                    "filename": filename or Path(source_path).name,
                    "mime_type": image_meta.mime_type,
                    "size_bytes": image_meta.size_bytes,
                    "url": f"/conversations/{self.conversation_id}/images/{image_meta.id}/content",
                }
            else:
                file_meta = await register_generated_file(self.conversation_id, source_path, filename, mime_type)
                attachment = {
                    "type": "file",
                    "id": file_meta.id,
                    "filename": file_meta.filename,
                    "mime_type": file_meta.mime_type,
                    "size_bytes": file_meta.size_bytes,
                    "url": f"/conversations/{self.conversation_id}/files/{file_meta.id}/content",
                }
        except Exception as e:
            logger.warning("share_file_registration_failed", error=str(e), path=source_path)
            return None

        self.state.metadata.setdefault("attachments", []).append(attachment)
        return attachment

    async def _execute_tool_call(self, tool_call: Dict) -> AsyncGenerator[Dict, None]:
        """Execute a single tool call with approval if needed."""
        tool_name = tool_call["function"]["name"]
        arguments = json.loads(tool_call["function"]["arguments"])
        tool_call_id = tool_call["id"]

        # Get tool
        tool = registry.get(tool_name)
        if not tool:
            error = f"Unknown tool: {tool_name}"
            self._persist_tool_result(tool_call_id, tool_name, error, success=False)
            yield {"type": "tool_error", "tool_call_id": tool_call_id, "error": error}
            return

        # Record tool call start
        call_state = self.state.add_tool_call(tool_name, arguments)
        call_state.started_at = datetime.utcnow()

        # ask_user is handled entirely separately from the risk/approval path:
        # it's not gating a dangerous action, it's the tool itself pausing to
        # collect a decision from the user, with its own timeout + fallback.
        # It mutates `arguments` in place (adding _answers/_timed_out) and
        # falls through to the normal "Execute the tool" block below, same
        # as every other tool - so results are persisted, saved, and yielded
        # the same way.
        if tool_name == "ask_user":
            async for event in self._run_questionnaire(tool_call_id, arguments):
                if event.get("type") == "questionnaire_failed":
                    call_state.status = "failed"
                    call_state.error = event["error"]
                    yield event
                    return
                yield event

        # Evaluate risk
        cwd = arguments.get("cwd")
        assessment = permission_engine.evaluate(tool_name, arguments, cwd)

        # A conversation-level "allow_all" setting or a task-level "approve
        # all <tool>" trust from earlier in this run can skip the prompt for
        # anything below the DANGEROUS/CRITICAL hard floor - see
        # PermissionEngine.requires_approval.
        conv = get_conversation(self.conversation_id)
        allow_all = bool(conv.metadata.get("allow_all")) if conv else False

        if RiskLevel.requires_approval(assessment.level) and not permission_engine.requires_approval(
            assessment, allow_all=allow_all, trusted_tools=self._trust_scope, tool_name=tool_name
        ):
            # Still record it for the audit trail, just pre-approved with no wait.
            approval = permission_engine.create_approval(
                task_id=self.state.task_id,
                conversation_id=self.conversation_id,
                tool_call_id=tool_call_id,
                tool=tool_name,
                arguments=arguments,
                assessment=assessment,
            )
            approval = permission_engine.approve(approval)
            create_approval(approval)
            call_state.approval_id = approval.id
            yield {
                "type": "approval_auto",
                "approval_id": approval.id,
                "tool": tool_name,
                "risk_level": assessment.level,
                "reason": "allow_all" if allow_all else "trusted_for_task",
            }

        # Check if approval needed
        elif permission_engine.requires_approval(
            assessment, allow_all=allow_all, trusted_tools=self._trust_scope, tool_name=tool_name
        ):
            # Create approval
            approval = permission_engine.create_approval(
                task_id=self.state.task_id,
                conversation_id=self.conversation_id,
                tool_call_id=tool_call_id,
                tool=tool_name,
                arguments=arguments,
                assessment=assessment,
            )
            create_approval(approval)
            call_state.approval_id = approval.id
            self.state.set_waiting_approval(approval.id)

            # Yield approval required event
            yield {
                "type": "approval_required",
                "approval_id": approval.id,
                "tool": tool_name,
                "risk_level": assessment.level,
                "reason": assessment.reason,
                "arguments": arguments,
            }

            # Wait for approval
            approval_start = time.time()
            await self._wait_for_approval(approval.id)
            approval_duration = time.time() - approval_start

            # Check approval result
            if self._approval_result is None:
                # Timeout or cancelled
                self.state.fail("Approval timed out or cancelled")
                if METRICS_ENABLED:
                    approvals_total.labels(tool=tool_name, risk_level=assessment.level, outcome="timeout").inc()
                    approval_duration_seconds.labels(outcome="timeout").observe(approval_duration)
                yield {"type": "approval_timeout", "approval_id": approval.id}
                return

            action = self._approval_result["action"]
            if action == "reject":
                # User rejected
                self._persist_tool_result(tool_call_id, tool_name, "User rejected the action", success=False)
                update_approval(permission_engine.reject(approval))
                if METRICS_ENABLED:
                    approvals_total.labels(tool=tool_name, risk_level=assessment.level, outcome="rejected").inc()
                    approval_duration_seconds.labels(outcome="rejected").observe(approval_duration)
                yield {"type": "approval_rejected", "approval_id": approval.id}
                return

            elif action == "correct":
                # User corrected - feed correction back to agent
                correction = self._approval_result.get("instruction", "")
                update_approval(permission_engine.correct(approval, correction))

                # A tool result must still close out the pending tool call
                # before we add a new user turn, or the assistant's tool_calls
                # turn is left unmatched in history.
                self._persist_tool_result(
                    tool_call_id, tool_name, f"User requested a correction: {correction}", success=False
                )

                # Add correction as user message for agent to reconsider
                correction_msg = f"User corrected the previous action: {correction}"
                self.context.add_user_message(correction_msg)
                add_message(self.conversation_id, "user", correction_msg)

                # Don't execute original - let agent generate new action
                if METRICS_ENABLED:
                    approvals_total.labels(tool=tool_name, risk_level=assessment.level, outcome="corrected").inc()
                    approval_duration_seconds.labels(outcome="corrected").observe(approval_duration)
                yield {"type": "approval_corrected", "approval_id": approval.id, "instruction": correction}
                return

            elif action in ("approve", "approve_all"):
                # User approved - continue to execution. "approve_all" also
                # trusts this tool for the rest of the task, so later calls
                # to it in this run skip the prompt (see the allow_all/
                # trusted_tools check above).
                update_approval(permission_engine.approve(approval))
                if action == "approve_all":
                    self._trust_scope.add(tool_name)
                if METRICS_ENABLED:
                    approvals_total.labels(tool=tool_name, risk_level=assessment.level, outcome="approved").inc()
                    approval_duration_seconds.labels(outcome="approved").observe(approval_duration)
                yield {
                    "type": "approval_approved",
                    "approval_id": approval.id,
                    "tool": tool_name,
                    "scope": "task" if action == "approve_all" else "once",
                }

        # Execute the tool
        yield {"type": "tool_started", "tool_call_id": tool_call_id, "tool": tool_name, "arguments": arguments}

        call_state.status = "executing"
        permission_engine.start_execution(call_state.approval_id) if call_state.approval_id else None

        tool_start = time.time()
        try:
            # Execute with timeout
            result = await asyncio.wait_for(
                tool.execute(**arguments),
                timeout=tool.timeout_seconds,
            )
            tool_duration = time.time() - tool_start
            call_state.complete_at = datetime.utcnow()

            if METRICS_ENABLED:
                agent_tool_calls_total.labels(tool=tool_name, status="success" if result.success else "failed").inc()
                agent_tool_duration_seconds.labels(tool=tool_name).observe(tool_duration)

            if result.success:
                call_state.status = "completed"
                call_state.result = result.output
                self._persist_tool_result(tool_call_id, tool_name, result.output, success=True)

                # Save to DB
                save_tool_call(self.state.task_id, call_state)

                if call_state.approval_id:
                    approval = get_approval(call_state.approval_id)
                    if approval:
                        update_approval(permission_engine.complete_execution(approval, result.output))

                attachment = await self._register_shared_attachment(result)

                yield {
                    "type": "tool_completed",
                    "tool_call_id": tool_call_id,
                    "tool": tool_name,
                    "result": result.output,
                    "truncated": result.truncated,
                    **({"attachment": attachment} if attachment else {}),
                }
            else:
                call_state.status = "failed"
                call_state.error = result.error
                self._persist_tool_result(tool_call_id, tool_name, result.error, success=False)

                if call_state.approval_id:
                    approval = get_approval(call_state.approval_id)
                    if approval:
                        update_approval(permission_engine.fail_execution(approval, result.error))

                yield {
                    "type": "tool_failed",
                    "tool_call_id": tool_call_id,
                    "tool": tool_name,
                    "error": result.error,
                }

        except asyncio.TimeoutError:
            tool_duration = time.time() - tool_start
            call_state.status = "failed"
            call_state.error = f"Tool timed out after {tool.timeout_seconds}s"
            self._persist_tool_result(tool_call_id, tool_name, call_state.error, success=False)
            if METRICS_ENABLED:
                agent_tool_calls_total.labels(tool=tool_name, status="timeout").inc()
                agent_tool_duration_seconds.labels(tool=tool_name).observe(tool_duration)
            yield {"type": "tool_timeout", "tool_call_id": tool_call_id, "tool": tool_name}

        except Exception as e:
            tool_duration = time.time() - tool_start
            call_state.status = "failed"
            call_state.error = str(e)
            self._persist_tool_result(tool_call_id, tool_name, str(e), success=False)
            if METRICS_ENABLED:
                agent_tool_calls_total.labels(tool=tool_name, status="error").inc()
                agent_tool_duration_seconds.labels(tool=tool_name).observe(tool_duration)
            yield {"type": "tool_error", "tool_call_id": tool_call_id, "tool": tool_name, "error": str(e)}

        finally:
            self.state.current_tool_call = None
            update_task(self.state)

    def _wait_for_approval(self, approval_id: str):
        """Wait for approval decision."""
        self._approval_event = asyncio.Event()
        self._approval_result = None
        return self._approval_event.wait()

    def resolve_approval(self, approval_id: str, action: str, instruction: str = None):
        """Resolve a pending approval (called from API)."""
        if self.state and self.state.pending_approval_id == approval_id:
            self._approval_result = {"action": action, "instruction": instruction}
            if self._approval_event:
                self._approval_event.set()

    async def _run_questionnaire(self, tool_call_id: str, arguments: Dict) -> AsyncGenerator[Dict, None]:
        """Create the questionnaire, wait for an answer or time out, then
        stash the outcome into `arguments` for the tool's own execute() to
        pick up. Unlike approvals this has a real enforced timeout - if
        nobody answers in `timeout_seconds`, we resolve it ourselves rather
        than leaving the run hanging."""
        raw_questions = arguments.get("questions", [])
        try:
            questions = [
                QuestionOption(
                    question=q["question"],
                    options=q["options"],
                    type=q.get("type", "single"),
                )
                for q in raw_questions
            ]
        except (KeyError, TypeError) as e:
            yield {"type": "questionnaire_failed", "tool_call_id": tool_call_id, "error": f"Malformed questions: {e}"}
            return

        timeout_seconds = int(arguments.get("timeout_seconds") or 300)
        fallback_raw = arguments.get("fallback") or QuestionnaireFallback.LET_MOLLY_DECIDE.value
        try:
            fallback = QuestionnaireFallback(fallback_raw)
        except ValueError:
            fallback = QuestionnaireFallback.LET_MOLLY_DECIDE

        record = questionnaire_engine.create_questionnaire(
            task_id=self.state.task_id,
            conversation_id=self.conversation_id,
            tool_call_id=tool_call_id,
            questions=questions,
            timeout_seconds=timeout_seconds,
            fallback=fallback,
        )
        create_questionnaire(record)
        self.state.set_waiting_questionnaire(record.id)

        yield {
            "type": "questionnaire_required",
            "questionnaire_id": record.id,
            "tool_call_id": tool_call_id,
            "questions": [q.__dict__ for q in questions],
            "timeout_seconds": timeout_seconds,
            "fallback": fallback.value,
        }

        try:
            await asyncio.wait_for(self._wait_for_questionnaire(record.id), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            pass  # handled uniformly below via self._questionnaire_result being None

        self.state.resume_from_questionnaire(record.id)

        if self._questionnaire_result is not None:
            # Answered before the timeout fired.
            answers = self._questionnaire_result["answers"]
            update_questionnaire(questionnaire_engine.answer(record, answers))
            arguments["_answers"] = answers
            arguments["_timed_out"] = False
            yield {"type": "questionnaire_answered", "questionnaire_id": record.id, "answers": answers}
        else:
            # Timed out - apply the fallback the caller asked for.
            update_questionnaire(questionnaire_engine.time_out(record))
            arguments["_answers"] = None
            arguments["_timed_out"] = True
            yield {"type": "questionnaire_timeout", "questionnaire_id": record.id, "fallback": fallback.value}

    def _wait_for_questionnaire(self, questionnaire_id: str):
        """Wait for the user's answers (bounded by asyncio.wait_for in the caller)."""
        self._questionnaire_event = asyncio.Event()
        self._questionnaire_result = None
        return self._questionnaire_event.wait()

    def resolve_questionnaire(self, questionnaire_id: str, answers: List[List[str]]):
        """Resolve a pending questionnaire (called from API/websocket)."""
        if self.state and self.state.pending_questionnaire_id == questionnaire_id:
            self._questionnaire_result = {"answers": answers}
            if self._questionnaire_event:
                self._questionnaire_event.set()

    def cancel(self):
        """Cancel the agent run."""
        self._cancelled = True

    def _detect_loop(self) -> bool:
        """Detect repeated identical tool calls."""
        if len(self.state.tool_calls) < 3:
            return False

        recent = self.state.tool_calls[-3:]
        if all(c.tool_name == recent[0].tool_name for c in recent):
            if all(c.arguments == recent[0].arguments for c in recent):
                return True
        return False


# Import at bottom to avoid circular import
from app.storage.approvals import get_approval