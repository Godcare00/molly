from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore")

    host: str = "0.0.0.0"
    port: int = 8080
    debug: bool = False

    # Swap for a real Postgres URL in production, e.g.
    # postgresql+asyncpg://molly:password@db.internal/molly_gateway
    # SQLite is fine for local dev / demoing the split, not for concurrent
    # production traffic - see ARCHITECTURE.md's scaling table, which
    # already called this out before the gateway existed.
    database_url: str = "sqlite+aiosqlite:///./data/gateway.db"

    # Used to build the enrollment hint text shown to admins, and as the
    # default a worker should dial if its own /admin/workers/enroll
    # response doesn't include one explicitly.
    public_ws_url: str = "ws://localhost:8080/worker/connect"
    public_http_url: str = "http://localhost:8080"

    # Signs the gateway's own user/device JWTs (access tokens issued to
    # mobile devices). Separate from each worker's per-worker relay
    # secret - compromising this lets someone mint gateway sessions;
    # compromising one worker's secret only lets someone forge relay
    # tokens *for that one worker*, which is the point of scoping it
    # per-worker rather than sharing one secret fleet-wide.
    jwt_secret: str = "change-this-in-production"
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 30
    relay_token_ttl_seconds: int = 60

    # A logged-in user's account-level session (see api/account.py) -
    # longer-lived than a device access token since it's re-derived from
    # a password login, not silently refreshed. Independent of
    # refresh_token_ttl_days, which is about a *device's* session.
    user_session_ttl_minutes: int = 60 * 24 * 7

    pairing_code_ttl_minutes: int = 10
    enrollment_token_ttl_minutes: int = 15

    # Set to run more than one gateway process (e.g. behind a load
    # balancer). Empty means single-process, pure in-memory routing -
    # see app/tunnel/registry.py and app/tunnel/bus.py for what this
    # changes. redis:// or rediss:// URL, e.g. redis://localhost:6379/0
    redis_url: str = ""


settings = Settings()
