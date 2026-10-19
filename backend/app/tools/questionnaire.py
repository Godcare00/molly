from typing import Any
from app.tools.registry import BaseTool, ToolResult, RiskLevel, ToolSchema, ToolParameter, registry


class AskUserTool(BaseTool):
    """Ask the user one or more multiple-choice questions and wait for their picks.

    This is a pure information-gathering tool - it never touches the system,
    so it's RiskLevel.READ and never goes through the approval gate. The
    actual "wait for a human" mechanics are handled specially in
    AgentExecutor._execute_tool_call, the same way approval-required tool
    calls are, because this tool doesn't do its own work: it just blocks
    until the questionnaire is answered or times out, then returns whatever
    the executor put in `arguments["_answers"]`.
    """

    name = "ask_user"
    description = (
        "Ask the user to choose between options before proceeding, e.g. when a decision is ambiguous, "
        "subjective, or would change something outside the current project's scope. Renders in the app as "
        "a small form with radio buttons (type='single') or checkboxes (type='multi'). If the user doesn't "
        "respond within timeout_seconds, Molly proceeds using its own best judgment by default."
    )
    risk_level = RiskLevel.READ
    timeout_seconds = 600  # generous - this tool's own wall-clock wait is governed by the questionnaire's timeout_seconds arg, not this
    output_limit_chars = 4000

    async def execute(
        self,
        questions: list,
        timeout_seconds: int = 300,
        fallback: str = "let_molly_decide",
        _answers: Any = None,
        _timed_out: bool = False,
    ) -> ToolResult:
        """Executed only after the executor has resolved the wait.

        `_answers` and `_timed_out` are injected by AgentExecutor once the
        questionnaire is answered or times out - they're not part of the
        schema exposed to the LLM (stripped in get_schema below).
        """
        if _timed_out:
            if fallback == "cancel":
                return ToolResult(
                    success=False,
                    error="The user did not respond in time. No answers were provided.",
                )
            return ToolResult(
                success=True,
                output="The user did not respond in time. Use your own best judgment and proceed.",
                metadata={"timed_out": True, "fallback": fallback},
            )

        return ToolResult(success=True, output={"answers": _answers}, metadata={"timed_out": False})

    def get_schema(self) -> ToolSchema:
        # Hand-written schema instead of the auto-generated one, since the
        # `questions` parameter is structured (list of {question, options,
        # type}) rather than a flat scalar, and `_answers`/`_timed_out` are
        # internal-only and must never be exposed to the model.
        return ToolSchema(
            name=self.name,
            description=self.description,
            parameters=[
                ToolParameter(
                    name="questions",
                    type="array",
                    description=(
                        "List of questions, each: {question: string, options: string[], "
                        "type: 'single' | 'multi'}. Keep options short - they render as buttons/checkboxes."
                    ),
                    required=True,
                ),
                ToolParameter(
                    name="timeout_seconds",
                    type="integer",
                    description="How long to wait for the user before falling back. Default 300 (5 minutes).",
                    required=False,
                    default=300,
                ),
                ToolParameter(
                    name="fallback",
                    type="string",
                    description=(
                        "What to do if the user doesn't respond in time. 'let_molly_decide' (default): proceed "
                        "using your own judgment. 'cancel': treat it as unanswered and stop."
                    ),
                    required=False,
                    default="let_molly_decide",
                    enum=["let_molly_decide", "cancel"],
                ),
            ],
            risk_level=self.risk_level,
            timeout_seconds=self.timeout_seconds,
            output_limit_chars=self.output_limit_chars,
        )


def register_questionnaire_tools():
    registry.register(AskUserTool())
