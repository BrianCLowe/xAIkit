"""Credential resolution interface for XaiKit (no SQLModel / User required)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class CredentialStore(Protocol):
    """Injected store for app- and/or user-scoped xAI credentials."""

    def get_api_key(self, subject: str | None = None) -> str | None:
        """Return a bearer credential for *subject*, or app/default when None."""
        ...


class DictCredentialStore:
    """Simple in-memory store: subject → api key; ``None`` / ``\"\"`` key for default."""

    def __init__(self, mapping: dict[str | None, str] | None = None) -> None:
        self._map: dict[str | None, str] = dict(mapping or {})

    def set_api_key(self, key: str, *, subject: str | None = None) -> None:
        cleaned = (key or "").strip()
        if not cleaned:
            raise ValueError("API key is required")
        self._map[subject] = cleaned

    def clear(self, subject: str | None = None) -> None:
        self._map.pop(subject, None)

    def get_api_key(self, subject: str | None = None) -> str | None:
        if subject is not None:
            hit = (self._map.get(subject) or "").strip()
            if hit:
                return hit
        default = (self._map.get(None) or self._map.get("") or "").strip()
        return default or None


class EnvCredentialStore:
    """Resolve from a pre-loaded env-style key string (caller reads os.environ)."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = (api_key or "").strip() or None

    def get_api_key(self, subject: str | None = None) -> str | None:
        # subject ignored — app-level env key only
        _ = subject
        return self._api_key
