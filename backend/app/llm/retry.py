import random
from dataclasses import dataclass

import httpx


@dataclass
class RetryPolicy:
    """Retry behavior applied to a single provider before the fallback chain
    gives up on it and moves to the next one."""

    max_retries: int = 2       # additional attempts after the first try
    base_delay: float = 1.0    # seconds, doubles each retry
    max_delay: float = 20.0    # cap on the backoff delay
    jitter: float = 0.25       # +/- fraction of the computed delay


# Status codes where retrying the *exact same request against the exact same
# provider* is very unlikely to help (bad/missing key, malformed request,
# unknown model, etc.) - these skip straight to the next provider in the
# chain instead of burning through the retry budget first.
_NON_RETRYABLE_STATUS_CODES = {400, 401, 403, 404, 422}


def is_retryable(exc: Exception) -> bool:
    """Whether the *same* provider is worth retrying for this error, as
    opposed to giving up on it immediately and moving to the next one."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code not in _NON_RETRYABLE_STATUS_CODES
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return True
    return False


def compute_delay(policy: RetryPolicy, attempt: int) -> float:
    """Exponential backoff with jitter. `attempt` is 0-indexed (0 = delay
    before the first retry)."""
    delay = min(policy.base_delay * (2**attempt), policy.max_delay)
    spread = delay * policy.jitter
    return max(0.0, delay + random.uniform(-spread, spread))
