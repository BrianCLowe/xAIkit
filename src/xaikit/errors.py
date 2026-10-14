"""Typed errors for xAIkit."""

from __future__ import annotations

import math
import os
from typing import NoReturn

DEFAULT_SDK_TIMEOUT_SECONDS = 180.0
SDK_TIMEOUT_ENV = "XAI_SDK_TIMEOUT_SECONDS"


class XaiKitError(Exception):
    """Base error for xAIkit."""


class XaiTimeoutError(TimeoutError):
    """An xai-sdk RPC exceeded this client's timeout.

    Raised for gRPC ``DEADLINE_EXCEEDED`` on sync and async chat, stream,
    batch, and collections calls. The timeout is per attempt.
    """


class CustomVoiceError(XaiKitError, RuntimeError):
    """An HTTP failure from the custom-voices API.

    ``status_code`` is the response status. The message carries a short server
    detail (at most 500 characters) with the API key removed. Checks that run
    before any request raise ``ValueError`` instead.
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)


class RoleUnavailableOnHost(XaiKitError):
    """An unpinned role has no model on this host.

    ``role`` is ``image``, ``video``, ``voice``, or ``speech-to-text``.
    ``host`` is the host (and port, when one was set) of the client's base URL.
    """

    def __init__(self, role: str, host: str) -> None:
        self.role = role
        self.host = host
        super().__init__(f"{role} is not available on {host}")


def require_positive_seconds(value: object, *, label: str = "timeout") -> float:
    """Return *value* as a finite number of seconds greater than 0."""
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a number of seconds greater than 0")
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number of seconds greater than 0") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{label} must be a number of seconds greater than 0")
    return number


def resolve_sdk_timeout(timeout: float | None) -> float:
    """Constructor value, then ``XAI_SDK_TIMEOUT_SECONDS``, then 180 seconds.

    ``None`` means the env var or the default. ``0`` and negative values raise
    ``ValueError``. The result is always a positive float, never ``None`` or ``0``.
    """
    if timeout is not None:
        return require_positive_seconds(timeout, label="timeout")
    raw = os.environ.get(SDK_TIMEOUT_ENV)
    if raw is None or not str(raw).strip():
        return DEFAULT_SDK_TIMEOUT_SECONDS
    return require_positive_seconds(str(raw).strip(), label=SDK_TIMEOUT_ENV)


def timeout_for_catalog(timeout: float | None) -> float:
    """Timeout for a catalog SDK fetch.

    An explicit value wins. ``None`` uses ``XAI_SDK_TIMEOUT_SECONDS`` when
    set, otherwise 180 seconds. Invalid values follow ``resolve_sdk_timeout``.
    """
    return resolve_sdk_timeout(timeout)


def is_grpc_deadline_exceeded(exc: BaseException) -> bool:
    """True when *exc* is a gRPC error whose status is ``DEADLINE_EXCEEDED``."""
    code = getattr(exc, "code", None)
    if not callable(code):
        return False
    try:
        status = code()
    except Exception:
        return False
    if getattr(status, "name", None) == "DEADLINE_EXCEEDED":
        return True
    try:
        import grpc
    except ImportError:
        grpc = None  # type: ignore[assignment]
    if grpc is not None and status == grpc.StatusCode.DEADLINE_EXCEEDED:
        return True
    return str(status) in {"StatusCode.DEADLINE_EXCEEDED", "DEADLINE_EXCEEDED"}


def as_public_sdk_error(exc: BaseException) -> BaseException:
    """Map gRPC ``DEADLINE_EXCEEDED`` to :class:`XaiTimeoutError`. Other errors stay."""
    if isinstance(exc, XaiTimeoutError):
        return exc
    if is_grpc_deadline_exceeded(exc):
        return XaiTimeoutError("xAI SDK call timed out")
    return exc


def reraise_mapped_sdk_error(exc: BaseException) -> NoReturn:
    """Re-raise *exc*, mapping a gRPC deadline to :class:`XaiTimeoutError`."""
    surfaced = as_public_sdk_error(exc)
    if surfaced is exc:
        raise exc
    raise surfaced from exc


def raise_sdk_or_runtime(exc: BaseException, message: str) -> NoReturn:
    """Raise :class:`XaiTimeoutError` for a deadline, otherwise ``RuntimeError``."""
    surfaced = as_public_sdk_error(exc)
    if isinstance(surfaced, XaiTimeoutError):
        if surfaced is exc:
            raise exc
        raise surfaced from exc
    raise RuntimeError(message) from exc
