from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List
from datetime import datetime, timedelta
import uuid


class QuestionnaireStatus(str, Enum):
    PENDING = "PENDING"
    ANSWERED = "ANSWERED"
    TIMED_OUT = "TIMED_OUT"  # timer expired - fell back per `fallback`
    CANCELLED = "CANCELLED"


class QuestionnaireFallback(str, Enum):
    # What happens if the user doesn't respond in time.
    LET_MOLLY_DECIDE = "let_molly_decide"  # agent gets a synthetic answer telling it to use its own judgment
    CANCEL = "cancel"  # agent gets told the question went unanswered and to stop/ask again later


@dataclass
class QuestionOption:
    question: str
    options: List[str]
    type: str = "single"  # "single" (radio) or "multi" (checkboxes)


@dataclass
class QuestionnaireRecord:
    id: str
    task_id: str
    conversation_id: str
    tool_call_id: str
    questions: List[QuestionOption]
    status: QuestionnaireStatus = QuestionnaireStatus.PENDING
    answers: Optional[List[List[str]]] = None  # selected option(s) per question, same order as `questions`
    timeout_seconds: int = 300
    fallback: QuestionnaireFallback = QuestionnaireFallback.LET_MOLLY_DECIDE
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    answered_at: Optional[datetime] = None

    def is_terminal(self) -> bool:
        return self.status in (
            QuestionnaireStatus.ANSWERED,
            QuestionnaireStatus.TIMED_OUT,
            QuestionnaireStatus.CANCELLED,
        )


class QuestionnaireEngine:
    """Create and resolve `ask_user` questionnaires."""

    def __init__(self, default_timeout_seconds: int = 300):
        self.default_timeout_seconds = default_timeout_seconds

    def create_questionnaire(
        self,
        task_id: str,
        conversation_id: str,
        tool_call_id: str,
        questions: List[QuestionOption],
        timeout_seconds: Optional[int] = None,
        fallback: QuestionnaireFallback = QuestionnaireFallback.LET_MOLLY_DECIDE,
    ) -> QuestionnaireRecord:
        timeout = timeout_seconds or self.default_timeout_seconds
        return QuestionnaireRecord(
            id=f"ques_{uuid.uuid4().hex[:12]}",
            task_id=task_id,
            conversation_id=conversation_id,
            tool_call_id=tool_call_id,
            questions=questions,
            status=QuestionnaireStatus.PENDING,
            timeout_seconds=timeout,
            fallback=fallback,
            expires_at=datetime.utcnow() + timedelta(seconds=timeout),
        )

    def answer(self, record: QuestionnaireRecord, answers: List[List[str]]) -> QuestionnaireRecord:
        record.status = QuestionnaireStatus.ANSWERED
        record.answers = answers
        record.answered_at = datetime.utcnow()
        record.updated_at = datetime.utcnow()
        return record

    def time_out(self, record: QuestionnaireRecord) -> QuestionnaireRecord:
        record.status = QuestionnaireStatus.TIMED_OUT
        record.updated_at = datetime.utcnow()
        return record

    def cancel(self, record: QuestionnaireRecord) -> QuestionnaireRecord:
        record.status = QuestionnaireStatus.CANCELLED
        record.updated_at = datetime.utcnow()
        return record


# Global engine instance
questionnaire_engine = QuestionnaireEngine()
