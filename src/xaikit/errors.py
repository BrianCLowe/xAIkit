"""Typed errors for xAIkit."""

from __future__ import annotations


class XaiKitError(Exception):
    """Base error for xAIkit."""


class RoleUnavailableOnHost(XaiKitError):
    """An unpinned role has no model on this host.

    ``role`` is ``image``, ``video``, ``voice``, or ``speech-to-text``.
    ``host`` is the host (and port, when one was set) of the client's base URL.
    """

    def __init__(self, role: str, host: str) -> None:
        self.role = role
        self.host = host
        super().__init__(f"{role} is not available on {host}")
