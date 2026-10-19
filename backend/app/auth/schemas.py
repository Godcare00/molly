"""
Authentication Pydantic schemas (request/response models).
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, EmailStr
from enum import Enum


class UserRole(str, Enum):
    OPERATOR = "operator"
    VIEWER = "viewer"
    ADMIN = "admin"


class Platform(str, Enum):
    IOS = "ios"
    ANDROID = "android"
    DESKTOP = "desktop"
    WEB = "web"


# --- Device Key Registration ---

class DeviceRegisterRequest(BaseModel):
    public_key: str = Field(..., description="Ed25519 public key in PEM format")
    device_name: str = Field(..., min_length=1, max_length=200, description="Human-readable device name")
    platform: Platform = Field(..., description="Device platform")
    platform_version: Optional[str] = Field(None, max_length=50)
    app_version: Optional[str] = Field(None, max_length=50)


class DeviceRegisterResponse(BaseModel):
    device_id: str
    challenge: str = Field(..., description="Challenge to sign with device private key")
    challenge_expires_at: datetime
    pairing_code: str = Field(..., description="Human-readable code to enter at the /connect page to approve this device")
    pairing_code_expires_at: datetime


class DeviceVerifyRequest(BaseModel):
    device_id: str
    signature: str = Field(..., description="Base64url-encoded signature of challenge")


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int = Field(..., description="Access token lifetime in seconds")
    refresh_expires_in: int = Field(..., description="Refresh token lifetime in seconds")


# --- Device Management ---

class DeviceResponse(BaseModel):
    id: str
    name: str
    platform: Platform
    platform_version: Optional[str] = None
    app_version: Optional[str] = None
    key_id: str
    is_trusted: bool
    is_revoked: bool
    last_used_at: Optional[datetime] = None
    last_ip: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class DeviceListResponse(BaseModel):
    devices: List[DeviceResponse]


class DeviceRevokeRequest(BaseModel):
    reason: Optional[str] = Field(None, max_length=500)


class DeviceTrustRequest(BaseModel):
    is_trusted: bool


# --- Connect (CLI + browser device approval) ---

class ConnectStartResponse(BaseModel):
    session_token: str
    connect_url: str
    expires_at: datetime


class ConnectApproveRequest(BaseModel):
    session_token: str
    code: str = Field(..., min_length=1, max_length=32)


class ConnectApproveResponse(BaseModel):
    device_name: str
    platform: Platform


class ConnectStatusResponse(BaseModel):
    status: str  # pending, approved, expired
    device_name: Optional[str] = None
    platform: Optional[Platform] = None


# --- Token Refresh ---

class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(TokenPair):
    pass


# --- User Info ---

class UserResponse(BaseModel):
    id: str
    email: Optional[EmailStr] = None
    username: Optional[str] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    role: UserRole
    is_active: bool
    created_at: datetime
    last_login_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# --- OAuth2 (future) ---

class OAuthProvider(str, Enum):
    GITHUB = "github"
    GOOGLE = "google"
    MICROSOFT = "microsoft"


class OAuthAuthorizeRequest(BaseModel):
    provider: OAuthProvider
    redirect_uri: str = Field(..., description="Mobile app redirect URI (e.g., molly://oauth-callback)")
    state: Optional[str] = None


class OAuthAuthorizeResponse(BaseModel):
    authorization_url: str
    state: str


class OAuthCallbackRequest(BaseModel):
    provider: OAuthProvider
    code: str
    redirect_uri: str
    state: Optional[str] = None


class OAuthTokenResponse(TokenPair):
    id_token: Optional[str] = None


# --- JWKS ---

class JWKSResponse(BaseModel):
    keys: List[dict]


# --- Error Responses ---

class AuthErrorResponse(BaseModel):
    error: str
    error_description: Optional[str] = None
    error_code: Optional[str] = None


# --- WebSocket Auth ---

class WSAuthMessage(BaseModel):
    type: str = "auth"
    token: str


class WSAuthResponse(BaseModel):
    type: str = "auth_result"
    success: bool
    error: Optional[str] = None
    user: Optional[UserResponse] = None