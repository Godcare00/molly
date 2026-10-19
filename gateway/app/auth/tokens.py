"""
Access tokens the gateway issues to a paired mobile device (short-lived,
HS256, verified locally on every request - see verify_access_token) plus
refresh-token issuance/rotation (DB-backed, checked against
app.models.RefreshToken - see api/admin_devices.py for where these are
minted and rotated). This mirrors the worker's original single-tenant
app/auth/jwt.py pattern, with tenant_id threaded through the claims.
"""
from __future__ import annotations

import secrets
import time
import uuid
from datetime import timedelta
from typing import Optional

import jwt as pyjwt
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import RefreshToken
from app.security import hash_secret
from app.timeutils import utcnow


class AccessClaims(BaseModel):
    tenant_id: str
    user_id: str
    device_id: str
    role: str = "member"
    default_worker_id: Optional[str] = None


class UserClaims(BaseModel):
    """Claims for a *user's* logged-in session (see api/account.py's
    /auth/signup and /auth/login) - proof of "which person, on which
    tenant" independent of any paired device. Kept as a distinct JWT
    `type` from AccessClaims's device-scoped "access" tokens so one can
    never be replayed as the other: a stolen device access token can't be
    used to hit account-level endpoints, and vice versa."""
    tenant_id: str
    user_id: str
    email: str
    role: str = "admin"


class TokenError(Exception):
    pass


def mint_access_token(claims: AccessClaims) -> str:
    now = int(time.time())
    payload = claims.model_dump()
    payload.update({
        "iat": now,
        "exp": now + settings.access_token_ttl_minutes * 60,
        "jti": str(uuid.uuid4()),
        "iss": "molly-gateway",
        "type": "access",
    })
    return pyjwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def verify_access_token(token: str) -> AccessClaims:
    try:
        payload = pyjwt.decode(token, settings.jwt_secret, algorithms=["HS256"], issuer="molly-gateway")
    except pyjwt.PyJWTError as e:
        raise TokenError(str(e)) from e
    if payload.get("type") != "access":
        raise TokenError("wrong token type")
    return AccessClaims(**{k: v for k, v in payload.items() if k in AccessClaims.model_fields})


def mint_user_token(claims: UserClaims) -> str:
    now = int(time.time())
    payload = claims.model_dump()
    payload.update({
        "iat": now,
        "exp": now + settings.user_session_ttl_minutes * 60,
        "jti": str(uuid.uuid4()),
        "iss": "molly-gateway",
        "type": "user",
    })
    return pyjwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def verify_user_token(token: str) -> UserClaims:
    try:
        payload = pyjwt.decode(token, settings.jwt_secret, algorithms=["HS256"], issuer="molly-gateway")
    except pyjwt.PyJWTError as e:
        raise TokenError(str(e)) from e
    if payload.get("type") != "user":
        raise TokenError("wrong token type")
    return UserClaims(**{k: v for k, v in payload.items() if k in UserClaims.model_fields})


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_expires_in: int


async def issue_token_pair(db: AsyncSession, claims: AccessClaims) -> TokenPair:
    """Mints a fresh access token plus a brand-new refresh token row.
    Used both at initial pairing and as the *output* of a successful
    rotation in refresh_token_pair below."""
    access_token = mint_access_token(claims)
    raw_refresh = secrets.token_urlsafe(48)
    expires_at = utcnow() + timedelta(days=settings.refresh_token_ttl_days)

    db.add(RefreshToken(
        tenant_id=claims.tenant_id,
        device_id=claims.device_id,
        token_hash=hash_secret(raw_refresh),
        expires_at=expires_at,
    ))
    await db.commit()

    return TokenPair(
        access_token=access_token,
        refresh_token=raw_refresh,
        expires_in=settings.access_token_ttl_minutes * 60,
        refresh_expires_in=settings.refresh_token_ttl_days * 86400,
    )


async def rotate_refresh_token(db: AsyncSession, raw_refresh_token: str) -> TokenPair:
    """Verifies a refresh token against the DB, then rotates it: the
    presented token is marked used (revoked_at set, replaced_by points at
    the new row) and a brand-new refresh token is issued alongside a new
    access token. A refresh token can only ever be redeemed once - reusing
    an already-rotated one is refused, not silently re-served, since that
    reuse is the signal a token was stolen and replayed rather than just
    that the client's clock is a bit off.
    """
    # token_hash is a unique-indexed column, so this is a direct lookup,
    # not a scan-and-compare over every issued refresh token.
    result = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == hash_secret(raw_refresh_token)))
    row = result.scalar_one_or_none()
    if not row:
        raise TokenError("unknown refresh token")
    if row.revoked_at is not None:
        raise TokenError("refresh token already used or revoked")
    if row.expires_at < utcnow():
        raise TokenError("refresh token expired")

    from app.models import Device  # local import: avoids a cycle with models importing back into auth

    device = await db.get(Device, row.device_id)
    if not device or not device.is_trusted or device.is_revoked:
        raise TokenError("device no longer authorized")

    claims = AccessClaims(
        tenant_id=row.tenant_id,
        user_id=device.user_id or f"tenant:{device.tenant_id}",
        device_id=device.id,
        role="member",
        default_worker_id=device.default_worker_id,
    )
    pair = await issue_token_pair(db, claims)

    # Look up the row we just created via issue_token_pair to link the
    # rotation chain - cheap (indexed hash lookup) and keeps issue_token_pair
    # from needing to know anything about rotation.
    new_row_result = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == hash_secret(pair.refresh_token)))
    new_row = new_row_result.scalar_one()

    row.revoked_at = utcnow()
    row.replaced_by = new_row.id
    await db.commit()

    return pair


async def revoke_all_refresh_tokens(db: AsyncSession, device_id: str) -> None:
    """Called when a device is revoked (see admin_devices.py) so a stolen
    refresh token can't keep minting access tokens after the device
    itself was kicked off the account."""
    result = await db.execute(select(RefreshToken).where(RefreshToken.device_id == device_id, RefreshToken.revoked_at.is_(None)))
    for row in result.scalars().all():
        row.revoked_at = utcnow()
    await db.commit()
