"""
Authentication API router.
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request, WebSocket, Query
from fastapi.responses import JSONResponse, HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel

from app.auth.database import get_auth_db
from app.auth.models import User, Device, Session, RefreshTokenRevocationList
from app.auth.schemas import (
    DeviceRegisterRequest, DeviceRegisterResponse,
    DeviceVerifyRequest, TokenPair,
    DeviceResponse, DeviceListResponse,
    DeviceRevokeRequest, DeviceTrustRequest,
    ConnectStartResponse, ConnectApproveRequest, ConnectApproveResponse, ConnectStatusResponse,
    RefreshRequest, RefreshResponse,
    UserResponse,
    JWKSResponse,
    WSAuthMessage, WSAuthResponse,
)
from app.auth.jwt import jwt_manager, hash_refresh_token, verify_refresh_token_hash
from app.auth.device_keys import DeviceKeyManager, PendingApprovalError
from app.auth.connect import ConnectManager, LocalSecretError, verify_local_secret
from app.auth.dependencies import get_current_user, get_auth_db, AuthUser
from app.auth.config import auth_settings

router = APIRouter(prefix="/auth", tags=["authentication"])


# --- JWKS Endpoint ---

@router.get("/.well-known/jwks.json", response_model=JWKSResponse)
async def jwks():
    """JSON Web Key Set for token verification."""
    return jwt_manager.get_jwks()


# --- Device Key Registration ---

@router.post("/device/register", response_model=DeviceRegisterResponse, status_code=status.HTTP_201_CREATED)
async def register_device(
    request: DeviceRegisterRequest,
    db: AsyncSession = Depends(get_auth_db),
):
    """
    Register a new device with its Ed25519 public key.
    Returns a challenge that must be signed with the device's private key.
    """
    # For now, create a temporary user or use a default
    # In production, this would be tied to an existing user via OAuth or invite
    user_result = await db.execute(select(User).where(User.id == "default"))
    user = user_result.scalar_one_or_none()

    if not user:
        # Create default user for single-user mode
        user = User(
            id="default",
            username="operator",
            display_name="VPS Operator",
            role="operator",
            is_active=True,
        )
        db.add(user)
        await db.flush()

    try:
        device, challenge, pairing_code, pairing_code_expires_at = await DeviceKeyManager.register_device(
            db,
            user_id=user.id,
            public_key_pem=request.public_key,
            device_name=request.device_name,
            platform=request.platform.value,
            platform_version=request.platform_version,
            app_version=request.app_version,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return DeviceRegisterResponse(
        device_id=device.id,
        challenge=challenge,
        challenge_expires_at=device.challenge_expires_at,
        pairing_code=pairing_code,
        pairing_code_expires_at=pairing_code_expires_at,
    )


@router.post("/device/verify", response_model=TokenPair)
async def verify_device(
    request: DeviceVerifyRequest,
    db: AsyncSession = Depends(get_auth_db),
):
    """
    Verify device challenge signature and issue tokens. The signature proves
    possession of the device's private key, but that alone isn't enough —
    the device also needs to have been approved via /connect first. The app
    is expected to call this repeatedly (polling) while it waits for that
    approval; a still-pending device returns 403 with a distinguishable
    error code so the app knows to keep waiting rather than give up.
    """
    try:
        device = await DeviceKeyManager.verify_device_challenge(db, request.device_id, request.signature)
    except PendingApprovalError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "pending_approval", "message": "Waiting for approval — enter the code shown in the app at the connect link."},
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # Issue tokens
    access_token, access_jti, access_expires = jwt_manager.create_access_token(
        subject=device.user_id,
        device_id=device.id,
        role="operator",
    )
    refresh_token, refresh_hash, refresh_expires = jwt_manager.create_refresh_token(
        subject=device.user_id,
        device_id=device.id,
    )

    # Create session
    session = Session(
        id=access_jti,
        user_id=device.user_id,
        device_id=device.id,
        refresh_token_hash=refresh_hash,
        access_token_jti=access_jti,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=refresh_expires),
    )
    db.add(session)

    # Update device last used
    device.last_used_at = datetime.now(timezone.utc)

    return TokenPair(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=access_expires,
        refresh_expires_in=refresh_expires,
    )


# --- Device Management ---

@router.get("/devices", response_model=DeviceListResponse)
async def list_devices(
    current_user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_auth_db),
):
    """List all devices for the current user."""
    result = await db.execute(
        select(Device).where(Device.user_id == current_user.user_id).order_by(Device.created_at.desc())
    )
    devices = result.scalars().all()

    return DeviceListResponse(devices=[DeviceResponse.model_validate(d) for d in devices])


@router.get("/devices/{device_id}", response_model=DeviceResponse)
async def get_device(
    device_id: str,
    current_user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_auth_db),
):
    """Get device details."""
    device = await db.get(Device, device_id)
    if not device or device.user_id != current_user.user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return DeviceResponse.model_validate(device)


@router.post("/devices/{device_id}/revoke", response_model=DeviceResponse)
async def revoke_device(
    device_id: str,
    request: DeviceRevokeRequest,
    current_user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_auth_db),
):
    """Revoke a device (logout and invalidate all tokens)."""
    if device_id == current_user.device_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot revoke current device")

    try:
        device = await DeviceKeyManager.revoke_device(db, device_id, request.reason)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    # Revoke all sessions for this device
    result = await db.execute(
        select(Session).where(Session.device_id == device_id, Session.revoked_at.is_(None))
    )
    for session in result.scalars().all():
        session.revoked_at = datetime.now(timezone.utc)
        session.revoked_reason = "Device revoked"

    return DeviceResponse.model_validate(device)


@router.post("/devices/{device_id}/trust", response_model=DeviceResponse)
async def set_device_trust(
    device_id: str,
    request: DeviceTrustRequest,
    current_user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_auth_db),
):
    """Set device trust status."""
    try:
        device = await DeviceKeyManager.set_device_trust(db, device_id, request.is_trusted)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return DeviceResponse.model_validate(device)


# --- Connect: CLI-issued pairing sessions approved from a browser ---

@router.post("/connect/start", response_model=ConnectStartResponse)
async def connect_start(
    request: Request,
    db: AsyncSession = Depends(get_auth_db),
):
    """
    Called by `molly connect` (running on the VPS) to start a pairing
    session. Requires the local secret only a process on this machine can
    read — that's what makes the resulting URL trustworthy to hand to a
    browser and treat as "this really came from the box owner".
    """
    try:
        verify_local_secret(request)
    except LocalSecretError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This endpoint can only be called from the Molly CLI on this server.")

    session = await ConnectManager.create_session(db)
    connect_url = f"{auth_settings.public_base_url.rstrip('/')}/auth/connect?session={session.token}"

    return ConnectStartResponse(
        session_token=session.token,
        connect_url=connect_url,
        expires_at=session.expires_at,
    )


@router.get("/connect/status", response_model=ConnectStatusResponse)
async def connect_status(
    session_token: str = Query(...),
    db: AsyncSession = Depends(get_auth_db),
):
    """Polled by `molly connect` while it waits for browser approval."""
    session = await ConnectManager.get_session(db, session_token)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown connect session")

    if session.status == "approved" and session.approved_device_id:
        device = await db.get(Device, session.approved_device_id)
        if device:
            return ConnectStatusResponse(status="approved", device_name=device.name, platform=device.platform)

    return ConnectStatusResponse(status=session.status)


@router.post("/connect/approve", response_model=ConnectApproveResponse)
async def connect_approve(
    request: ConnectApproveRequest,
    db: AsyncSession = Depends(get_auth_db),
):
    """
    Called from the /connect browser page once the operator types in the
    code shown in the app. This is the step that actually grants trust.
    """
    try:
        session, device = await ConnectManager.approve(db, request.session_token, request.code)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return ConnectApproveResponse(device_name=device.name, platform=device.platform)


@router.get("/connect", response_class=HTMLResponse, include_in_schema=False)
async def connect_page(session: str = Query(...)):
    """Minimal browser page for approving a device pairing code."""
    return HTMLResponse(_CONNECT_PAGE_HTML.replace("__SESSION_TOKEN__", session))


_CONNECT_PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Connect a device — Molly</title>
<style>
  :root { color-scheme: dark; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0b0c10; color: #f2f2f5; display: flex; min-height: 100vh; align-items: center; justify-content: center; margin: 0; padding: 24px; }
  .card { max-width: 380px; width: 100%; background: #16171d; border: 1px solid #2a2b33; border-radius: 16px; padding: 32px 28px; }
  h1 { font-size: 20px; margin: 0 0 8px; }
  p { color: #9a9ba5; font-size: 14px; line-height: 1.5; margin: 0 0 24px; }
  input { width: 100%; box-sizing: border-box; font-size: 22px; letter-spacing: 4px; text-align: center; text-transform: uppercase; padding: 14px; border-radius: 10px; border: 1px solid #33343d; background: #0e0f13; color: #f2f2f5; margin-bottom: 16px; }
  button { width: 100%; padding: 14px; border-radius: 10px; border: none; background: #5b8cff; color: #fff; font-size: 15px; font-weight: 600; cursor: pointer; }
  button:disabled { opacity: 0.5; cursor: default; }
  .msg { margin-top: 16px; font-size: 14px; text-align: center; }
  .msg.error { color: #ff6b6b; }
  .msg.success { color: #4ade80; }
</style>
</head>
<body>
  <div class="card">
    <h1>Connect a device</h1>
    <p>Enter the code shown in the Molly app to approve it for this server.</p>
    <input id="code" maxlength="8" placeholder="XXX-XXXX" autofocus autocomplete="off" autocapitalize="characters">
    <button id="submit">Approve device</button>
    <div id="msg" class="msg"></div>
  </div>
  <script>
    const sessionToken = "__SESSION_TOKEN__";
    const codeInput = document.getElementById('code');
    const submitBtn = document.getElementById('submit');
    const msg = document.getElementById('msg');

    async function submit() {
      const code = codeInput.value.trim();
      if (!code) return;
      submitBtn.disabled = true;
      msg.textContent = '';
      msg.className = 'msg';
      try {
        const res = await fetch('/auth/connect/approve', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_token: sessionToken, code }),
        });
        const data = await res.json();
        if (!res.ok) {
          throw new Error((data && data.detail) || 'Something went wrong.');
        }
        msg.textContent = `Connected: ${data.device_name}. You can close this page and return to the app.`;
        msg.className = 'msg success';
        codeInput.disabled = true;
        submitBtn.style.display = 'none';
      } catch (err) {
        msg.textContent = err.message || 'Something went wrong.';
        msg.className = 'msg error';
        submitBtn.disabled = false;
      }
    }

    submitBtn.addEventListener('click', submit);
    codeInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') submit(); });
  </script>
</body>
</html>
"""


