import asyncio
from typing import Dict, List, Optional
import structlog

from app.llm.base import LLMProvider
from app.llm.openai_compatible import OpenAICompatibleProvider
from app.llm.anthropic_provider import AnthropicProvider
from app.llm.fallback import FallbackLLMProvider
from app.llm.retry import RetryPolicy
from app.config import settings

logger = structlog.get_logger()

# Names/aliases that map to each wire protocol we know how to speak.
ANTHROPIC_ALIASES = {"anthropic", "claude"}
OPENAI_COMPATIBLE_ALIASES = {
    "openai", "openai-compatible", "ollama", "vllm", "lmstudio", "lm-studio",
    "groq", "together", "openrouter", "azure", "azure-openai", "fireworks",
    "deepseek", "mistral", "perplexity", "localai",
}

SUPPORTED_PROVIDERS = sorted(ANTHROPIC_ALIASES | OPENAI_COMPATIBLE_ALIASES)

_provider: Optional[LLMProvider] = None
_bug_bounty_provider: Optional[LLMProvider] = None
# How long to let an old provider's in-flight requests finish before closing
# its underlying HTTP connection when it's swapped out at runtime.
_DRAIN_SECONDS = 60


def detect_provider_kind(provider: str, base_url: str = "", model: str = "") -> str:
    """Best-effort detection of which wire protocol to speak: 'anthropic' or
    'openai_compatible'. Order of precedence, most to least certain:

    1. An unambiguous base_url domain (api.anthropic.com / api.openai.com) -
       this is a fact about which server will actually receive the request,
       so it overrides a mistyped or stale provider name.
    2. A recognized provider name/alias.
    3. A model name that's obviously a Claude model.
    4. Default to the OpenAI-compatible format, since that's what the vast
       majority of self-hosted/local servers (Ollama, vLLM, LM Studio, etc.)
       and third-party gateways speak.
    """
    url = (base_url or "").lower()
    if "anthropic.com" in url:
        return "anthropic"
    if "api.openai.com" in url:
        return "openai_compatible"

    p = (provider or "").strip().lower()
    if p in ANTHROPIC_ALIASES:
        return "anthropic"
    if p in OPENAI_COMPATIBLE_ALIASES:
        return "openai_compatible"

    m = (model or "").strip().lower()
    if m.startswith("claude"):
        return "anthropic"

    return "openai_compatible"


def canonical_provider_name(provider: str, base_url: str = "", model: str = "") -> str:
    """A clean provider label to display/persist, given the same inputs used
    for detection.

    Preserves whatever descriptive name the user typed (e.g. a gateway like
    "nvidia" or "groq" that isn't in our alias list but still speaks the
    OpenAI-compatible format) rather than flattening it to a generic label -
    unless that name would be actively misleading (e.g. it says "anthropic"
    but a stronger signal like the base_url determined it's actually
    OpenAI-compatible, or vice versa).
    """
    kind = detect_provider_kind(provider, base_url, model)
    p = (provider or "").strip().lower()

    if kind == "anthropic":
        return "anthropic"

    # kind == "openai_compatible"
    if p in ANTHROPIC_ALIASES:
        return "openai-compatible"
    return p or "openai-compatible"


def get_configured_models() -> List[Dict[str, str]]:
    """The model picker's data source (see GET /settings/available-models):
    one entry per configured chain provider (primary + fallbacks), in
    chain order. Doesn't include the bug-bounty override - that's a
    per-mode default, not something to pick per-message."""
    return [
        {
            "name": cfg.get("name") or cfg["model"],
            "provider": cfg["provider"],
            "model": cfg["model"],
        }
        for cfg in settings.provider_chain_configs
    ]


def find_chain_entry_for_model(model: str, provider: Optional[str] = None) -> Optional[Dict]:
    """Look up a configured chain entry by model (+ optionally provider, to
    disambiguate if two entries share a model name on different
    providers). Always resolves against the *current* live chain rather
    than anything cached, so editing the chain later doesn't leave a
    conversation pointing at a stale/removed entry silently."""
    for cfg in settings.provider_chain_configs:
        if cfg["model"] == model and (provider is None or cfg["provider"] == provider):
            return cfg
    return None


