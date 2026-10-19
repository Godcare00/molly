"""
The "connect" flow: pairing a new device by combining two independent
proofs before granting trust —

  1. Shell access to the VPS (proven by possessing a local secret file that
     only a process running on the box, as the same OS user, can read —
     that's what `molly connect` sends when it asks the backend for a
     connect URL).
  2. Possession of the phone app instance (proven by the short pairing code
     the app displays, which the operator copies into the browser page the
     connect URL points at).

Neither proof alone is sufficient — a leaked pairing code is useless
without the connect URL, and vice versa.
"""
import os
import secrets
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Tuple

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.config import auth_settings
from app.auth.device_keys import DeviceKeyManager
from app.auth.models import ConnectSession, Device


class LocalSecretError(Exception):
    """Raised when the caller can't prove it's running on the VPS itself."""


def _local_secret_path() -> Path:
    return Path(auth_settings.connect_local_secret_path).resolve()


def ensure_local_secret() -> str:
    """
    Get (or create, on first run) the local secret that proves a process is
    running on this machine as this OS user. Only `molly connect` and the
    backend itself ever read this file.
    """
    path = _local_secret_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        secret = secrets.token_urlsafe(32)
        path.write_text(secret)
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600 — owner only
    return path.read_text().strip()


def verify_local_secret(request: Request) -> None:
    """Raise LocalSecretError unless the request carries the correct local secret."""
    provided = request.headers.get("x-local-secret", "")
    expected = ensure_local_secret()
    if not provided or not secrets.compare_digest(provided, expected):
        raise LocalSecretError("Missing or invalid local secret")


class ConnectManager:
    """Manages CLI-issued connect sessions and their browser-side approval."""

    @staticmethod
    async def create_session(db_session: AsyncSession) -> ConnectSession:
        session = ConnectSession(
            token=secrets.token_urlsafe(24),
            status="pending",
            expires_at=datetime.now(timezone.utc)
            + timedelta(minutes=auth_settings.connect_session_expire_minutes),
        )
        db_session.add(session)
        await db_session.flush()
        return session

    @staticmethod
    def _is_expired(expires_at: datetime) -> bool:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at < datetime.now(timezone.utc)

    @classmethod
    async def get_session(cls, db_session: AsyncSession, token: str) -> Optional[ConnectSession]:
        session = await db_session.get(ConnectSession, token)
        if session and session.status == "pending" and cls._is_expired(session.expires_at):
            session.status = "expired"
            await db_session.flush()
        return session

    @classmethod
    async def approve(
        cls,
        db_session: AsyncSession,
        session_token: str,
        code: str,
    ) -> Tuple[ConnectSession, Device]:
        """
        Confirm a device's pairing code against a pending connect session.
        Raises ValueError with a generic message on any failure — callers
        should not learn from the error *why* it failed (session vs. code).
        """
        session = await cls.get_session(db_session, session_token)
        if not session:
            raise ValueError("This connect link is invalid.")
        if session.status != "pending":
            raise ValueError("This connect link has expired or was already used. Run `molly connect` again.")

        if session.attempts >= auth_settings.connect_max_attempts:
            session.status = "expired"
            await db_session.flush()
            raise ValueError("Too many attempts. Run `molly connect` again for a new link.")

        session.attempts += 1

        normalized = DeviceKeyManager.normalize_pairing_code(code)
        result = await db_session.execute(
            select(Device).where(
                Device.pairing_code == normalized,
                Device.is_revoked.is_(False),
                Device.is_trusted.is_(False),
            )
        )
        device = result.scalar_one_or_none()

        if device and device.pairing_code_expires_at and cls._is_expired(device.pairing_code_expires_at):
            device = None

        if not device:
            await db_session.flush()
            raise ValueError("That code is incorrect or has expired.")

        device.is_trusted = True
        device.pairing_code = None
        device.pairing_code_expires_at = None

        session.status = "approved"
        session.approved_device_id = device.id
        session.approved_at = datetime.now(timezone.utc)

        await db_session.flush()
        return session, device
