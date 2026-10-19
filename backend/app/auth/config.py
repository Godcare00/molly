"""
Authentication configuration.
"""
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
import os


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # JWT Settings
    jwt_algorithm: str = "RS256"
    jwt_private_key_path: str = "data/keys/jwt_private.pem"
    jwt_public_key_path: str = "data/keys/jwt_public.pem"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 30
    jwt_issuer: str = "molly"
    jwt_audience: str = "molly-mobile"

    # Device Key Settings
    device_key_challenge_expire_minutes: int = 10
    device_key_max_per_user: int = 10

    # Connect (CLI + browser pairing approval)
    pairing_code_expire_minutes: int = 10
    connect_session_expire_minutes: int = 10
    connect_max_attempts: int = 5
    connect_local_secret_path: str = "data/keys/connect_local.key"
    # Where the /connect link should point. Override in .env once you know
    # how the browser will actually reach this server (Tailscale hostname,
    # public domain, etc.) — defaults to a loopback URL that only works for
    # a browser on the same machine.
    public_base_url: str = "http://127.0.0.1:8000"

    # Rate Limiting
    rate_limit_requests_per_minute: int = 60
    rate_limit_burst: int = 10

    # OAuth2/OIDC (for future)
    oauth_github_client_id: Optional[str] = None
    oauth_github_client_secret: Optional[str] = None
    oauth_google_client_id: Optional[str] = None
    oauth_google_client_secret: Optional[str] = None

    # WebAuthn/Passkeys (for future)
    webauthn_rp_id: str = "localhost"
    webauthn_rp_name: str = "Molly"
    webauthn_origin: str = "https://localhost"

    # Database
    auth_database_path: str = "data/auth.db"

    @property
    def jwt_private_key(self) -> str:
        path = os.path.expanduser(self.jwt_private_key_path)
        if os.path.exists(path):
            with open(path, "r") as f:
                return f.read()
        return ""

    @property
    def jwt_public_key(self) -> str:
        path = os.path.expanduser(self.jwt_public_key_path)
        if os.path.exists(path):
            with open(path, "r") as f:
                return f.read()
        return ""


auth_settings = AuthSettings()