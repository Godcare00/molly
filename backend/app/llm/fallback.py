import asyncio
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

import structlog

from app.llm.base import LLMProvider, LLMResponse, Message
from app.llm.retry import RetryPolicy, compute_delay, is_retryable
from app.tools.registry import ToolSchema

logger = structlog.get_logger()


class AllProvidersFailedError(Exception):
    """Raised when every provider in the fallback chain has failed."""

    def __init__(self, attempts: List[Dict[str, str]]):
        self.attempts = attempts
        summary = "; ".join(f"{a['name']}: {a['error']}" for a in attempts) or "no providers configured"
        super().__init__(f"All LLM providers failed - {summary}")


class FallbackLLMProvider(LLMProvider):
    """Wraps an ordered chain of providers.

    Each provider is retried (with exponential backoff) up to
    `policy.max_retries` times on transient errors before the chain moves on
    to the next provider. Errors that a retry can't plausibly fix (bad API
    key, malformed request, unknown model) skip straight to the next
    provider without spending the retry budget.

    A chain of a single provider still goes through this wrapper so retry
    behavior is applied uniformly whether or not fallback providers are
    configured.
    """

    def __init__(self, chain: List[Tuple[str, LLMProvider]], policy: Optional[RetryPolicy] = None):
        if not chain:
            raise ValueError("FallbackLLMProvider requires at least one provider")
        self.chain = chain
        self.policy = policy or RetryPolicy()
        # Index of the provider that most recently served a request - purely
        # informational (used for get_model_name()) so a status display has
        # something sensible to show before the first request completes.
        self._last_success_index = 0

    def get_model_name(self) -> str:
        idx = min(self._last_success_index, len(self.chain) - 1)
        return self.chain[idx][1].get_model_name()

    def supports_images(self) -> bool:
        return all(provider.supports_images() for _, provider in self.chain)

    async def close(self):
        for _, provider in self.chain:
            if hasattr(provider, "close"):
                await provider.close()

    async def _run_with_retry(self, name: str, provider: LLMProvider, coro_factory):
        """Run one provider through its retry budget. Returns the result, or
        raises the final error once retries (if any apply) are exhausted."""
        attempt = 0
        while True:
            try:
                return await coro_factory()
            except Exception as e:
                if not is_retryable(e) or attempt >= self.policy.max_retries:
                    raise
                delay = compute_delay(self.policy, attempt)
                logger.warning(
                    "llm_provider_retry",
                    provider=name,
                    attempt=attempt + 1,
                    max_retries=self.policy.max_retries,
                    delay_seconds=round(delay, 2),
                    error=str(e),
                )
                await asyncio.sleep(delay)
                attempt += 1

    async def chat(
        self,
        messages: List[Message],
        tools: Optional[List[ToolSchema]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
    ) -> LLMResponse:
        attempts_log: List[Dict[str, str]] = []
        for i, (name, provider) in enumerate(self.chain):
            try:
                response = await self._run_with_retry(
                    name,
                    provider,
                    lambda: provider.chat(
                        messages,
                        tools=tools,
                        model=model,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        reasoning_effort=reasoning_effort,
                    ),
                )
            except Exception as e:
                attempts_log.append({"name": name, "error": str(e)})
                logger.warning("llm_provider_failed", provider=name, error=str(e))
                continue

            if attempts_log:
                logger.warning(
                    "llm_provider_fallback_succeeded",
                    used_provider=name,
                    failed_providers=[a["name"] for a in attempts_log],
                )
            self._last_success_index = i
            response.provider = name
            response.model_used = provider.get_model_name()
            response.provider_attempts = attempts_log or None
            return response

        raise AllProvidersFailedError(attempts_log)

    async def chat_stream(
        self,
        messages: List[Message],
        tools: Optional[List[ToolSchema]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
    ) -> AsyncIterator[str]:
        attempts_log: List[Dict[str, str]] = []
        for i, (name, provider) in enumerate(self.chain):
            attempt = 0
            started = False
            while True:
                try:
                    async for chunk in provider.chat_stream(
                        messages,
                        tools=tools,
                        model=model,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        reasoning_effort=reasoning_effort,
                    ):
                        started = True
                        yield chunk
                    if attempts_log:
                        logger.warning(
                            "llm_provider_fallback_succeeded",
                            used_provider=name,
                            failed_providers=[a["name"] for a in attempts_log],
                        )
                    self._last_success_index = i
                    return
                except Exception as e:
                    if started:
                        # Already streamed partial output to the caller - we
                        # can't retry or fall back mid-stream without
                        # duplicating content, so let this propagate.
                        raise
                    if is_retryable(e) and attempt < self.policy.max_retries:
                        delay = compute_delay(self.policy, attempt)
                        logger.warning(
                            "llm_provider_retry",
                            provider=name,
                            attempt=attempt + 1,
                            max_retries=self.policy.max_retries,
                            delay_seconds=round(delay, 2),
                            error=str(e),
                        )
                        await asyncio.sleep(delay)
                        attempt += 1
                        continue
                    attempts_log.append({"name": name, "error": str(e)})
                    logger.warning("llm_provider_failed", provider=name, error=str(e))
                    break  # move on to the next provider in the chain

        raise AllProvidersFailedError(attempts_log)
