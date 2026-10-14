"""Contract tests: custom voice REST wiring (sync client)."""

from __future__ import annotations

import pytest

from custom_voice_suite import CASES, Env, run_case


def _selected():
    return [fn for fn in CASES if not getattr(fn, "async_only", False)]


@pytest.mark.parametrize("func", _selected(), ids=lambda fn: fn.__name__)
def test_custom_voices_sync(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, func) -> None:
    run_case(Env(monkeypatch, caplog, async_mode=False), func)
