import json
from typing import List, Optional

import structlog
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from app.config import settings, persist_env_vars
from app.llm.client import (
    build_provider,
    build_provider_chain,
    build_bug_bounty_provider,
    get_configured_models,
    swap_provider,
    refresh_bug_bounty_provider,
    detect_provider_kind,
    canonical_provider_name,
)
from app.llm.retry import RetryPolicy
from app.storage import app_settings as kv_settings
from app.auth.dependencies import get_current_user

logger = structlog.get_logger()

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(get_current_user)])

MASKED_API_KEY = "***"

DETECTION_LABELS = {
    "anthropic": "Anthropic (native Messages API)",
    "openai_compatible": "OpenAI-compatible (chat completions API)",
}


class ProviderSettings(BaseModel):
    provider: str
    base_url: str
    api_key: str
    model: str
    temperature: float = Field(0.1, ge=0.0, le=2.0)
    max_tokens: int = Field(4096, gt=0)


class ProviderChainEntry(BaseModel):
    name: Optional[str] = None
    provider: str
    base_url: str
    api_key: str
    model: str
    temperature: float = Field(0.1, ge=0.0, le=2.0)
    max_tokens: int = Field(4096, gt=0)


class RetrySettings(BaseModel):
    max_retries: int = Field(2, ge=0, le=10)
    retry_base_delay_seconds: float = Field(1.0, ge=0.0, le=60.0)
    retry_max_delay_seconds: float = Field(20.0, ge=0.0, le=300.0)


class ProviderChainSettings(BaseModel):
    providers: List[ProviderChainEntry] = Field(..., min_length=1)
    retry: RetrySettings = Field(default_factory=RetrySettings)


class BugBountyModelSettings(BaseModel):
    """Model override for bug_bounty-mode conversations only - stored in the
    DB (app_settings table), never in .env. Everything but `model` is
    optional: leave provider/base_url/api_key/temperature/max_tokens unset
    to reuse whatever the primary provider (PUT /settings/provider) is
    currently configured with, and only swap the model. Set the others too
    if bug-bounty work should go through an entirely different
    provider/account than general-mode conversations.
    """
    model: str = Field(..., min_length=1)
    provider: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(None, gt=0)


@router.get("/provider")
async def get_provider_settings():
    """Get current provider settings (API key masked)."""
    return {
        "provider": settings.llm_provider,
        "base_url": settings.llm_base_url,
        "api_key": MASKED_API_KEY if settings.llm_api_key else "",
        "model": settings.llm_model,
        "temperature": settings.llm_temperature,
        "max_tokens": settings.llm_max_tokens,
    }


