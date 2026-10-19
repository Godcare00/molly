import httpx
import pytest
from unittest.mock import AsyncMock, patch

from app.llm.base import LLMResponse, Message as LLMMessage
from app.llm.fallback import AllProvidersFailedError, FallbackLLMProvider
from app.llm.retry import RetryPolicy, compute_delay, is_retryable


def _http_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://example.com/v1/messages")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


def _make_provider(name: str, model: str = "test-model"):
    """A minimal stand-in for a real LLMProvider with mockable chat/chat_stream."""
    provider = AsyncMock()
    provider.get_model_name.return_value = model
    provider.supports_images.return_value = True
    return provider


@pytest.fixture(autouse=True)
def no_real_sleep():
    """Retry backoff would otherwise slow every test down for no reason."""
    with patch("app.llm.fallback.asyncio.sleep", new=AsyncMock(return_value=None)):
        yield


class TestRetryClassification:
    def test_rate_limit_is_retryable(self):
        assert is_retryable(_http_error(429)) is True

    def test_server_error_is_retryable(self):
        assert is_retryable(_http_error(503)) is True

    def test_unauthorized_is_not_retryable(self):
        assert is_retryable(_http_error(401)) is False

    def test_bad_request_is_not_retryable(self):
        assert is_retryable(_http_error(400)) is False

    def test_timeout_is_retryable(self):
        assert is_retryable(httpx.ConnectTimeout("timed out")) is True

    def test_unknown_exception_is_not_retryable(self):
        assert is_retryable(ValueError("weird")) is False

    def test_delay_grows_and_is_capped(self):
        policy = RetryPolicy(base_delay=1.0, max_delay=5.0, jitter=0.0)
        assert compute_delay(policy, 0) == pytest.approx(1.0)
        assert compute_delay(policy, 1) == pytest.approx(2.0)
        assert compute_delay(policy, 10) == pytest.approx(5.0)  # capped


class TestFallbackChat:
    @pytest.mark.asyncio
    async def test_first_provider_success_no_fallback(self):
        p1 = _make_provider("primary")
        p1.chat.return_value = LLMResponse(content="hi from primary")

        chain = FallbackLLMProvider([("primary", p1)])
        response = await chain.chat([LLMMessage(role="user", content="hello")])

        assert response.content == "hi from primary"
        assert response.provider == "primary"
        assert response.provider_attempts is None
        p1.chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_non_retryable_error_skips_straight_to_next_provider(self):
        p1 = _make_provider("primary")
        p1.chat.side_effect = _http_error(401)
        p2 = _make_provider("backup")
        p2.chat.return_value = LLMResponse(content="hi from backup")

        chain = FallbackLLMProvider(
            [("primary", p1), ("backup", p2)], RetryPolicy(max_retries=3)
        )
        response = await chain.chat([LLMMessage(role="user", content="hello")])

        assert response.content == "hi from backup"
        assert response.provider == "backup"
        assert response.provider_attempts == [{"name": "primary", "error": str(_http_error(401))}]
        # A 401 isn't retryable, so it should only be called once, not 4 times.
        assert p1.chat.await_count == 1

    @pytest.mark.asyncio
    async def test_retryable_error_is_retried_before_falling_over(self):
        p1 = _make_provider("primary")
        p1.chat.side_effect = _http_error(503)
        p2 = _make_provider("backup")
        p2.chat.return_value = LLMResponse(content="hi from backup")

        chain = FallbackLLMProvider(
            [("primary", p1), ("backup", p2)], RetryPolicy(max_retries=2)
        )
        response = await chain.chat([LLMMessage(role="user", content="hello")])

        assert response.content == "hi from backup"
        # Initial attempt + 2 retries = 3 calls to the failing provider.
        assert p1.chat.await_count == 3
        assert p2.chat.await_count == 1

    @pytest.mark.asyncio
    async def test_recovers_after_transient_failure_without_falling_over(self):
        p1 = _make_provider("primary")
        p1.chat.side_effect = [_http_error(503), LLMResponse(content="recovered")]

        chain = FallbackLLMProvider([("primary", p1)], RetryPolicy(max_retries=2))
        response = await chain.chat([LLMMessage(role="user", content="hello")])

        assert response.content == "recovered"
        assert response.provider == "primary"
        assert p1.chat.await_count == 2

    @pytest.mark.asyncio
    async def test_all_providers_failing_raises_aggregate_error(self):
        p1 = _make_provider("primary")
        p1.chat.side_effect = _http_error(500)
        p2 = _make_provider("backup")
        p2.chat.side_effect = _http_error(401)

        chain = FallbackLLMProvider(
            [("primary", p1), ("backup", p2)], RetryPolicy(max_retries=0)
        )

        with pytest.raises(AllProvidersFailedError) as exc_info:
            await chain.chat([LLMMessage(role="user", content="hello")])

        assert {a["name"] for a in exc_info.value.attempts} == {"primary", "backup"}
        assert "primary" in str(exc_info.value)
        assert "backup" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_single_provider_chain_still_applies_retries(self):
        """A chain of length 1 (no fallbacks configured) still gets retry
        behavior - fallback and retry are independent features."""
        p1 = _make_provider("primary")
        p1.chat.side_effect = [_http_error(503), _http_error(503), LLMResponse(content="ok")]

        chain = FallbackLLMProvider([("primary", p1)], RetryPolicy(max_retries=2))
        response = await chain.chat([LLMMessage(role="user", content="hello")])

        assert response.content == "ok"
        assert p1.chat.await_count == 3


