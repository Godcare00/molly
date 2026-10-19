import json
from datetime import datetime
from typing import Optional, List
from app.storage.database import execute_query, execute_write
from app.security.questionnaire import (
    QuestionnaireRecord,
    QuestionnaireStatus,
    QuestionnaireFallback,
    QuestionOption,
)


def create_questionnaire(record: QuestionnaireRecord) -> QuestionnaireRecord:
    execute_write(
        """INSERT INTO questionnaires (id, task_id, conversation_id, tool_call_id, questions, status, answers,
           timeout_seconds, fallback, created_at, updated_at, expires_at, answered_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            record.id,
            record.task_id,
            record.conversation_id,
            record.tool_call_id,
            json.dumps([q.__dict__ for q in record.questions]),
            record.status.value,
            json.dumps(record.answers) if record.answers is not None else None,
            record.timeout_seconds,
            record.fallback.value,
            record.created_at.isoformat(),
            record.updated_at.isoformat(),
            record.expires_at.isoformat() if record.expires_at else None,
            record.answered_at.isoformat() if record.answered_at else None,
        ),
    )
    return record


def get_questionnaire(questionnaire_id: str) -> Optional[QuestionnaireRecord]:
    rows = execute_query("SELECT * FROM questionnaires WHERE id = ?", (questionnaire_id,))
    if not rows:
        return None
    return _row_to_questionnaire(rows[0])


def get_questionnaires(
    conversation_id: Optional[str] = None,
    task_id: Optional[str] = None,
    status: Optional[QuestionnaireStatus] = None,
    limit: int = 50,
) -> List[QuestionnaireRecord]:
    query = "SELECT * FROM questionnaires WHERE 1=1"
    params = []

    if conversation_id:
        query += " AND conversation_id = ?"
        params.append(conversation_id)
    if task_id:
        query += " AND task_id = ?"
        params.append(task_id)
    if status:
        query += " AND status = ?"
        params.append(status.value)

    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    rows = execute_query(query, tuple(params))
    return [_row_to_questionnaire(r) for r in rows]


def update_questionnaire(record: QuestionnaireRecord) -> QuestionnaireRecord:
    execute_write(
        """UPDATE questionnaires SET
           status = ?, answers = ?, updated_at = ?, expires_at = ?, answered_at = ?
           WHERE id = ?""",
        (
            record.status.value,
            json.dumps(record.answers) if record.answers is not None else None,
            record.updated_at.isoformat(),
            record.expires_at.isoformat() if record.expires_at else None,
            record.answered_at.isoformat() if record.answered_at else None,
            record.id,
        ),
    )
    return record


def _row_to_questionnaire(row) -> QuestionnaireRecord:
    return QuestionnaireRecord(
        id=row["id"],
        task_id=row["task_id"],
        conversation_id=row["conversation_id"],
        tool_call_id=row["tool_call_id"],
        questions=[QuestionOption(**q) for q in json.loads(row["questions"] or "[]")],
        status=QuestionnaireStatus(row["status"]),
        answers=json.loads(row["answers"]) if row["answers"] else None,
        timeout_seconds=row["timeout_seconds"],
        fallback=QuestionnaireFallback(row["fallback"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        expires_at=datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None,
        answered_at=datetime.fromisoformat(row["answered_at"]) if row["answered_at"] else None,
    )
