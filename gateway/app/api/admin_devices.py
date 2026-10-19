"""
Everything about a device *after* it's paired: refreshing its session,
the device itself checking who it is / logging out, and a tenant admin
revoking it. Pairing itself - the code-based flow requested from the server
and redeemed by the phone - lives in app/api/pairing.py, since it's
authenticated as the worker/nobody rather than as a tenant admin.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.device_auth import get_current_device
from app.auth.tenant_auth import get_tenant_admin
from app.auth.tokens import AccessClaims, TokenError, revoke_all_refresh_tokens, rotate_refresh_token
from app.db import get_db
from app.models import Device, Tenant, User

router = APIRouter()


class RefreshBody(BaseModel):
    refresh_token: str


@router.post("/auth/refresh")
async def refresh(body: RefreshBody, db: AsyncSession = Depends(get_db)):
    """Gateway-native - never proxied to a worker (see molly-app/src/api/client.ts's
    performRefresh(), which calls this directly against API_BASE_URL with no
    /w/{worker_id} prefix, since the gateway is what owns sessions now)."""
    try:
        pair = await rotate_refresh_token(db, body.refresh_token)
    except TokenError as e:
        raise HTTPException(status_code=401, detail=str(e))
    return pair.model_dump()


@router.get("/auth/me")
async def me(claims: AccessClaims = Depends(get_current_device), db: AsyncSession = Depends(get_db)):
    """Gateway-native, like /auth/refresh above - the mobile app calls this
    with no /w/{worker_id} prefix (see molly-app/src/api/client.ts's
    `gatewayNative` request option) since it's about the *session*, not
    anything a specific worker owns. Resolves the device's own access
    token into the identity the app displays: the tenant/account it
    belongs to, and - if this device was paired while logged into a real
    account (see api/pairing.py's optional Authorization header) - which
    user. A device paired anonymously via a bare code has no `email`."""
    device = await db.get(Device, claims.device_id)
    if not device or device.is_revoked:
        raise HTTPException(status_code=401, detail="Device no longer authorized")

    user = await db.get(User, device.user_id) if device.user_id else None

    return {
        "tenant_id": claims.tenant_id,
        "device_id": device.id,
        "device_name": device.name,
        "user_id": user.id if user else None,
        "email": user.email if user else None,
        "role": claims.role,
        "default_worker_id": device.default_worker_id,
    }


@router.post("/auth/logout")
async def logout(claims: AccessClaims = Depends(get_current_device), db: AsyncSession = Depends(get_db)):
    """Ends *this* device's session by revoking its outstanding refresh
    tokens, so a stolen/cached refresh token stops working the moment the
    user logs out - the short-lived access token still already in flight
    simply expires on its own shortly after. Doesn't touch `Device.is_revoked`;
    that's the stronger, admin-initiated action below (`revoke_device`),
    which also blocks the device from ever pairing/refreshing again."""
    await revoke_all_refresh_tokens(db, claims.device_id)
    return {"status": "logged_out"}


@router.post("/admin/devices/{device_id}/revoke")
async def revoke_device(device_id: str, tenant: Tenant = Depends(get_tenant_admin), db: AsyncSession = Depends(get_db)):
    device = await db.get(Device, device_id)
    if not device or device.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="Device not found")
    device.is_revoked = True
    await db.commit()
    await revoke_all_refresh_tokens(db, device_id)
    return {"status": "revoked"}