@router.put("/provider")
async def update_provider_settings(request: ProviderSettings):
    """Update provider settings and apply them immediately — no restart needed.

    The provider name doesn't have to match exactly: it's cross-checked
    against the base_url and model to figure out which API format to speak
    (Anthropic's native Messages API, or an OpenAI-compatible chat/completions
    API used by OpenAI, Ollama, vLLM, LM Studio, and most gateways).
    """
    kind = detect_provider_kind(request.provider, request.base_url, request.model)
    provider_name = canonical_provider_name(request.provider, request.base_url, request.model)

    # If the client echoed back the masked key unchanged, keep the existing secret.
    api_key = settings.llm_api_key if request.api_key == MASKED_API_KEY else request.api_key

    # Build the new provider *before* mutating anything shared, so a bad config
    # (e.g. bad base_url) fails loudly without disturbing the running provider.
    try:
        new_provider = build_provider(
            provider=provider_name,
            base_url=request.base_url,
            api_key=api_key,
            model=request.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    resolved_base_url = getattr(new_provider, "base_url", request.base_url)

    # Apply in-memory so every new agent run picks it up right away.
    settings.llm_provider = provider_name
    settings.llm_base_url = resolved_base_url
    settings.llm_api_key = api_key
    settings.llm_model = request.model
    settings.llm_temperature = request.temperature
    settings.llm_max_tokens = request.max_tokens

    # Persist to .env so the change also survives a future restart.
    try:
        persist_env_vars(
            {
                "LLM_PROVIDER": provider_name,
                "LLM_BASE_URL": resolved_base_url,
                "LLM_API_KEY": api_key,
                "LLM_MODEL": request.model,
                "LLM_TEMPERATURE": str(request.temperature),
                "LLM_MAX_TOKENS": str(request.max_tokens),
            }
        )
    except Exception:
        logger.warning("provider_settings_persist_failed", exc_info=True)

    # Hot-swap the live provider. Runs already in progress keep using the old
    # instance; anything new picks up the change immediately.
    swap_provider(new_provider)

    logger.info(
        "provider_settings_updated",
        provider=provider_name,
        detected_as=kind,
        model=request.model,
    )

    return {
        "status": "updated",
        "message": "Provider settings applied immediately. No restart required.",
        "detected_as": DETECTION_LABELS.get(kind, kind),
        "settings": {
            "provider": provider_name,
            "base_url": resolved_base_url,
            "api_key": MASKED_API_KEY if api_key else "",
            "model": request.model,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        },
    }


@router.post("/provider/test")
async def test_provider_connection(request: ProviderSettings):
    """Test a provider configuration without affecting the live provider."""
    kind = detect_provider_kind(request.provider, request.base_url, request.model)
    provider_name = canonical_provider_name(request.provider, request.base_url, request.model)
    api_key = settings.llm_api_key if request.api_key == MASKED_API_KEY else request.api_key

    try:
        from app.llm.base import Message as LLMMessage

        test_provider = build_provider(
            provider=provider_name,
            base_url=request.base_url,
            api_key=api_key,
            model=request.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
        try:
            await test_provider.chat(
                [LLMMessage(role="user", content="Reply with 'ok'.")],
                max_tokens=5,
            )
        finally:
            if hasattr(test_provider, "close"):
                await test_provider.close()

        label = DETECTION_LABELS.get(kind, kind)
        return {"ok": True, "message": f"Connected to {request.model} via {label}."}
    except Exception as e:
        return {"ok": False, "message": f"Provider test failed: {str(e)}"}


# ---------------------------------------------------------------------------
# Provider chain (multiple providers with automatic failover)
# ---------------------------------------------------------------------------
#
# The primary provider (above) is always the first entry in the chain.
# Anything configured here beyond it is tried, in order, if the one before
# it fails after exhausting its retry budget - see app/llm/fallback.py.


def _entry_key(cfg: dict) -> tuple:
    """Identity used to match a chain entry across requests so a masked API
    key in an incoming PUT can be resolved back to the real stored secret,
    independent of the item's position (rows can be reordered)."""
    return (
        (cfg.get("provider") or "").strip().lower(),
        (cfg.get("base_url") or "").strip().lower(),
        (cfg.get("model") or "").strip().lower(),
    )


def _mask_chain_entry(cfg: dict) -> dict:
    return {
        "name": cfg.get("name") or canonical_provider_name(
            cfg.get("provider", ""), cfg.get("base_url", ""), cfg.get("model", "")
        ),
        "provider": cfg.get("provider", ""),
        "base_url": cfg.get("base_url", ""),
        "api_key": MASKED_API_KEY if cfg.get("api_key") else "",
        "model": cfg.get("model", ""),
        "temperature": cfg.get("temperature", 0.1),
        "max_tokens": cfg.get("max_tokens", 4096),
    }


@router.get("/providers")
async def get_provider_chain():
    """Get the full provider chain (primary + fallbacks) and retry settings."""
    return {
        "providers": [_mask_chain_entry(cfg) for cfg in settings.provider_chain_configs],
        "retry": {
            "max_retries": settings.llm_max_retries,
            "retry_base_delay_seconds": settings.llm_retry_base_delay_seconds,
            "retry_max_delay_seconds": settings.llm_retry_max_delay_seconds,
        },
    }


@router.get("/available-models")
async def get_available_models():
    """List of models a conversation can be pinned to (see the mobile
    app's model/reasoning picker and PATCH /conversations/{id}/settings'
    `model` field) - one entry per configured chain provider, no secrets.
    Lighter than GET /providers, which also returns masked api_keys and
    retry policy that the picker doesn't need."""
    return {"models": get_configured_models()}


@router.put("/providers")
async def update_provider_chain(request: ProviderChainSettings):
    """Replace the whole provider chain and retry settings, then hot-swap the
    live provider to the newly built chain. The first entry becomes the
    primary provider (same fields as PUT /settings/provider); the rest are
    stored as the fallback list, tried in order on failure.
    """
    existing_by_key = {_entry_key(cfg): cfg.get("api_key", "") for cfg in settings.provider_chain_configs}

    resolved: List[dict] = []
    for i, entry in enumerate(request.providers):
        provider_name = canonical_provider_name(entry.provider, entry.base_url, entry.model)
        api_key = entry.api_key
        if api_key == MASKED_API_KEY:
            key = _entry_key(entry.model_dump())
            stored = existing_by_key.get(key, "")
            if not stored:
                raise HTTPException(400, f"Provider #{i + 1} ({entry.model}) is missing an API key.")
            api_key = stored

        resolved.append(
            {
                "name": entry.name or provider_name,
                "provider": provider_name,
                "base_url": entry.base_url,
                "api_key": api_key,
                "model": entry.model,
                "temperature": entry.temperature,
                "max_tokens": entry.max_tokens,
            }
        )

    policy = RetryPolicy(
        max_retries=request.retry.max_retries,
        base_delay=request.retry.retry_base_delay_seconds,
        max_delay=request.retry.retry_max_delay_seconds,
    )

    # Build the new chain *before* mutating anything shared, so a bad config
    # anywhere in the list fails loudly without disturbing the running chain.
    try:
        new_chain = build_provider_chain(resolved, policy)
    except ValueError as e:
        raise HTTPException(400, str(e))

    primary, *fallbacks = resolved

    # Apply in-memory so every new agent run picks it up right away.
    settings.llm_provider_name = "" if primary["name"] == primary["provider"] else primary["name"]
    settings.llm_provider = primary["provider"]
    settings.llm_base_url = primary["base_url"]
    settings.llm_api_key = primary["api_key"]
    settings.llm_model = primary["model"]
    settings.llm_temperature = primary["temperature"]
    settings.llm_max_tokens = primary["max_tokens"]
    settings.llm_fallback_providers = json.dumps(fallbacks)
    settings.llm_max_retries = request.retry.max_retries
    settings.llm_retry_base_delay_seconds = request.retry.retry_base_delay_seconds
    settings.llm_retry_max_delay_seconds = request.retry.retry_max_delay_seconds

    # Persist to .env so the change also survives a future restart.
    try:
        persist_env_vars(
            {
                "LLM_PROVIDER_NAME": settings.llm_provider_name,
                "LLM_PROVIDER": primary["provider"],
                "LLM_BASE_URL": primary["base_url"],
                "LLM_API_KEY": primary["api_key"],
                "LLM_MODEL": primary["model"],
                "LLM_TEMPERATURE": str(primary["temperature"]),
                "LLM_MAX_TOKENS": str(primary["max_tokens"]),
                "LLM_FALLBACK_PROVIDERS": json.dumps(fallbacks),
                "LLM_MAX_RETRIES": str(request.retry.max_retries),
                "LLM_RETRY_BASE_DELAY_SECONDS": str(request.retry.retry_base_delay_seconds),
                "LLM_RETRY_MAX_DELAY_SECONDS": str(request.retry.retry_max_delay_seconds),
            }
        )
    except Exception:
        logger.warning("provider_chain_persist_failed", exc_info=True)

    # Hot-swap the live provider. Runs already in progress keep using the old
    # chain instance; anything new picks up the change immediately.
    swap_provider(new_chain)

    logger.info(
        "provider_chain_updated",
        providers=[cfg["name"] for cfg in resolved],
        max_retries=request.retry.max_retries,
    )

    return {
        "status": "updated",
        "message": f"Provider chain updated ({len(resolved)} provider{'s' if len(resolved) != 1 else ''}). No restart required.",
        "providers": [_mask_chain_entry(cfg) for cfg in resolved],
        "retry": request.retry.model_dump(),
    }


# ---------------------------------------------------------------------------
# Bug-bounty model override
# ---------------------------------------------------------------------------
#
# Deliberately NOT part of .env / app/config.py's Settings - this is a
# per-conversation-mode preference an operator may change often through the
# app, stored via app/storage/app_settings.py (SQLite) instead. See
# app/llm/client.py's get_provider_for_mode(), which AgentExecutor calls
# instead of get_llm_provider() directly.

BUG_BOUNTY_MODEL_KEY = "bug_bounty_model"


def _mask_bug_bounty_cfg(cfg: dict) -> dict:
    return {
        "model": cfg.get("model", ""),
        "provider": cfg.get("provider") or None,
        "base_url": cfg.get("base_url") or None,
        "api_key": MASKED_API_KEY if cfg.get("api_key") else "",
        "temperature": cfg.get("temperature"),
        "max_tokens": cfg.get("max_tokens"),
    }


@router.get("/bug-bounty-model")
async def get_bug_bounty_model():
    """Get the bug-bounty model override, or {"configured": false} if
    bug_bounty-mode conversations are just using the primary provider/model
    like general mode does."""
    cfg = kv_settings.get_json(BUG_BOUNTY_MODEL_KEY)
    if not cfg or not cfg.get("model"):
        return {"configured": False}
    return {"configured": True, **_mask_bug_bounty_cfg(cfg)}


@router.put("/bug-bounty-model")
async def update_bug_bounty_model(request: BugBountyModelSettings):
    """Set (or update) the model bug_bounty-mode conversations should use.
    Applies immediately - the next bug_bounty message picks it up, no
    restart, same hot-swap idea as PUT /settings/provider but scoped to
    this one override rather than the primary chain."""
    existing = kv_settings.get_json(BUG_BOUNTY_MODEL_KEY) or {}

    # If the client echoed back the masked key unchanged, keep the existing
    # secret (same convention as PUT /settings/provider above).
    api_key = request.api_key
    if api_key == MASKED_API_KEY:
        api_key = existing.get("api_key", "")

    cfg = {
        "model": request.model,
        "provider": request.provider or "",
        "base_url": request.base_url or "",
        "api_key": api_key or "",
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
    }
    # Drop unset optional fields entirely rather than storing nulls, so
    # build_bug_bounty_provider()'s `cfg.get(...) or settings.llm_*`
    # fallbacks trigger cleanly at request time - if the primary provider
    # changes later, an override that didn't pin its own provider/base_url/
    # api_key/temperature/max_tokens keeps tracking it. `model` is required
    # (min_length=1) so it always survives this filter.
    cfg = {k: v for k, v in cfg.items() if v not in (None, "")}

    # Build before persisting, so a bad config (bad base_url, empty model
    # for a provider that needs one, etc.) fails loudly without silently
    # saving something broken.
    try:
        build_bug_bounty_provider(cfg)
    except ValueError as e:
        raise HTTPException(400, str(e))

    kv_settings.set_json(BUG_BOUNTY_MODEL_KEY, cfg)
    refresh_bug_bounty_provider()

    logger.info("bug_bounty_model_updated", model=cfg["model"], provider=cfg.get("provider") or "(same as primary)")

    return {
        "status": "updated",
        "message": "Bug-bounty model override applied immediately. No restart required.",
        **_mask_bug_bounty_cfg(cfg),
    }


@router.delete("/bug-bounty-model")
async def clear_bug_bounty_model():
    """Remove the override - bug_bounty-mode conversations go back to using
    the primary provider/model, same as general mode."""
    kv_settings.delete(BUG_BOUNTY_MODEL_KEY)
    refresh_bug_bounty_provider()
    return {"status": "cleared"}


@router.post("/bug-bounty-model/test")
async def test_bug_bounty_model(request: BugBountyModelSettings):
    """Test a bug-bounty model config without saving or affecting the live
    override - same idea as POST /settings/provider/test."""
    existing = kv_settings.get_json(BUG_BOUNTY_MODEL_KEY) or {}
    api_key = request.api_key
    if api_key == MASKED_API_KEY:
        api_key = existing.get("api_key", "")

    cfg = {
        "model": request.model,
        "provider": request.provider or "",
        "base_url": request.base_url or "",
        "api_key": api_key or "",
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
    }
    cfg = {k: v for k, v in cfg.items() if v not in (None, "")}

    try:
        from app.llm.base import Message as LLMMessage

        test_provider = build_bug_bounty_provider(cfg)
        try:
            await test_provider.chat(
                [LLMMessage(role="user", content="Reply with 'ok'.")],
                max_tokens=5,
            )
        finally:
            if hasattr(test_provider, "close"):
                await test_provider.close()

        return {"ok": True, "message": f"Connected to {cfg['model']}."}
    except Exception as e:
        return {"ok": False, "message": f"Bug-bounty model test failed: {str(e)}"}
