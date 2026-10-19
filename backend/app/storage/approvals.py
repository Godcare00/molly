import json
from datetime import datetime
from typing import Optional, List
from app.storage.database import execute_query, execute_write
from app.security.permissions import ApprovalRecord, ApprovalStatus


def create_approval(approval: ApprovalRecord) -> ApprovalRecord:
    execute_write(
        """INSERT INTO approvals (id, task_id, conversation_id, tool_call_id, tool_name, arguments, risk_level, reason, status, user_instruction, created_at, updated_at, expires_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            approval.id,
            approval.task_id,
            approval.conversation_id,
            approval.tool_call_id,
            approval.tool,
            json.dumps(approval.arguments),
            approval.risk_level,
            approval.reason,
            approval.status.value,
            approval.user_instruction,
            approval.created_at.isoformat(),
            approval.updated_at.isoformat(),
            approval.expires_at.isoformat() if approval.expires_at else None,
        ),
    )
    return approval


def get_approval(approval_id: str) -> Optional[ApprovalRecord]:
    rows = execute_query("SELECT * FROM approvals WHERE id = ?", (approval_id,))
    if not rows:
        return None
    return _row_to_approval(rows[0])


def get_approvals(
    conversation_id: Optional[str] = None,
    task_id: Optional[str] = None,
    status: Optional[ApprovalStatus] = None,
    limit: int = 50,
) -> List[ApprovalRecord]:
    query = "SELECT * FROM approvals WHERE 1=1"
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
    return [_row_to_approval(r) for r in rows]


def update_approval(approval: ApprovalRecord) -> ApprovalRecord:
    execute_write(
        """UPDATE approvals SET
           status = ?, user_instruction = ?, updated_at = ?, expires_at = ?, executed_at = ?, execution_result = ?
           WHERE id = ?""",
        (
            approval.status.value,
            approval.user_instruction,
            approval.updated_at.isoformat(),
            approval.expires_at.isoformat() if approval.expires_at else None,
            approval.executed_at.isoformat() if approval.executed_at else None,
            json.dumps(approval.execution_result) if approval.execution_result else None,
            approval.id,
        ),
    )
    return approval


def _row_to_approval(row) -> ApprovalRecord:
    return ApprovalRecord(
        id=row["id"],
        task_id=row["task_id"],
        conversation_id=row["conversation_id"],
        tool_call_id=row["tool_call_id"],
        tool=row["tool_name"],
        arguments=json.loads(row["arguments"] or "{}"),
        risk_level=row["risk_level"],
        reason=row["reason"],
        status=ApprovalStatus(row["status"]),
        user_instruction=row["user_instruction"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        expires_at=datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None,
        executed_at=datetime.fromisoformat(row["executed_at"]) if row["executed_at"] else None,
        execution_result=json.loads(row["execution_result"]) if row["execution_result"] else None,
    )