# --- Token Refresh ---

@router.post("/refresh", response_model=RefreshResponse)
async def refresh_token(
    request: RefreshRequest,
    db: AsyncSession = Depends(get_auth_db),
):
    """Refresh access token using refresh token."""
    # Hash the provided refresh token
    token_hash = hash_refresh_token(request.refresh_token)

    # Check revocation list
    revoked = await db.get(RefreshTokenRevocationList, token_hash)
    if revoked:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revoked")

    # Verify token
    try:
        payload = jwt_manager.verify_token(request.refresh_token, expected_type="refresh")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))

    user_id = payload.get("sub")
    device_id = payload.get("device_id")

    # Verify session exists
    session = await db.get(Session, token_hash)
    if not session or session.revoked_at or session.user_id != user_id or session.device_id != device_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")

    # Verify device
    device = await db.get(Device, device_id)
    if not device or device.is_revoked or not device.is_trusted:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Device not authorized")

    # Issue new tokens
    access_token, access_jti, access_expires = jwt_manager.create_access_token(
        subject=user_id,
        device_id=device_id,
        role="operator",
    )
    new_refresh_token, new_refresh_hash, refresh_expires = jwt_manager.create_refresh_token(
        subject=user_id,
        device_id=device_id,
    )

    # Revoke old session
    session.revoked_at = datetime.now(timezone.utc)
    session.revoked_reason = "Token refreshed"

    # Create new session
    new_session = Session(
        id=access_jti,
        user_id=user_id,
        device_id=device_id,
        refresh_token_hash=new_refresh_hash,
        access_token_jti=access_jti,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=refresh_expires),
    )
    db.add(new_session)

    return RefreshResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        expires_in=access_expires,
        refresh_expires_in=refresh_expires,
    )


