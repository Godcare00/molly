import json
from datetime import datetime
from typing import Optional, List
from app.storage.database import execute_query, execute_write
from app.agent.state import TaskStatus, AgentState, ToolCallState


def create_task(conversation_id: str, metadata: dict = None) -> AgentState:
    """Create a new task."""
    from datetime import datetime
    import uuid

    task_id = f"task_{uuid.uuid4().hex[:12]}"
    now = datetime.utcnow().isoformat()

    execute_write(
        """INSERT INTO tasks (id, conversation_id, status, created_at, updated_at, metadata)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (task_id, conversation_id, TaskStatus.RUNNING.value, now, now, json.dumps(metadata or {})),
    )

    return AgentState(
        task_id=task_id,
        conversation_id=conversation_id,
        status=TaskStatus.RUNNING,
        metadata=metadata or {},
    )


def get_task(task_id: str) -> Optional[AgentState]:
    rows = execute_query("SELECT * FROM tasks WHERE id = ?", (task_id,))
    if not rows:
        return None
    return _row_to_task(rows[0])


def get_conversation_tasks(conversation_id: str, limit: int = 20) -> List[AgentState]:
    rows = execute_query(
        "SELECT * FROM tasks WHERE conversation_id = ? ORDER BY created_at DESC LIMIT ?",
        (conversation_id, limit),
    )
    return [_row_to_task(r) for r in rows]


def update_task(task: AgentState) -> AgentState:
    execute_write(
        """UPDATE tasks SET
           status = ?, updated_at = ?, completed_at = ?, error = ?, metadata = ?
           WHERE id = ?""",
        (
            task.status.value,
            task.updated_at.isoformat(),
            task.updated_at.isoformat() if task.is_terminal() else None,
            task.error,
            json.dumps(task.metadata),
            task.task_id,
        ),
    )
    return task


def save_tool_call(task_id: str, tool_call: ToolCallState) -> None:
    execute_write(
        """INSERT INTO tool_calls (id, task_id, tool_name, arguments, result, risk_level, status, started_at, completed_at, error, approval_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            tool_call.id,
            task_id,
            tool_call.tool_name,
            json.dumps(tool_call.arguments),
            json.dumps(tool_call.result) if tool_call.result else None,
            tool_call.metadata.get("risk_level") if hasattr(tool_call, "metadata") else None,
            tool_call.status,
            tool_call.started_at.isoformat() if tool_call.started_at else None,
            tool_call.completed_at.isoformat() if tool_call.completed_at else None,
            tool_call.error,
            tool_call.approval_id,
        ),
    )


def _row_to_task(row) -> AgentState:
    task = AgentState(
        task_id=row["id"],
        conversation_id=row["conversation_id"],
        status=TaskStatus(row["status"]),
        error=row["error"],
        metadata=json.loads(row["metadata"] or "{}"),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )
    return task