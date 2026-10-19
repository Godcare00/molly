"""
Authenticates the *admin* side of the gateway's REST API (creating
enrollment tokens, listing/revoking workers, approving device pairings) -
as distinct from authenticating a mobile *device*'s ordinary API traffic,
which goes through tokens.verify_access_token instead.

Two ways in, both resolving to the same `Tenant`:

  - `X-API-Key`: a single hashed API key per tenant, minted once at
    signup (see api/account.py) and otherwise meant for
    scripts/CI/`curl` - long-lived and not tied to any one person.
  - `Authorization: Bearer <user session token>`: a real logged-in user
    (email/password, api/account.py's /auth/login), for the app/browser
    to hit these same admin endpoints without ever handling the raw API
    key. This is `tokens.UserClaims`, a distinct JWT `type` from the
    device access tokens `tokens.AccessClaims` covers - a stolen device
    token can't be replayed here, and vice versa.

Either way, every module downstream of this only ever asks "which tenant
is this for", never "which scheme proved it" - swapping in a fuller
account system (OAuth/OIDC, SSO, multiple admins with an audit trail)
only means changing this file.
"""
from __future__ import annotations

import hashlib
from typing import Annotated, Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import TokenError, verify_user_token
from app.db import get_db
from app.models import Tenant


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


async def get_tenant_admin(
    x_api_key: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
    db: AsyncSession = Depends(get_db),
) -> Tenant:
    if x_api_key:
        result = await db.execute(select(Tenant).where(Tenant.api_key_hash == hash_api_key(x_api_key)))
        tenant = result.scalar_one_or_none()
        if not tenant:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
        return tenant

    if authorization and authorization.lower().startswith("bearer "):
        try:
            claims = verify_user_token(authorization.split(" ", 1)[1])
        except TokenError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")
        tenant = await db.get(Tenant, claims.tenant_id)
        if not tenant:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
        return tenant

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="X-API-Key header or Authorization: Bearer session token required",
    )