# --- Logout / Revocation ---

@router.post("/logout")
async def logout(
    current_user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_auth_db),
):
    """Logout current session."""
    # Revoke current session
    current_user.session.revoked_at = datetime.now(timezone.utc)
    current_user.session.revoked_reason = "User logout"

    # Add refresh token to revocation list
    revocation = RefreshTokenRevocationList(
        token_hash=current_user.session.refresh_token_hash,
        reason="User logout",
    )
    db.add(revocation)

    return {"message": "Logged out successfully"}


@router.post("/logout-all")
async def logout_all(
    current_user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_auth_db),
):
    """Logout all sessions for current user."""
    # Revoke all sessions
    result = await db.execute(
        select(Session).where(Session.user_id == current_user.user_id, Session.revoked_at.is_(None))
    )
    for session in result.scalars().all():
        session.revoked_at = datetime.now(timezone.utc)
        session.revoked_reason = "User logout all"
        db.add(RefreshTokenRevocationList(token_hash=session.refresh_token_hash, reason="User logout all"))

    return {"message": "All sessions revoked"}


# --- User Info ---

@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: AuthUser = Depends(get_current_user),
):
    """Get current user information."""
    return UserResponse.model_validate(current_user.user)


# --- WebSocket Auth Handshake ---

class WSAuthRequest(BaseModel):
    type: str = "auth"
    token: str


