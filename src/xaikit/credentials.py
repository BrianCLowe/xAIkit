"""Credential resolution interface for XaiKit (no SQLModel / User required)."""

from __future__ import annotations

import os
from typing import Protocol, runtime_checkable

_ENV_KEY_OMITTED = object()
_DEFAULT_API_KEY_ENV = "XAI_API_KEY"


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
    """App-level key from a passed string, or from the environment at construction.

    Pass ``api_key`` to store that string and skip the environment. Blank
    becomes no key. Omit ``api_key`` to read ``os.environ[name]`` once while
    building the store. ``name`` defaults to ``XAI_API_KEY``. An unset or
    whitespace-only variable raises ``RuntimeError`` immediately. The env
    value is stored raw so ``XaiClient`` can normalize whitespace and a
    leading Bearer prefix.
    """

    def __init__(
        self,
        api_key: str | None | object = _ENV_KEY_OMITTED,
        *,
        name: str = _DEFAULT_API_KEY_ENV,
    ) -> None:
        if api_key is _ENV_KEY_OMITTED:
            raw = os.environ.get(name)
            if raw is None or raw.strip() == "":
                raise RuntimeError(
                    "xAI API key is not configured. "
                    f"Environment variable {name} is unset or empty."
                )
            self._api_key = raw
            return
        supplied = api_key if isinstance(api_key, str) else ""
        self._api_key = supplied.strip() or None

    def get_api_key(self, subject: str | None = None) -> str | None:
        # subject is ignored. This store is app-level only.
        _ = subject
        return self._api_key
