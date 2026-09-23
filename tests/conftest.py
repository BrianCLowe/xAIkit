"""Pytest hooks for XaiKit."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_public_price_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gap-file lookup stays offline unless a test patches the fetch itself."""
    from xaikit.pricing import clear_public_price_cache

    clear_public_price_cache()
    monkeypatch.setattr(
        "xaikit.pricing.fetch_public_price_payload",
        lambda url="", timeout=10.0: None,
    )


def pytest_configure(config) -> None:  # type: ignore[no-untyped-def]
    config.addinivalue_line(
        "markers",
        "live: hits the live xAI API (requires XAI_API_KEY and XAITKIT_LIVE=1)",
    )
