"""Pytest hooks for XaiKit."""

from __future__ import annotations


def pytest_configure(config) -> None:  # type: ignore[no-untyped-def]
    config.addinivalue_line(
        "markers",
        "live: hits the live xAI API (requires XAI_API_KEY and XAITKIT_LIVE=1)",
    )
