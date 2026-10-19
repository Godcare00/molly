import json
import uuid
from datetime import datetime
from typing import Optional, List
from dataclasses import dataclass, asdict
from app.storage.database import execute_query, execute_write, execute_many
from app.config import settings


@dataclass
class Conversation:
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    metadata: dict

    @classmethod
    def from_row(cls, row) -> "Conversation":
        return cls(
            id=row["id"],
            title=row["title"] or "",
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            metadata=json.loads(row["metadata"] or "{}"),
        )


@dataclass
class Message:
    id: str
    conversation_id: str
    role: str
    content: str
    content_type: str
    tool_calls: Optional[str]
    tool_call_id: Optional[str]
    metadata: dict
    created_at: datetime

    @classmethod
    def from_row(cls, row) -> "Message":
        return cls(
            id=row["id"],
            conversation_id=row["conversation_id"],
            role=row["role"],
            content=row["content"],
            content_type=row["content_type"] or "text",
            tool_calls=row["tool_calls"],
            tool_call_id=row["tool_call_id"],
            metadata=json.loads(row["metadata"] or "{}"),
            created_at=datetime.fromisoformat(row["created_at"]),
        )


def create_conversation(title: str = "", metadata: Optional[dict] = None) -> Conversation:
    conv_id = f"conv_{uuid.uuid4().hex[:12]}"
    now = datetime.utcnow().isoformat()
    metadata = metadata or {}

    execute_write(
        "INSERT INTO conversations (id, title, created_at, updated_at, metadata) VALUES (?, ?, ?, ?, ?)",
        (conv_id, title, now, now, json.dumps(metadata)),
    )

    return Conversation(
        id=conv_id,
        title=title,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        metadata=metadata,
    )


def get_conversation(conv_id: str) -> Optional[Conversation]:
    rows = execute_query("SELECT * FROM conversations WHERE id = ?", (conv_id,))
    if not rows:
        return None
    return Conversation.from_row(rows[0])


def list_conversations(limit: int = 50, offset: int = 0) -> List[Conversation]:
    rows = execute_query(
        "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    )
    return [Conversation.from_row(r) for r in rows]


def update_conversation(conv_id: str, title: Optional[str] = None, metadata: Optional[dict] = None) -> bool:
    updates = []
    params = []

    if title is not None:
        updates.append("title = ?")
        params.append(title)
    if metadata is not None:
        updates.append("metadata = ?")
        params.append(json.dumps(metadata))

    if not updates:
        return False

    updates.append("updated_at = ?")
    params.append(datetime.utcnow().isoformat())
    params.append(conv_id)

    execute_write(f"UPDATE conversations SET {', '.join(updates)} WHERE id = ?", tuple(params))
    return True


def delete_conversation(conv_id: str) -> bool:
    execute_write("DELETE FROM conversations WHERE id = ?", (conv_id,))
    return True


def add_message(
    conversation_id: str,
    role: str,
    content: str,
    content_type: str = "text",
    tool_calls: Optional[list] = None,
    tool_call_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> Message:
    msg_id = f"msg_{uuid.uuid4().hex[:12]}"
    now = datetime.utcnow().isoformat()

    execute_write(
        """INSERT INTO messages (id, conversation_id, role, content, content_type, tool_calls, tool_call_id, metadata, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            msg_id,
            conversation_id,
            role,
            content,
            content_type,
            json.dumps(tool_calls) if tool_calls else None,
            tool_call_id,
            json.dumps(metadata or {}),
            now,
        ),
    )

    # Update conversation timestamp
    execute_write(
        "UPDATE conversations SET updated_at = ? WHERE id = ?",
        (now, conversation_id),
    )

    return Message(
        id=msg_id,
        conversation_id=conversation_id,
        role=role,
        content=content,
        content_type=content_type,
        tool_calls=json.dumps(tool_calls) if tool_calls else None,
        tool_call_id=tool_call_id,
        metadata=metadata or {},
        created_at=datetime.utcnow(),
    )


def get_messages(conversation_id: str, limit: int = 100, offset: int = 0) -> List[Message]:
    rows = execute_query(
        "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC LIMIT ? OFFSET ?",
        (conversation_id, limit, offset),
    )
    return [Message.from_row(r) for r in rows]


def get_recent_messages(conversation_id: str, limit: int = 20) -> List[Message]:
    rows = execute_query(
        "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at DESC LIMIT ?",
        (conversation_id, limit),
    )
    return [Message.from_row(r) for r in reversed(rows)]