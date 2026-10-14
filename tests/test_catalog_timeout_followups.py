"""CUT-2026-10-14-xk-catalog-timeout-followups.

Offline cases CTF-C01..CTF-C14. Fake key only. No network.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from xaikit import XaiClient
from xaikit.catalog import (
    BOOTSTRAP_MODEL,
    clear_catalog_cache,
    fetch_models_from_sdk,
    inject_catalog,
    list_models,
    resolve_model,
    resolve_model_selection,
)
from xaikit.errors import (
    DEFAULT_SDK_TIMEOUT_SECONDS,
    SDK_TIMEOUT_ENV,
    XaiTimeoutError,
    resolve_sdk_timeout,
    timeout_for_catalog,
)

FAKE_KEY = "xai-fake"
_BOOTSTRAP_IDS = [BOOTSTRAP_MODEL, "grok-4.3"]


class FakeClient:
    """Stand-in for xai_sdk.Client. Records timeout and can stall or return one id."""

    mode = "healthy"
    inits = 0
    listed_timeouts: list[float] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args
        type(self).inits += 1
        timeout = kwargs.get("timeout")
        self.timeout = timeout
        self.models = self

    @classmethod
    def reset(cls) -> None:
        cls.mode = "healthy"
        cls.inits = 0
        cls.listed_timeouts = []

    def close(self) -> None:
        return None

    def list_language_models(self) -> list[object]:
        timeout = self.timeout
        if isinstance(timeout, (int, float)) and not isinstance(timeout, bool):
            type(self).listed_timeouts.append(float(timeout))
        if type(self).mode == "stall":
            raise XaiTimeoutError("xAI SDK call timed out")
        return [SimpleNamespace(name="grok-live-9")]

    def list_image_generation_models(self) -> list[object]:
        if type(self).mode == "stall":
            raise XaiTimeoutError("xAI SDK call timed out")
        return []


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if name.startswith("XAI_"):
            monkeypatch.delenv(name, raising=False)
    inject_catalog(None)
    clear_catalog_cache()
    FakeClient.reset()
    yield
    inject_catalog(None)
    clear_catalog_cache()
    FakeClient.reset()


def _install(monkeypatch: pytest.MonkeyPatch, *, client_module: bool = False) -> None:
    FakeClient.reset()
    monkeypatch.setattr("xai_sdk.Client", FakeClient)
    if client_module:
        monkeypatch.setattr("xaikit.client.Client", FakeClient)


def _ids(rows: list) -> list[str]:
    return [row.id for row in rows]


def _outcome(fn: object) -> tuple[object, ...]:
    try:
        return ("ok", fn())  # type: ignore[operator]
    except Exception as exc:
        return ("err", type(exc), str(exc))


def test_ctf_c01_unset_env_defaults_to_180(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch)
    fetch_models_from_sdk(FAKE_KEY)
    assert FakeClient.listed_timeouts == [180.0]


def test_ctf_c02_fetch_honors_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch)
    monkeypatch.setenv(SDK_TIMEOUT_ENV, "7")
    fetch_models_from_sdk(FAKE_KEY)
    assert FakeClient.listed_timeouts == [7.0]


def test_ctf_c03_list_models_honors_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch)
    monkeypatch.setenv(SDK_TIMEOUT_ENV, "7")
    list_models(api_key=FAKE_KEY, force_refresh=True)
    assert FakeClient.listed_timeouts == [7.0]


def test_ctf_c04_resolve_honors_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch)
    monkeypatch.setenv(SDK_TIMEOUT_ENV, "7")
    resolve_model(api_key=FAKE_KEY)
    assert FakeClient.listed_timeouts == [7.0]
    clear_catalog_cache()
    FakeClient.listed_timeouts = []
    resolve_model_selection(api_key=FAKE_KEY)
    assert FakeClient.listed_timeouts == [7.0]


def test_ctf_c05_explicit_timeout_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch)
    monkeypatch.setenv(SDK_TIMEOUT_ENV, "7")
    fetch_models_from_sdk(FAKE_KEY, timeout=3)
    clear_catalog_cache()
    list_models(api_key=FAKE_KEY, sdk_timeout=3, force_refresh=True)
    clear_catalog_cache()
    resolve_model(api_key=FAKE_KEY, sdk_timeout=3)
    assert FakeClient.listed_timeouts == [3.0, 3.0, 3.0]


def test_ctf_c06_invalid_env_matches_resolve_sdk_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch)
    for raw in ("0", "abc"):
        monkeypatch.setenv(SDK_TIMEOUT_ENV, raw)
        clear_catalog_cache()
        direct = _outcome(lambda: resolve_sdk_timeout(None))
        catalog = _outcome(lambda: timeout_for_catalog(None))
        assert catalog == direct
        fetched = _outcome(lambda: fetch_models_from_sdk(FAKE_KEY))
        assert fetched[0] == direct[0]
        assert fetched[1] is direct[1]
        listed = _outcome(lambda: list_models(api_key=FAKE_KEY, force_refresh=True))
        assert listed[0] == "err"
        assert listed[1] is direct[1]
        assert FakeClient.inits == 0


def test_ctf_c07_constructor_timeout_beats_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, client_module=True)
    monkeypatch.setenv(SDK_TIMEOUT_ENV, "7")
    XaiClient(api_key=FAKE_KEY, timeout=5)
    assert FakeClient.listed_timeouts == [5.0]


def test_ctf_c08_deadline_is_not_shared_with_other_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch)
    FakeClient.mode = "stall"
    stalled = list_models(api_key=FAKE_KEY, sdk_timeout=1)
    assert _ids(stalled) == _BOOTSTRAP_IDS
    after_a = FakeClient.inits
    assert after_a >= 1
    FakeClient.mode = "healthy"
    live = list_models(api_key=FAKE_KEY)
    assert "grok-live-9" in _ids(live)
    assert FakeClient.inits > after_a


def test_ctf_c09_client_deadline_does_not_stick_to_other_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, client_module=True)
    FakeClient.mode = "stall"
    XaiClient(api_key=FAKE_KEY, timeout=1)
    after_a = FakeClient.inits
    FakeClient.mode = "healthy"
    other = XaiClient(api_key=FAKE_KEY)
    assert other.model == "grok-live-9"
    assert FakeClient.inits > after_a


def test_ctf_c10_deadline_caller_keeps_retry_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch)
    FakeClient.mode = "stall"
    first = list_models(api_key=FAKE_KEY, sdk_timeout=1)
    assert _ids(first) == _BOOTSTRAP_IDS
    after = FakeClient.inits
    second = list_models(api_key=FAKE_KEY, sdk_timeout=1)
    assert _ids(second) == _BOOTSTRAP_IDS
    assert FakeClient.inits == after


def test_ctf_c11_deadline_does_not_replace_other_live_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch)
    FakeClient.mode = "healthy"
    live = list_models(api_key=FAKE_KEY)
    assert "grok-live-9" in _ids(live)
    FakeClient.mode = "stall"
    stalled = list_models(api_key=FAKE_KEY, sdk_timeout=1, force_refresh=True)
    assert _ids(stalled) == _BOOTSTRAP_IDS
    FakeClient.mode = "healthy"
    again = list_models(api_key=FAKE_KEY)
    assert "grok-live-9" in _ids(again)
    assert _ids(again) != _BOOTSTRAP_IDS


def test_ctf_c12_no_key_does_not_call_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch)
    FakeClient.mode = "stall"
    rows = list_models(sdk_timeout=1)
    assert _ids(rows) == _BOOTSTRAP_IDS
    assert FakeClient.inits == 0
    again = list_models()
    assert _ids(again) == _BOOTSTRAP_IDS
    assert FakeClient.inits == 0


def test_ctf_c13_existing_timeout_tests_stay_in_place() -> None:
    """C13 is the unedited tests/test_sdk_timeout.py and tests/test_catalog.py run."""
    root = os.path.dirname(os.path.dirname(__file__))
    timeout_tests = open(
        os.path.join(root, "tests", "test_sdk_timeout.py"), encoding="utf-8"
    ).read()
    catalog_tests = open(
        os.path.join(root, "tests", "test_catalog.py"), encoding="utf-8"
    ).read()
    assert "def test_to1_5_catalog_default_and_explicit" in timeout_tests
    assert "def test_list_models_deadline_fallback_uses_short_retry_window" in timeout_tests
    assert "def test_sdk_failure_with_key_bootstraps_and_does_not_retry_within_ttl" in catalog_tests


def test_ctf_c14_default_constant_stays_180() -> None:
    assert DEFAULT_SDK_TIMEOUT_SECONDS == 180.0
