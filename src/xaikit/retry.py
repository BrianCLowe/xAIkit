"""Retry / timeout policy for XaiKit provider calls.

Lightweight (no tenacity dependency). Retries transient SDK / network failures;
does not retry validation or JSON-parse errors raised after a successful sample.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

_RETRYABLE_NAMES = frozenset(
    {
        "TimeoutError",
        "ConnectionError",
        "ConnectTimeout",
        "ReadTimeout",
        "APIConnectionError",
        "APITimeoutError",
        "ServiceUnavailable",
        "InternalServerError",
        "RateLimitError",
        "TooManyRequests",
    }
)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """How many attempts and how long to wait between them."""

    max_attempts: int = 3
    backoff_seconds: float = 0.5
    backoff_multiplier: float = 2.0
    max_backoff_seconds: float = 8.0
    timeout_seconds: float = 0.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            object.__setattr__(self, "max_attempts", 1)


def default_retry_policy(
    *,
    max_attempts: int = 3,
    backoff_seconds: float = 0.5,
    backoff_multiplier: float = 2.0,
    max_backoff_seconds: float = 8.0,
    timeout_seconds: float = 0.0,
) -> RetryPolicy:
    """Build policy from kwargs only (no settings import)."""
    return RetryPolicy(
        max_attempts=max(1, int(max_attempts)),
        backoff_seconds=max(0.0, float(backoff_seconds)),
        backoff_multiplier=max(1.0, float(backoff_multiplier)),
        max_backoff_seconds=max(0.0, float(max_backoff_seconds)),
        timeout_seconds=max(0.0, float(timeout_seconds)),
    )


def is_retryable(exc: BaseException) -> bool:
    """True for transient network/SDK failures; False for ValueError/parse errors."""
    if isinstance(exc, (ValueError, TypeError, json.JSONDecodeError)):
        return False
    name = type(exc).__name__
    if name in _RETRYABLE_NAMES:
        return True
    msg = str(exc).lower()
    transient_markers = (
        "timeout",
        "timed out",
        "connection",
        "temporarily",
        "unavailable",
        "rate limit",
        "too many requests",
        "503",
        "502",
        "429",
        "transient",
        "network",
    )
    if any(m in msg for m in transient_markers):
        return True
    if name == "RuntimeError" and "invalid json" not in msg and "not an object" not in msg:
        if "xai request failed" in msg or "mock provider" in msg or "network" in msg:
            return True
        if "json" not in msg and "schema" not in msg:
            return True
    return False


def call_with_retry(
    fn: Callable[[], T],
    *,
    policy: RetryPolicy | None = None,
    sleep: Callable[[float], None] = time.sleep,
    is_retryable_fn: Callable[[BaseException], bool] = is_retryable,
    label: str = "xai",
) -> T:
    """Invoke *fn* with retries on transient failures."""
    pol = policy or default_retry_policy()
    started = time.monotonic()
    last_exc: BaseException | None = None
    delay = pol.backoff_seconds

    for attempt in range(1, pol.max_attempts + 1):
        if pol.timeout_seconds > 0:
            elapsed = time.monotonic() - started
            if elapsed >= pol.timeout_seconds:
                if last_exc is not None:
                    raise TimeoutError(
                        f"{label}: overall timeout {pol.timeout_seconds}s exceeded"
                    ) from last_exc
                raise TimeoutError(
                    f"{label}: overall timeout {pol.timeout_seconds}s exceeded"
                )
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            retryable = is_retryable_fn(exc)
            if not retryable or attempt >= pol.max_attempts:
                raise
            if pol.timeout_seconds > 0:
                remaining = pol.timeout_seconds - (time.monotonic() - started)
                if remaining <= 0:
                    raise TimeoutError(
                        f"{label}: overall timeout {pol.timeout_seconds}s exceeded"
                    ) from exc
                sleep_for = min(delay, remaining, pol.max_backoff_seconds)
            else:
                sleep_for = min(delay, pol.max_backoff_seconds)
            logger.warning(
                "%s attempt %d/%d failed (%s); retry in %.2fs",
                label,
                attempt,
                pol.max_attempts,
                type(exc).__name__,
                sleep_for,
            )
            if sleep_for > 0:
                sleep(sleep_for)
            delay = min(delay * pol.backoff_multiplier, pol.max_backoff_seconds)

    assert last_exc is not None
    raise last_exc