def build_provider_from_chain_entry(cfg: Dict) -> LLMProvider:
    """Build a standalone provider from one chain entry - used when a
    conversation has explicitly picked a specific model (see
    app/api/routes.py's ConversationSettingsUpdate.model), so that turn
    uses exactly that model/provider rather than the automatic
    primary-then-fallbacks chain."""
    return build_provider(
        provider=cfg["provider"],
        base_url=cfg["base_url"],
        api_key=cfg["api_key"],
        model=cfg["model"],
        temperature=cfg.get("temperature", settings.llm_temperature),
        max_tokens=cfg.get("max_tokens", settings.llm_max_tokens),
    )


def get_provider_for_model_selection(model: str, provider: Optional[str] = None) -> Optional[LLMProvider]:
    """Resolve a conversation's explicit model selection to a provider, or
    None if it no longer matches any configured chain entry (e.g. the
    chain was edited after the conversation picked it) - callers should
    fall back to get_provider_for_mode() in that case rather than error
    the whole run over a stale selection. Wrapped in a single-entry
    FallbackLLMProvider so it still gets the normal retry-on-transient-
    error behavior, just without the cross-model fallback that picking a
    specific model is meant to opt out of."""
    cfg = find_chain_entry_for_model(model, provider)
    if cfg is None:
        return None
    single_provider = build_provider_from_chain_entry(cfg)
    return FallbackLLMProvider([(cfg.get("name") or cfg["model"], single_provider)])


