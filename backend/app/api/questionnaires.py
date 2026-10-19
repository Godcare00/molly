from fastapi import APIRouter, HTTPException, Depends
from typing import Optional, List
from pydantic import BaseModel

from app.storage.questionnaires import get_questionnaire, get_questionnaires
from app.security.questionnaire import QuestionnaireStatus
from app.auth.dependencies import get_current_user

router = APIRouter(prefix="/questionnaires", tags=["questionnaires"], dependencies=[Depends(get_current_user)])


class RespondRequest(BaseModel):
    # One entry per question, in the same order as `questions`; each entry
    # is a list of the option label(s) picked (len 1 for type="single").
    answers: List[List[str]]


@router.get("")
async def list_questionnaires(
    conversation_id: Optional[str] = None,
    task_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
):
    """List questionnaires with optional filters."""
    status_enum = None
    if status:
        try:
            status_enum = QuestionnaireStatus(status.upper())
        except ValueError:
            raise HTTPException(400, f"Invalid status: {status}")

    records = get_questionnaires(conversation_id, task_id, status_enum, limit)
    return [_serialize(r) for r in records]


@router.get("/{questionnaire_id}")
async def get_questionnaire_detail(questionnaire_id: str):
    """Get questionnaire details."""
    record = get_questionnaire(questionnaire_id)
    if not record:
        raise HTTPException(404, "Questionnaire not found")
    return _serialize(record)


@router.post("/{questionnaire_id}/respond")
async def respond(questionnaire_id: str, request: RespondRequest):
    """Submit the user's answers for a pending questionnaire.

    This only validates and returns the current record - actually waking up
    the waiting AgentExecutor happens over the conversation's websocket
    connection (a `questionnaire_response` message), the same way
    `approval_response` resolves approvals. This REST endpoint exists so the
    app has a durable record/fallback path even if the socket dropped.
    """
    record = get_questionnaire(questionnaire_id)
    if not record:
        raise HTTPException(404, "Questionnaire not found")

    if record.status != QuestionnaireStatus.PENDING:
        raise HTTPException(400, f"Questionnaire is not pending: {record.status.value}")

    if len(request.answers) != len(record.questions):
        raise HTTPException(400, f"Expected {len(record.questions)} answers, got {len(request.answers)}")

    return {"status": "accepted", "questionnaire_id": questionnaire_id, "answers": request.answers}


def _serialize(record) -> dict:
    return {
        "id": record.id,
        "task_id": record.task_id,
        "conversation_id": record.conversation_id,
        "tool_call_id": record.tool_call_id,
        "questions": [q.__dict__ for q in record.questions],
        "status": record.status.value,
        "answers": record.answers,
        "timeout_seconds": record.timeout_seconds,
        "fallback": record.fallback.value,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "expires_at": record.expires_at.isoformat() if record.expires_at else None,
        "answered_at": record.answered_at.isoformat() if record.answered_at else None,
    }