@router.websocket("/ws")
async def websocket_auth(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_auth_db),
):
    """
    WebSocket authentication endpoint.
    Connect with ?token=<access_token> or send auth message after connect.
    """
    await websocket.accept()

    # If token in query, authenticate immediately
    if token:
        try:
            auth_user = await authenticate_ws_token(token, db)
            await websocket.send_json(WSAuthResponse(success=True, user=UserResponse.model_validate(auth_user.user)).model_dump())
            # Keep connection alive for the main app to take over
            await websocket.close(code=1000, reason="Authenticated")
            return
        except HTTPException as e:
            await websocket.send_json(WSAuthResponse(success=False, error=e.detail).model_dump())
            await websocket.close(code=4001, reason=e.detail)
            return

    # Wait for auth message
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "auth":
                token = data.get("token")
                if not token:
                    await websocket.send_json(WSAuthResponse(success=False, error="Token required").model_dump())
                    continue

                try:
                    auth_user = await authenticate_ws_token(token, db)
                    await websocket.send_json(WSAuthResponse(success=True, user=UserResponse.model_validate(auth_user.user)).model_dump())
                    await websocket.close(code=1000, reason="Authenticated")
                    return
                except HTTPException as e:
                    await websocket.send_json(WSAuthResponse(success=False, error=e.detail).model_dump())
    except Exception:
        await websocket.close(code=1000)


async def authenticate_ws_token(token: str, db: AsyncSession) -> AuthUser:
    """Authenticate WebSocket token."""
    from app.auth.dependencies import authenticate_websocket
    from app.auth.jwt import jwt_manager
    from app.auth.models import User, Device, Session

    try:
        payload = jwt_manager.verify_token(token, expected_type="access")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))

    user_id = payload.get("sub")
    device_id = payload.get("device_id")
    jti = payload.get("jti")

    user = await db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    device = await db.get(Device, device_id)
    if not device or device.is_revoked or not device.is_trusted:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Device not authorized")

    session = await db.get(Session, jti) if jti else None
    if not session or session.revoked_at:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session revoked")

    from app.auth.dependencies import AuthUser
    return AuthUser(user, device, session, payload)


# --- Health Check ---

@router.get("/health")
async def auth_health():
    """Auth service health check."""
    return {"status": "healthy", "service": "auth"}