def build_bug_bounty_provider(cfg: Dict) -> LLMProvider:
    """Build a provider for the bug-bounty model override (stored via
    app/storage/app_settings.py, not .env - see app/api/settings.py's
    /settings/bug-bounty-model). Any of provider/base_url/api_key/
    temperature/max_tokens left unset in `cfg` falls back to whatever the
    *primary* provider is currently configured with, so the common case
    (just wanting a different model on the same account/gateway) only
    requires specifying `model`.
    """
    provider_field = cfg.get("provider") or settings.llm_provider
    base_url = cfg.get("base_url") or settings.llm_base_url
    api_key = cfg.get("api_key") or settings.llm_api_key
    model = cfg["model"]
    temperature = cfg.get("temperature", settings.llm_temperature)
    max_tokens = cfg.get("max_tokens", settings.llm_max_tokens)
    return build_provider(
        provider=provider_field,
        base_url=base_url,
        api_key=api_key,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def get_bug_bounty_provider() -> Optional[LLMProvider]:
    """Lazily build (and cache) the bug-bounty override provider from
    whatever's currently stored in app_settings, or None if nothing's
    configured - callers should fall back to get_llm_provider() then."""
    global _bug_bounty_provider

    if _bug_bounty_provider is None:
        from app.storage.app_settings import get_json  # local import: avoid a storage->llm->storage cycle at module load

        cfg = get_json("bug_bounty_model")
        if not cfg or not cfg.get("model"):
            return None
        _bug_bounty_provider = build_bug_bounty_provider(cfg)

    return _bug_bounty_provider


def refresh_bug_bounty_provider() -> None:
    """Drop the cached bug-bounty provider so the next get_bug_bounty_provider()
    call rebuilds it from the latest app_settings value. Call this after
    PUT/DELETE on /settings/bug-bounty-model - same drain-then-close
    handling as swap_provider(), since a run already using the old one
    shouldn't have its connection yanked mid-request."""
    global _bug_bounty_provider
    old_provider = _bug_bounty_provider
    _bug_bounty_provider = None
    if old_provider is not None:
        asyncio.create_task(_drain_and_close(old_provider))


def get_provider_for_mode(mode: str) -> LLMProvider:
    """What AgentExecutor actually calls: the bug-bounty override provider
    when `mode == "bug_bounty"` and one is configured, otherwise the normal
    primary/fallback chain from get_llm_provider(). Falls back the same way
    for any other/unknown mode."""
    if mode == "bug_bounty":
        override = get_bug_bounty_provider()
        if override is not None:
            return override
    return get_llm_provider()


def get_llm_provider() -> LLMProvider:
    """Get or create the LLM provider instance."""
    global _provider

    if _provider is None:
        _provider = create_provider()

    return _provider


def build_provider(
    provider: str,
    base_url: str,
    api_key: str,
    model: str,
    temperature: float = 0.1,
    max_tokens: int = 4096,
) -> LLMProvider:
    """Build a provider instance, auto-detecting the wire protocol from the
    provider name, base_url, and model (used for hot-swap and testing)."""
    kind = detect_provider_kind(provider, base_url, model)

    if kind == "anthropic":
        resolved_base_url = base_url
        # If someone switches to Claude but leaves the OpenAI default (or
        # nothing) in place, fill in Anthropic's default rather than fail.
        if not resolved_base_url or "api.openai.com" in resolved_base_url.lower():
            resolved_base_url = AnthropicProvider.DEFAULT_BASE_URL
        return AnthropicProvider(
            base_url=resolved_base_url,
            api_key=api_key,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    return OpenAICompatibleProvider(
        base_url=base_url,
        api_key=api_key,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def build_provider_chain(
    configs: List[Dict],
    policy: Optional[RetryPolicy] = None,
) -> FallbackLLMProvider:
    """Build a retry/fallback chain from an ordered list of provider config
    dicts (each with provider/base_url/api_key/model/temperature/max_tokens,
    and an optional display `name`). The first entry is tried first; on
    failure (after its retry budget is exhausted) the next one is tried, and
    so on.
    """
    if not configs:
        raise ValueError("At least one provider must be configured")

    chain = []
    for cfg in configs:
        provider_field = cfg.get("provider", "")
        base_url = cfg.get("base_url", "")
        model = cfg.get("model", "")
        name = cfg.get("name") or canonical_provider_name(provider_field, base_url, model)
        provider = build_provider(
            provider=provider_field,
            base_url=base_url,
            api_key=cfg.get("api_key", ""),
            model=model,
            temperature=cfg.get("temperature", 0.1),
            max_tokens=cfg.get("max_tokens", 4096),
        )
        chain.append((name, provider))

    return FallbackLLMProvider(chain, policy)


def create_provider() -> LLMProvider:
    """Create a new provider instance - a retry/fallback chain built from
    current settings (the primary provider plus any configured fallbacks)."""
    policy = RetryPolicy(
        max_retries=settings.llm_max_retries,
        base_delay=settings.llm_retry_base_delay_seconds,
        max_delay=settings.llm_retry_max_delay_seconds,
    )
    return build_provider_chain(settings.provider_chain_configs, policy)


def set_provider(provider: LLMProvider) -> None:
    """Set a custom provider (for testing)."""
    global _provider
    _provider = provider


def swap_provider(new_provider: LLMProvider) -> None:
    """Atomically swap in a new provider, e.g. after a settings change.

    Requests already in flight keep the old provider instance (each agent run
    grabs a reference via get_llm_provider() when it starts), so this takes
    effect for the *next* request with no restart needed. The old provider's
    HTTP connection is closed in the background after a drain period so
    in-flight requests aren't cut off.
    """
    global _provider
    old_provider = _provider
    _provider = new_provider

    if old_provider is not None and old_provider is not new_provider:
        asyncio.create_task(_drain_and_close(old_provider))


async def _drain_and_close(provider: LLMProvider) -> None:
    try:
        await asyncio.sleep(_DRAIN_SECONDS)
        if hasattr(provider, "close"):
            await provider.close()
    except Exception:
        logger.warning("llm_provider_drain_close_failed", exc_info=True)


async def close_provider() -> None:
    """Close the provider connection."""
    global _provider
    if _provider and hasattr(_provider, "close"):
        await _provider.close()
    _provider = None
