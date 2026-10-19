"""
Authenticates a paired *device's* own gateway-native calls - today just
GET /auth/me and POST /auth/logout (see api/account.py) - via the same
short-lived access token issued by /devices/pair or /auth/refresh and
verified the same way api/proxy.py and api/mobile_ws.py already do for
proxied traffic. Kept separate from auth/tenant_auth.py's
get_tenant_admin: that one resolves "which tenant is asking" for
admin-ish endpoints (API key or a logged-in user's session); this one
resolves "which device, on whose behalf" for endpoints the device itself
calls about its own session.
"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import Header, HTTPException, status

from app.auth.tokens import AccessClaims, TokenError, verify_access_token


async def get_current_device(
    authorization: Annotated[Optional[str], Header()] = None,
) -> AccessClaims:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer access token required")
    try:
        return verify_access_token(authorization.split(" ", 1)[1])
    except TokenError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
