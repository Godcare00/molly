"""
Worker-side half of joining a fleet gateway.

Mirrors app/auth/connect.py's local-secret trick: there, "you can read
this file" proves a process is running on the box. Here, since the
gateway isn't co-located with the server, proof-of-possession happens once,
out of band - the operator runs `molly worker enroll --token <token>` ON
THE server, using a one-time enrollment token they copied from the gateway's
admin dashboard/API. Only someone with a shell on the box could paste it
into a shell running there, which is the same property the local-secret
file gives the existing single-tenant `molly connect` flow.

That one-time token is exchanged for a long-lived {worker_id, worker_token,
worker_secret} triple, cached to disk exactly like ensure_local_secret()
caches its secret - so a restart doesn't require re-enrolling.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Optional

import httpx


class EnrollmentError(Exception):
    pass


def _credential_path() -> Path:
    from app.config import settings
    return Path(settings.database_path_resolved).parent / "gateway_credential.json"


def load_credential() -> Optional[dict]:
    """Returns {worker_id, worker_token, worker_secret, gateway_ws_url} if
    this worker has been enrolled, else None. Cheap enough to call per
    request (get_current_user's relay branch does) - it's a small local
    file read, not a network call."""
    path = _credential_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _save_credential(cred: dict) -> None:
    path = _credential_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cred))
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600 - same permissions as the local-connect secret


async def enroll(gateway_http_url: str, enrollment_token: str, label: str) -> dict:
    """One-time call: trades a short-lived enrollment token (minted by a
    tenant admin on the gateway) for this worker's permanent credential.
    Never call this automatically on startup - it should only run when a
    human deliberately runs `molly worker enroll`, the same way
    `molly connect` is a deliberate, human-initiated action."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{gateway_http_url.rstrip('/')}/admin/workers/enroll",
            json={"enrollment_token": enrollment_token, "label": label},
        )
    if resp.status_code != 200:
        raise EnrollmentError(f"enrollment failed ({resp.status_code}): {resp.text}")

    body = resp.json()
    cred = {
        "worker_id": body["worker_id"],
        "worker_token": body["worker_token"],
        "worker_secret": body["worker_secret"],
        "gateway_ws_url": body.get("gateway_ws_url", ""),
        "gateway_http_url": gateway_http_url,
    }
    _save_credential(cred)
    return cred


def clear_credential() -> None:
    """Removes this worker's fleet enrollment. It keeps working fine
    afterwards as a plain self-hosted worker; it just stops dialing out
    to the gateway on next restart."""
    path = _credential_path()
    if path.exists():
        path.unlink()
