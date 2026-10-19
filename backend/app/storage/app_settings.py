"""Generic key/value settings storage, backed by SQLite (the app_settings
table in app/storage/database.py) rather than .env. Use this for
preferences that are per-install operator choices someone might change
often through the app - the .env file (app/config.py + persist_env_vars)
is for the handful of settings that make sense as process-startup
environment configuration (the primary LLM provider chain, server host/
port, etc).

First (and so far only) consumer: the bug-bounty model override in
app/api/settings.py / app/llm/client.py.
"""
import json
from datetime import datetime
from typing import Any, Optional

from app.storage.database import execute_query, execute_write


def get_json(key: str, default: Any = None) -> Any:
    """Fetch and JSON-decode a stored value, or `default` if unset."""
    rows = execute_query("SELECT value FROM app_settings WHERE key = ?", (key,))
    if not rows:
        return default
    try:
        return json.loads(rows[0]["value"])
    except (TypeError, ValueError):
        return default


def set_json(key: str, value: Any) -> None:
    """Store a JSON-serializable value, upserting by key."""
    execute_write(
        """
        INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """,
        (key, json.dumps(value), datetime.utcnow().isoformat()),
    )


def delete(key: str) -> None:
    execute_write("DELETE FROM app_settings WHERE key = ?", (key,))
