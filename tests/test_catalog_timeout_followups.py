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
    CATALOG_TIMEOUT_RETRY_SECONDS,
    ModelInfo,
    cached_catalog,
    catalog_source,
    clear_catalog_cache,
    fetch_models_from_sdk,
    find_cached_model,
    inject_catalog,
    list_models,
    resolve_model,
    resolve_model_selection,
    save_catalog_snapshot,
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
    live_name = "grok-live-9"
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
        cls.live_name = "grok-live-9"
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
        if type(self).mode == "error":
            raise RuntimeError("list down")
        return [SimpleNamespace(name=type(self).live_name)]

    def list_image_generation_models(self) -> list[object]:
        if type(self).mode == "stall":
            raise XaiTimeoutError("xAI SDK call timed out")
        if type(self).mode == "error":
            raise RuntimeError("list down")
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


def test_fresh_live_snapshot_is_shared_across_timeouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fresh live list is reused by another timeout, including when that fetch would stall."""
    _install(monkeypatch)
    FakeClient.mode = "healthy"
    live = list_models(api_key=FAKE_KEY)
    assert "grok-live-9" in _ids(live)
    after_live = FakeClient.inits
    FakeClient.mode = "stall"
    reused = list_models(api_key=FAKE_KEY, sdk_timeout=1)
    assert "grok-live-9" in _ids(reused)
    assert _ids(reused) != _BOOTSTRAP_IDS
    assert FakeClient.inits == after_live


def test_successful_fetch_replaces_shared_fallback_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A later live fetch replaces the shared snapshot left by another timeout's deadline."""
    _install(monkeypatch)
    FakeClient.mode = "stall"
    stalled = list_models(api_key=FAKE_KEY, sdk_timeout=1)
    assert _ids(stalled) == _BOOTSTRAP_IDS
    assert catalog_source() == "sdk-error"
    assert find_cached_model("grok-4.7") is not None
    FakeClient.mode = "healthy"
    live = list_models(api_key=FAKE_KEY)
    assert "grok-live-9" in _ids(live)
    assert catalog_source() == "sdk"
    cached = cached_catalog()
    assert cached is not None
    assert "grok-live-9" in _ids(cached)
    assert find_cached_model("grok-live-9") is not None
    assert find_cached_model("grok-4.7") is None


