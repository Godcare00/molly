"""
Device pairing, take two: no admin, no browser, one code.

  vps:   molly connect
         -> POST /worker/pairing-codes  (authenticated as the worker itself)
         -> prints the returned code in the terminal
  phone: user types that code into the app
         -> POST /devices/pair {code, name, platform}
         -> gets back a real access/refresh token pair immediately

Whoever can read the code printed on the server's own terminal is trusted to
pair a device - the same trust model the original single-tenant
`molly connect` used (there, proximity to the box was proven by reading a
local secret file; here, by the worker itself - already trusted by the
gateway from enrollment - being the one asking for the code on the
operator's behalf). There's no separate tenant-admin approval step.
"""
from __future__ import annotations

import secrets
import time
from collections import defaultdict, deque
from datetime import timedelta
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import AccessClaims, TokenError, issue_token_pair, verify_user_token
from app.auth.worker_auth import get_authenticated_worker
from app.config import settings
from app.db import get_db
from app.models import Device, PairingCode, Worker
from app.timeutils import utcnow

router = APIRouter()

# Excludes visually-ambiguous characters (0/O, 1/I/L) since this is meant
# to be read off a terminal and typed on a phone keyboard.
_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
_CODE_LENGTH = 8


def _generate_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))


@router.post("/worker/pairing-codes")
async def create_pairing_code(worker: Worker = Depends(get_authenticated_worker), db: AsyncSession = Depends(get_db)):
    code = _generate_code()
    db.add(PairingCode(
        code=code,
        tenant_id=worker.tenant_id,
        worker_id=worker.id,
        expires_at=utcnow() + timedelta(minutes=settings.pairing_code_ttl_minutes),
    ))
    await db.commit()
    return {"code": code, "expires_in_minutes": settings.pairing_code_ttl_minutes}


# --- naive per-IP rate limiting on the code-guessing surface below ---
#
# /devices/pair is the one endpoint in this service an unauthenticated
# caller gets to repeatedly guess a short human-typeable secret against.
# A 33^8 code space and a short TTL already make brute-forcing
# impractical, but a request-rate cap costs nothing and closes off doing
# it faster than intended. This is an in-memory, single-process
# stand-in - put a real rate limiter (e.g. at a reverse proxy, or
# slowapi keyed through the same Redis used for multi-process routing)
# in front of this in production.
_attempts: dict[str, deque] = defaultdict(deque)
_RATE_LIMIT_WINDOW_SECONDS = 60
_RATE_LIMIT_MAX_ATTEMPTS = 20


def _check_rate_limit(client_ip: str) -> None:
    now = time.monotonic()
    window = _attempts[client_ip]
    while window and window[0] < now - _RATE_LIMIT_WINDOW_SECONDS:
        window.popleft()
    if len(window) >= _RATE_LIMIT_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many pairing attempts - try again in a minute")
    window.append(now)


class PairBody(BaseModel):
    code: str
    name: str = ""
    platform: str = ""


@router.post("/devices/pair")
async def pair_device(
    body: PairBody,
    request: Request,
    authorization: Annotated[Optional[str], Header()] = None,
    db: AsyncSession = Depends(get_db),
):
    _check_rate_limit(request.client.host if request.client else "unknown")

    code = body.code.strip().upper()
    row = await db.get(PairingCode, code)
    now = utcnow()
    if not row or row.used_at is not None or row.expires_at < now:
        raise HTTPException(status_code=400, detail="Invalid or expired code")

    # Optional: if the phone is already logged into a real account (see
    # api/account.py's /auth/login), attach the resulting device to that
    # user instead of leaving it anonymous - purely additive, the code
    # alone is still sufficient to pair exactly as before. A logged-in
    # session for a *different* tenant than the code belongs to is
    # rejected outright rather than silently ignored, since silently
    # dropping it would let someone believe their account is attached
    # when it isn't.
    user_id: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        try:
            claims = verify_user_token(authorization.split(" ", 1)[1])
        except TokenError:
            raise HTTPException(status_code=401, detail="Invalid or expired session")
        if claims.tenant_id != row.tenant_id:
            raise HTTPException(status_code=403, detail="This account can't pair a device with that code")
        user_id = claims.user_id

    device = Device(
        tenant_id=row.tenant_id,
        user_id=user_id,
        name=body.name,
        platform=body.platform,
        default_worker_id=row.worker_id,
        is_trusted=True,
    )
    db.add(device)
    await db.flush()  # assigns device.id before we reference it below

    row.used_at = now
    row.device_id = device.id
    await db.commit()
    await db.refresh(device)

    pair = await issue_token_pair(db, AccessClaims(
        tenant_id=device.tenant_id,
        user_id=device.user_id or f"tenant:{device.tenant_id}",
        device_id=device.id,
        role="member",
        default_worker_id=device.default_worker_id,
    ))
    return {**pair.model_dump(), "default_worker_id": device.default_worker_id}
