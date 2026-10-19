import sqlite3
import os
from pathlib import Path
from contextlib import contextmanager
from typing import Optional
import threading

from app.config import settings


SCHEMA = """
-- Conversations
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT DEFAULT '{}'
);

-- Messages
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    content_type TEXT DEFAULT 'text',
    tool_calls TEXT,
    tool_call_id TEXT,
    metadata TEXT DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at);

-- Tasks
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    error TEXT,
    metadata TEXT DEFAULT '{}',
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_tasks_conversation ON tasks(conversation_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);

-- Tool Calls
CREATE TABLE IF NOT EXISTS tool_calls (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    arguments TEXT NOT NULL,
    result TEXT,
    risk_level TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    error TEXT,
    approval_id TEXT,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_tool_calls_task ON tool_calls(task_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_approval ON tool_calls(approval_id);

-- Approvals
CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    tool_call_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    arguments TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    user_instruction TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    executed_at TIMESTAMP,
    execution_result TEXT,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status);
CREATE INDEX IF NOT EXISTS idx_approvals_conversation ON approvals(conversation_id);
CREATE INDEX IF NOT EXISTS idx_approvals_task ON approvals(task_id);

-- Questionnaires (ask_user tool: Molly asks the user to pick from options)
CREATE TABLE IF NOT EXISTS questionnaires (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    tool_call_id TEXT NOT NULL,
    questions TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    answers TEXT,
    timeout_seconds INTEGER NOT NULL DEFAULT 300,
    fallback TEXT NOT NULL DEFAULT 'let_molly_decide',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    answered_at TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_questionnaires_status ON questionnaires(status);
CREATE INDEX IF NOT EXISTS idx_questionnaires_conversation ON questionnaires(conversation_id);
CREATE INDEX IF NOT EXISTS idx_questionnaires_task ON questionnaires(task_id);

-- Agent Runs
CREATE TABLE IF NOT EXISTS agent_runs (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    iterations INTEGER DEFAULT 0,
    tool_calls_count INTEGER DEFAULT 0,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    error TEXT,
    metadata TEXT DEFAULT '{}',
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

-- Image Metadata (origin: 'upload' or 'generated' — see files table above)
CREATE TABLE IF NOT EXISTS images (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    path TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    width INTEGER,
    height INTEGER,
    size_bytes INTEGER,
    origin TEXT NOT NULL DEFAULT 'upload',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    viewed_at TIMESTAMP,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_images_conversation ON images(conversation_id);
CREATE INDEX IF NOT EXISTS idx_images_created ON images(created_at);

-- File Metadata (non-image attachments: logs, code, config, csv, etc.)
-- origin: 'upload' (user sent it to Molly) or 'generated' (Molly sent it
-- back via the share_file tool). New databases get the column from this
-- CREATE; existing databases pick it up via the ALTER TABLE in init_db().
CREATE TABLE IF NOT EXISTS files (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    path TEXT NOT NULL,
    filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes INTEGER,
    origin TEXT NOT NULL DEFAULT 'upload',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    viewed_at TIMESTAMP,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_files_conversation ON files(conversation_id);
CREATE INDEX IF NOT EXISTS idx_files_created ON files(created_at);

-- Projects
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    description TEXT,
    stack TEXT DEFAULT '[]',
    repository TEXT,
    branch TEXT,
    environment TEXT,
    services TEXT DEFAULT '[]',
    commands TEXT DEFAULT '{}',
    notes TEXT DEFAULT '[]',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_projects_path ON projects(path);

-- Generic key/value store for settings that are intentionally NOT part of
-- .env (see app/storage/app_settings.py) - e.g. the bug-bounty model
-- override in app/api/settings.py, which the operator wants scoped to this
-- one preference rather than mixed into the backend's environment config.
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

_DB_LOCK = threading.Lock()
_connection: Optional[sqlite3.Connection] = None


def get_db_path() -> Path:
    return settings.database_path_resolved


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    """SQLite has no `ADD COLUMN IF NOT EXISTS`, so check first. Safe to call
    on every startup — a no-op once the column exists."""
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_db() -> None:
    """Initialize the database schema."""
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA)
        # Migrate databases created before the `origin` column existed.
        _add_column_if_missing(conn, "files", "origin", "origin TEXT NOT NULL DEFAULT 'upload'")
        _add_column_if_missing(conn, "images", "origin", "origin TEXT NOT NULL DEFAULT 'upload'")
        conn.commit()


@contextmanager
def get_connection() -> sqlite3.Connection:
    """Get a database connection with row factory."""
    global _connection
    with _DB_LOCK:
        if _connection is None:
            db_path = get_db_path()
            _connection = sqlite3.connect(db_path, check_same_thread=False)
            _connection.row_factory = sqlite3.Row
            _connection.execute("PRAGMA foreign_keys = ON")
        yield _connection


def execute_query(query: str, params: tuple = ()) -> list[sqlite3.Row]:
    """Execute a SELECT query and return rows."""
    with get_connection() as conn:
        cursor = conn.execute(query, params)
        return cursor.fetchall()


def execute_write(query: str, params: tuple = ()) -> int:
    """Execute an INSERT/UPDATE/DELETE query and return lastrowid."""
    with get_connection() as conn:
        cursor = conn.execute(query, params)
        conn.commit()
        return cursor.lastrowid


def execute_many(query: str, params_list: list[tuple]) -> None:
    """Execute multiple queries in a transaction."""
    with get_connection() as conn:
        conn.executemany(query, params_list)
        conn.commit()


def close_db() -> None:
    """Close the database connection."""
    global _connection
    with _DB_LOCK:
        if _connection is not None:
            _connection.close()
            _connection = None