def test_refresh_then_other_timeout_sees_latest_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A later successful fetch replaces the one live snapshot other timeouts read."""
    _install(monkeypatch)
    FakeClient.mode = "healthy"
    FakeClient.live_name = "grok-live-9"
    first = list_models(api_key=FAKE_KEY, sdk_timeout=5)
    assert "grok-live-9" in _ids(first)
    FakeClient.live_name = "grok-live-10"
    refreshed = list_models(api_key=FAKE_KEY, sdk_timeout=5, force_refresh=True)
    assert "grok-live-10" in _ids(refreshed)
    assert "grok-live-9" not in _ids(refreshed)
    after = FakeClient.inits
    other = list_models(api_key=FAKE_KEY, sdk_timeout=1)
    assert "grok-live-10" in _ids(other)
    assert "grok-live-9" not in _ids(other)
    assert FakeClient.inits == after
    assert catalog_source() == "sdk"
    cached = cached_catalog()
    assert cached is not None
    assert "grok-live-10" in _ids(cached)
    assert "grok-live-9" not in _ids(cached)

    FakeClient.mode = "stall"
    stalled = list_models(api_key=FAKE_KEY, sdk_timeout=5, force_refresh=True)
    assert _ids(stalled) == _BOOTSTRAP_IDS
    assert catalog_source() == "sdk"
    assert find_cached_model("grok-live-10") is not None
    again = list_models(api_key=FAKE_KEY, sdk_timeout=1)
    assert "grok-live-10" in _ids(again)
    assert _ids(again) != _BOOTSTRAP_IDS


_TIMEOUT_A = 1.0
_TIMEOUT_B = 5.0
_REST_BASE = "https://example.test/v1"
_SOURCE_KINDS = [
    "sdk",
    "rest",
    "persist-explicit",
    "fixture-explicit",
    "inject",
    "bootstrap",
    "persist-fallback",
    "fixture-fallback",
    "sdk-error",
    "deadline",
    "deadline-persist",
    "deadline-fixture",
]
_LIVE_KINDS = {"sdk", "rest"}
_EXPLICIT_KINDS = {"persist-explicit", "fixture-explicit", "inject", "bootstrap"}
_DEADLINE_KINDS = {"deadline", "deadline-persist", "deadline-fixture"}


def _tick(clock: dict[str, float], seconds: float = 1.0) -> None:
    clock["t"] += seconds


def _write_fixture(path, model_id: str) -> None:
    path.write_text(
        '[{"id": "%s", "capabilities": ["chat"]}]' % model_id,
        encoding="utf-8",
    )


def _save_persist(path, model_id: str) -> None:
    save_catalog_snapshot(path, [ModelInfo(id=model_id, capabilities=["chat"])])


def _seed_fallback(tmp_path) -> None:
    path = tmp_path / "seed.json"
    _write_fixture(path, "seed-fallback")
    FakeClient.mode = "stall"
    rows = list_models(
        api_key=FAKE_KEY,
        sdk_timeout=_TIMEOUT_A,
        fixture_path=path,
        force_refresh=True,
    )
    assert _ids(rows) == ["seed-fallback"]


@pytest.mark.parametrize("kind", _SOURCE_KINDS)
@pytest.mark.parametrize("live_present", [False, True])
def test_snapshot_source_cache_class(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    kind: str,
    live_present: bool,
) -> None:
    """Every source, with and without a live snapshot, then a newer live load.

    Live SDK and REST are the one shared snapshot and clear every fallback.
    A failed fetch stores persist, fixture, sdk-error, or a deadline body on
    that timeout only. The next read for that timeout must not keep an older
    sdk-error. Caller inject, fixture, and persist replace the shared snapshot.
    Bootstrap replaces it too and leaves another timeout's fallback in place.
    """
    _install(monkeypatch)
    clock = {"t": 1_000_000.0}
    monkeypatch.setattr("xaikit.catalog.time.time", lambda: clock["t"])
    rest_calls = {"n": 0}

    def _rest(api_key: str, base_url: str) -> list[ModelInfo]:
        del api_key, base_url
        rest_calls["n"] += 1
        return [ModelInfo(id="grok-rest-1", capabilities=["chat"])]

    monkeypatch.setattr("xaikit.catalog.fetch_models_via_rest", _rest)

    if live_present:
        FakeClient.mode = "healthy"
        FakeClient.live_name = "grok-live-9"
        planted = list_models(api_key=FAKE_KEY, sdk_timeout=_TIMEOUT_B)
        assert _ids(planted) == ["grok-live-9"]
        _tick(clock)

    _seed_fallback(tmp_path)
    # Same tick as the seed so a live load must clear the fallback. A newer
    # timestamp alone would not be what hides it.
    expected = _load_source(kind, tmp_path)
    _assert_source(kind, expected, live_present, rest_calls)
    _assert_window(kind, expected, clock, live_present)
    _assert_newer_live_clears(kind, clock)


def _load_source(kind: str, tmp_path) -> list[str]:
    FakeClient.live_name = "grok-sdk"
    if kind == "sdk":
        FakeClient.mode = "healthy"
        rows = list_models(api_key=FAKE_KEY, sdk_timeout=_TIMEOUT_B, force_refresh=True)
    elif kind == "rest":
        rows = list_models(
            api_key=FAKE_KEY,
            sdk_timeout=_TIMEOUT_A,
            base_url=_REST_BASE,
            force_refresh=True,
        )
    elif kind == "persist-explicit":
        _save_persist(tmp_path / "explicit.json", "from-persist")
        rows = list_models(
            persist_path=tmp_path / "explicit.json",
            sdk_timeout=_TIMEOUT_A,
            force_refresh=True,
        )
    elif kind == "fixture-explicit":
        _write_fixture(tmp_path / "explicit.json", "from-fixture")
        rows = list_models(
            fixture_path=tmp_path / "explicit.json",
            sdk_timeout=_TIMEOUT_A,
            force_refresh=True,
        )
    elif kind == "inject":
        inject_catalog([ModelInfo(id="from-inject", capabilities=["chat"])])
        rows = list_models(sdk_timeout=_TIMEOUT_A, force_refresh=True)
    elif kind == "bootstrap":
        rows = list_models(sdk_timeout=_TIMEOUT_A, force_refresh=True)
    elif kind == "persist-fallback":
        _save_persist(tmp_path / "fallback.json", "from-persist")
        FakeClient.mode = "error"
        rows = list_models(
            api_key=FAKE_KEY,
            sdk_timeout=_TIMEOUT_A,
            persist_path=tmp_path / "fallback.json",
            force_refresh=True,
        )
    elif kind == "fixture-fallback":
        _write_fixture(tmp_path / "fallback.json", "from-fixture")
        FakeClient.mode = "error"
        rows = list_models(
            api_key=FAKE_KEY,
            sdk_timeout=_TIMEOUT_A,
            fixture_path=tmp_path / "fallback.json",
            force_refresh=True,
        )
    elif kind == "sdk-error":
        FakeClient.mode = "error"
        rows = list_models(api_key=FAKE_KEY, sdk_timeout=_TIMEOUT_A, force_refresh=True)
    elif kind == "deadline":
        FakeClient.mode = "stall"
        rows = list_models(api_key=FAKE_KEY, sdk_timeout=_TIMEOUT_A, force_refresh=True)
    elif kind == "deadline-persist":
        _save_persist(tmp_path / "deadline.json", "from-persist")
        FakeClient.mode = "stall"
        rows = list_models(
            api_key=FAKE_KEY,
            sdk_timeout=_TIMEOUT_A,
            persist_path=tmp_path / "deadline.json",
            force_refresh=True,
        )
    elif kind == "deadline-fixture":
        _write_fixture(tmp_path / "deadline.json", "from-fixture")
        FakeClient.mode = "stall"
        rows = list_models(
            api_key=FAKE_KEY,
            sdk_timeout=_TIMEOUT_A,
            fixture_path=tmp_path / "deadline.json",
            force_refresh=True,
        )
    else:
        raise AssertionError(kind)
    return _ids(rows)


def _reread(kind: str, *, with_key: bool) -> list[str]:
    kwargs: dict[str, object] = {"sdk_timeout": _TIMEOUT_A}
    if with_key:
        kwargs["api_key"] = FAKE_KEY
    return _ids(list_models(**kwargs))  # type: ignore[arg-type]


def _assert_source(
    kind: str,
    expected: list[str],
    live_present: bool,
    rest_calls: dict[str, int],
) -> None:
    assert "seed-fallback" not in expected or kind == "bootstrap"
    if kind == "bootstrap":
        assert expected == _BOOTSTRAP_IDS
        assert catalog_source() == "bootstrap"
        held = _reread(kind, with_key=False)
        assert held == ["seed-fallback"]
        other = _ids(list_models(sdk_timeout=_TIMEOUT_B))
        assert other == _BOOTSTRAP_IDS
        assert "seed-fallback" not in other
        if live_present:
            assert "grok-live-9" not in other
            assert find_cached_model("grok-live-9") is None
        return

    assert expected != ["seed-fallback"]
    if kind in _LIVE_KINDS:
        assert "seed-fallback" not in expected
        if kind == "sdk":
            assert expected == ["grok-sdk"]
            assert catalog_source() == "sdk"
            after = FakeClient.inits
            assert _reread("sdk", with_key=True) == ["grok-sdk"]
            assert _ids(list_models(api_key=FAKE_KEY, sdk_timeout=_TIMEOUT_A)) == ["grok-sdk"]
            assert FakeClient.inits == after
        else:
            assert expected == ["grok-rest-1"]
            assert catalog_source() == "rest"
            assert rest_calls["n"] == 1
            again = list_models(
                api_key=FAKE_KEY,
                sdk_timeout=_TIMEOUT_A,
                base_url=_REST_BASE,
            )
            assert _ids(again) == ["grok-rest-1"]
            assert rest_calls["n"] == 1
        if live_present:
            assert "grok-live-9" not in expected
        return

    if kind in _EXPLICIT_KINDS:
        assert catalog_source() == {
            "persist-explicit": "persist",
            "fixture-explicit": "fixture",
            "inject": "inject",
        }[kind]
        assert _reread(kind, with_key=False) == expected
        other = _ids(list_models(sdk_timeout=_TIMEOUT_B))
        assert other == expected
        assert "seed-fallback" not in other
        if live_present:
            assert "grok-live-9" not in other
        return

    # Fetch fallback. A newer body replaces the seeded sdk deadline fixture.
    assert "seed-fallback" not in expected
    keyed_hold = kind != "persist-fallback"
    after = FakeClient.inits
    assert _reread(kind, with_key=keyed_hold) == expected
    assert FakeClient.inits == after
    if live_present:
        assert "grok-live-9" not in expected
        assert catalog_source() == "sdk"
        assert find_cached_model("grok-live-9") is not None
        marker = "grok-4.7" if expected == _BOOTSTRAP_IDS else expected[0]
        assert find_cached_model(marker) is None
        before = FakeClient.inits
        other = list_models(api_key=FAKE_KEY, sdk_timeout=_TIMEOUT_B)
        assert _ids(other) == ["grok-live-9"]
        assert FakeClient.inits == before
    else:
        source = {
            "persist-fallback": "persist",
            "fixture-fallback": "fixture",
            "sdk-error": "sdk-error",
            "deadline": "sdk-error",
            "deadline-persist": "persist",
            "deadline-fixture": "fixture",
        }[kind]
        assert catalog_source() == source
        before = FakeClient.inits
        other = list_models(api_key=FAKE_KEY, sdk_timeout=_TIMEOUT_B)
        assert FakeClient.inits > before
        if expected != _BOOTSTRAP_IDS:
            assert _ids(other) != expected


def _assert_window(
    kind: str,
    expected: list[str],
    clock: dict[str, float],
    live_present: bool,
) -> None:
    if kind in _LIVE_KINDS or kind in _EXPLICIT_KINDS:
        return
    keyed_hold = kind != "persist-fallback"
    _tick(clock, CATALOG_TIMEOUT_RETRY_SECONDS + 1)
    after = FakeClient.inits
    again = _reread(kind, with_key=keyed_hold)
    if kind in _DEADLINE_KINDS and not live_present:
        assert FakeClient.inits == after + 1
        return
    if kind in _DEADLINE_KINDS and live_present:
        # The short window expired, so the fresher live list is used.
        assert again == ["grok-live-9"]
        assert FakeClient.inits == after
        return
    assert again == expected
    assert FakeClient.inits == after


def _assert_newer_live_clears(kind: str, clock: dict[str, float]) -> None:
    if kind == "inject":
        inject_catalog(None)
    _tick(clock)
    FakeClient.mode = "healthy"
    FakeClient.live_name = "grok-live-10"
    refreshed = list_models(api_key=FAKE_KEY, sdk_timeout=_TIMEOUT_B, force_refresh=True)
    assert _ids(refreshed) == ["grok-live-10"]
    again = list_models(api_key=FAKE_KEY, sdk_timeout=_TIMEOUT_A)
    other = list_models(api_key=FAKE_KEY, sdk_timeout=_TIMEOUT_B)
    assert _ids(again) == ["grok-live-10"]
    assert _ids(other) == ["grok-live-10"]
    assert catalog_source() == "sdk"
    cached = cached_catalog()
    assert cached is not None
    assert _ids(cached) == ["grok-live-10"]
    assert find_cached_model("grok-live-10") is not None
    for marker in (
        "seed-fallback",
        "from-fixture",
        "from-persist",
        "from-inject",
        "grok-sdk",
        "grok-rest-1",
        "grok-live-9",
        "grok-4.7",
        "grok-4.3",
    ):
        assert marker not in _ids(again)
        assert find_cached_model(marker) is None