class TestFallbackChatStream:
    @pytest.mark.asyncio
    async def test_falls_over_before_any_chunk_is_yielded(self):
        p1 = _make_provider("primary")

        async def failing_stream(*args, **kwargs):
            raise _http_error(503)
            yield  # pragma: no cover - makes this an async generator

        async def good_stream(*args, **kwargs):
            yield "hello "
            yield "world"

        p1.chat_stream.side_effect = failing_stream
        p2 = _make_provider("backup")
        p2.chat_stream.side_effect = good_stream

        chain = FallbackLLMProvider(
            [("primary", p1), ("backup", p2)], RetryPolicy(max_retries=0)
        )

        chunks = [c async for c in chain.chat_stream([LLMMessage(role="user", content="hi")])]
        assert chunks == ["hello ", "world"]

    @pytest.mark.asyncio
    async def test_mid_stream_failure_does_not_fall_over(self):
        """Once output has started streaming to the caller we can't safely
        retry or fall back without duplicating content - the error must
        propagate instead of silently switching providers."""
        p1 = _make_provider("primary")

        async def partial_then_fail(*args, **kwargs):
            yield "partial "
            raise _http_error(503)

        p1.chat_stream.side_effect = partial_then_fail
        p2 = _make_provider("backup")

        chain = FallbackLLMProvider(
            [("primary", p1), ("backup", p2)], RetryPolicy(max_retries=2)
        )

        chunks = []
        with pytest.raises(httpx.HTTPStatusError):
            async for c in chain.chat_stream([LLMMessage(role="user", content="hi")]):
                chunks.append(c)

        assert chunks == ["partial "]
        p2.chat_stream.assert_not_called()


class TestBuildProviderChain:
    def test_requires_at_least_one_provider(self):
        from app.llm.client import build_provider_chain

        with pytest.raises(ValueError):
            build_provider_chain([])

    def test_builds_named_chain_from_configs(self):
        from app.llm.client import build_provider_chain

        configs = [
            {
                "name": "openai-primary",
                "provider": "openai",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-test",
                "model": "gpt-4o",
            },
            {
                "provider": "anthropic",
                "base_url": "https://api.anthropic.com/v1",
                "api_key": "sk-ant-test",
                "model": "claude-sonnet-4-6",
            },
        ]
        chain = build_provider_chain(configs)
        names = [name for name, _ in chain.chain]
        assert names == ["openai-primary", "anthropic"]
        assert chain.chain[1][1].get_model_name() == "claude-sonnet-4-6"
