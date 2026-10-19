import json
from pathlib import Path
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE_PATH = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM Provider (primary - first in the fallback chain)
    llm_provider_name: str = ""  # optional display label, e.g. "OpenAI (main)"
    llm_provider: str = "openai"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o"
    llm_temperature: float = 0.1
    llm_max_tokens: int = 4096

    # Additional providers tried, in order, if the primary (and each one
    # after it) fails after exhausting its retries. JSON-encoded list of
    # {name, provider, base_url, api_key, model, temperature, max_tokens}.
    llm_fallback_providers: str = "[]"

    # Retry behavior applied to each provider in the chain before the chain
    # moves on to the next one.
    llm_max_retries: int = 2
    llm_retry_base_delay_seconds: float = 1.0
    llm_retry_max_delay_seconds: float = 20.0

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # Database
    database_path: str = "data/app.db"

    # File Storage
    uploads_dir: str = "data/uploads"
    projects_dir: str = "data/projects"
    skills_dir: str = "data/skills"
    max_image_size_mb: int = 10
    max_upload_size_mb: int = 50

    # Image Cleanup
    image_cleanup_days: int = 7
    max_images_per_conversation: int = 50

    # File Cleanup (non-image attachments)
    file_cleanup_days: int = 30
    max_files_per_conversation: int = 50

    # Agent Limits
    max_iterations: int = 50
    max_tool_calls: int = 100
    max_execution_time_seconds: int = 300
    max_command_timeout_seconds: int = 120
    max_context_tokens: int = 32000
    max_tool_output_chars: int = 10000

    # Approval
    approval_timeout_minutes: int = 30

    # Gemini Live (hands-free voice mode)
    gemini_api_key: str = ""
    gemini_live_model: str = "gemini-3.1-flash-live-preview"
    # Comma-separated words that count as a spoken approval / rejection for a
    # tool call that would otherwise need an in-app tap. Kept short and
    # distinctive on purpose - see app/agent/live_voice.py for why loose
    # matching (e.g. bare "yes") is deliberately avoided.
    live_voice_confirm_words: str = "confirm,confirmed"
    live_voice_cancel_words: str = "cancel,cancelled,stop"
    # Live API sessions are capped by Google at ~10 minutes of connection
    # lifetime (~15 min audio-only before that). We proactively close and
    # surface that to the client rather than let it die mid-sentence; see
    # KNOWN_LIMITATIONS.md.
    live_session_max_minutes: int = 9

    # Fleet gateway (optional). Leave gateway_ws_url blank to run exactly as
    # today - a self-hosted, single-tenant worker with no gateway involved.
    # Set it (after running `python -m app.cli worker enroll`, which writes
    # data/gateway_credential.json) to also dial out to a shared gateway;
    # see app/tunnel/. The two modes aren't exclusive - a worker can serve
    # local/Tailscale clients on :8000 AND be reachable through a gateway
    # at the same time.
    gateway_ws_url: str = ""  # e.g. wss://gateway.example.com/worker/connect

    # Base HTTP URL of the fleet's gateway, used only by `molly worker
    # enroll` to know where to POST the enrollment token (see
    # app/tunnel/enrollment.py). Baked in here so enrollment on a new server
    # is just `molly worker enroll --token <token>` - no need to also
    # know/paste the gateway's address every time. If you ever stand up a
    # second gateway, override per-worker with --gateway or GATEWAY_HTTP_URL
    # in that worker's .env; this default doesn't need to change.
    gateway_http_url: str = "https://gateway.example.com"  # TODO: set to your real gateway's URL

    # Security
    secret_key: str = "change-this-in-production"
    allowed_hosts: str = "*"

    # Logging
    log_level: str = "INFO"

    @property
    def uploads_path(self) -> Path:
        return Path(self.uploads_dir).resolve()

    @property
    def projects_path(self) -> Path:
        return Path(self.projects_dir).resolve()

    @property
    def skills_path(self) -> Path:
        return Path(self.skills_dir).resolve()

    @property
    def database_path_resolved(self) -> Path:
        return Path(self.database_path).resolve()

    @property
    def allowed_hosts_list(self) -> list[str]:
        return [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]

    @property
    def live_voice_confirm_words_list(self) -> list[str]:
        return [w.strip().lower() for w in self.live_voice_confirm_words.split(",") if w.strip()]

    @property
    def live_voice_cancel_words_list(self) -> list[str]:
        return [w.strip().lower() for w in self.live_voice_cancel_words.split(",") if w.strip()]

    @property
    def fallback_provider_configs(self) -> list[dict]:
        """Parsed fallback provider list, tolerant of missing/malformed JSON
        (e.g. a hand-edited .env) so a bad value degrades to "no fallbacks"
        rather than crashing startup."""
        try:
            parsed = json.loads(self.llm_fallback_providers or "[]")
        except (json.JSONDecodeError, TypeError):
            return []
        return parsed if isinstance(parsed, list) else []

    @property
    def provider_chain_configs(self) -> list[dict]:
        """The full ordered provider chain: the primary provider first,
        followed by any configured fallbacks."""
        primary = {
            "name": self.llm_provider_name or "primary",
            "provider": self.llm_provider,
            "base_url": self.llm_base_url,
            "api_key": self.llm_api_key,
            "model": self.llm_model,
            "temperature": self.llm_temperature,
            "max_tokens": self.llm_max_tokens,
        }
        return [primary, *self.fallback_provider_configs]


settings = Settings()


def persist_env_vars(updates: dict[str, str]) -> None:
    """Write key/value pairs into the .env file so they survive a restart.

    This only persists to disk; callers are responsible for also updating
    the in-memory `settings` object so the change takes effect immediately.
    """
    from dotenv import set_key

    ENV_FILE_PATH.touch(exist_ok=True)
    for key, value in updates.items():
        set_key(str(ENV_FILE_PATH), key, value, quote_mode="never")