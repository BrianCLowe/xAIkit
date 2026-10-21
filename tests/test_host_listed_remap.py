"""CUT-2026-10-21-xk-host-listed-remap.

HR-AC-1 and HR-AC-2. Offline only: the loopback host fixture from
test_regional_endpoint, plus inject_catalog for the default host.
No live call and no API key.

HR-C01..C16 are the behavior cases. HR-C17 is the existing suites.
HR-C18..C21 are diff and offline gates run outside this file.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import socket
from pathlib import Path
from typing import Any

import httpx
import pytest

from xaikit import AsyncXaiClient, RoleUnavailableOnHost, XaiClient
from xaikit.catalog import (
    clear_catalog_cache,
    contract_listed_model_for_need,
    describe_listed_id,
    feature_options,
    fetch_host_catalog_async,
    inject_catalog,
    static_role_for_id,
)
from xaikit.provider import MockChatProvider
from xaikit.types import ModelInfo

KEY = "xai-test-FAKE"
IMAGE_LATEST = "grok-imagine-image-quality-latest"
IMAGE_MARCH = "grok-imagine-image-2026-03-02"
IMAGE_QUALITY_SNAP = "grok-imagine-image-quality-20260403"
VIDEO_STABLE = "grok-imagine-video-1.5-2026-05-30"
VIDEO_PREVIEW = "grok-imagine-video-1.5-preview"
FIVE_IDS = (
    IMAGE_LATEST,
    IMAGE_MARCH,
    IMAGE_QUALITY_SNAP,
    VIDEO_STABLE,
    VIDEO_PREVIEW,
)
QUALITY = "grok-imagine-video"
ONE_FIVE = "grok-imagine-video-1.5"
VIDEO_LATEST = "grok-imagine-video-latest"
CHAT_47 = "grok-4.7"
CHAT_43 = "grok-4.3"
UNKNOWN = "my-fine-tune-x"
_MOCK_EXTENSION_GAP = "Video extension response missing request_id"


def _load_regional_endpoint():
    """Load the existing loopback host helpers without editing that file."""
    path = Path(__file__).resolve().with_name("test_regional_endpoint.py")
    spec = importlib.util.spec_from_file_location(
        "xaikit_hr_host_listed_regional_fixture", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load loopback host fixture from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_regional = _load_regional_endpoint()
_start_host = _regional._start_host
_stop = _regional._stop


def _json_response(method: str, url: str, status_code: int, payload: dict[str, Any]) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request(method, url),
    )


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch):
    """No API key, no injected catalog, and no non-loopback TCP connect."""
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("XAI_MANAGEMENT_KEY", raising=False)
    inject_catalog(None)
    clear_catalog_cache()

    def _host(address: Any) -> str:
        if isinstance(address, tuple) and address:
            return str(address[0])
        return str(address)

    def _check(address: Any) -> None:
        host = _host(address)
        if host in {"127.0.0.1", "::1", "localhost"}:
            return
        raise AssertionError(f"non-loopback connection to {host}")

    orig = socket.socket.connect
    orig_ex = socket.socket.connect_ex

    def connect(self, address):  # type: ignore[no-untyped-def]
        _check(address)
        return orig(self, address)

    def connect_ex(self, address):  # type: ignore[no-untyped-def]
        _check(address)
        return orig_ex(self, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    yield
    inject_catalog(None)
    clear_catalog_cache()


def _client(cls: type, host: dict[str, Any] | None = None, **kwargs: Any) -> Any:
    params: dict[str, Any] = {
        "api_key": KEY,
        "intent": "best",
        "provider": MockChatProvider("ok"),
    }
    if host is not None:
        params["base_url"] = host["base"]
    params.update(kwargs)
    return cls(**params)


def _call(client: Any, name: str, *args: Any, **kwargs: Any) -> Any:
    out = getattr(client, name)(*args, **kwargs)
    if asyncio.iscoroutine(out):
        return asyncio.run(out)
    return out


def _extend(client: Any, **kwargs: Any) -> Any:
    """Extend on the loopback host.

    The shared fixture answers ``/videos/extensions`` with ``{"ok": true}``,
    so a real POST then raises for a missing request_id. That POST is already
    recorded. Any other error propagates.
    """
    try:
        return _call(
            client,
            "extend_video",
            "keep going",
            video_url="https://example.com/clip.mp4",
            into=[],
            wait=False,
            **kwargs,
        )
    except RuntimeError as exc:
        if str(exc) != _MOCK_EXTENSION_GAP:
            raise
        return None


def _row(model: str | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {"messages": [{"role": "user", "content": "hi"}]}
    if model is not None:
        row["model"] = model
    return row


class _BatchCapture:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _sync(operation: str, *, sdk_client: Any = None, **kwargs: Any) -> Any:
            self.calls.append({"operation": operation, **kwargs})
            return {"id": kwargs.get("batch_id", "batch_1")}

        async def _async(operation: str, *, sdk_client: Any = None, **kwargs: Any) -> Any:
            self.calls.append({"operation": operation, **kwargs})
            return {"id": kwargs.get("batch_id", "batch_1")}

        monkeypatch.setattr("xaikit.client.call_batch_rpc", _sync)
        monkeypatch.setattr("xaikit.async_client.call_batch_rpc_async", _async)

    def models(self) -> list[str]:
        found: list[str] = []
        for call in self.calls:
            for req in call.get("requests") or []:
                found.append(str(req.get("model")))
        return found


def _open(ids: tuple[str, ...] | list[str]) -> dict[str, Any]:
    return _start_host(list(ids))


def _posts(records: list[dict[str, Any]], suffix: str | None = None) -> list[dict[str, Any]]:
    found = []
    for row in records:
        if row["method"] != "POST":
            continue
        if suffix is not None and not str(row["path"]).endswith(suffix):
            continue
        found.append(row)
    return found


def _posted_models(records: list[dict[str, Any]], suffix: str | None = None) -> list[str]:
    found: list[str] = []
    for row in _posts(records, suffix):
        payload = json.loads(row["body"].decode() or "{}")
        found.append(str(payload.get("model")))
    return found


def _assert_role(err: RoleUnavailableOnHost, role: str, host: dict[str, Any]) -> None:
    assert err.role == role
    assert err.host == host["host"]
    assert role in str(err)
    assert host["host"] in str(err)


def _assert_no_post(host: dict[str, Any]) -> None:
    assert _posts(host["records"]) == []
    assert _posts(host["records"], "/videos/extensions") == []
    assert "grok-imagine-video" not in _posted_models(host["records"])
    assert any(
        row["method"] == "GET" and str(row["path"]).endswith("/models")
        for row in host["records"]
    )


def _assert_extension(host: dict[str, Any], model: str) -> None:
    models = _posted_models(host["records"], "/videos/extensions")
    assert models == [model]
    assert _posted_models(host["records"]) == [model]


def _add(client: Any, requests: list[dict[str, Any]]) -> Any:
    return _call(client, "add_batch_requests", "batch_1", requests)


def _default_rows() -> list[ModelInfo]:
    return [
        ModelInfo(id=CHAT_47, capabilities=["chat"], created=3),
        ModelInfo(id=CHAT_43, capabilities=["chat"], created=1),
        ModelInfo(id=QUALITY, capabilities=["video"], created=1),
        ModelInfo(id=ONE_FIVE, capabilities=["video"], created=2),
    ]


def _capture_default_posts(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    posts: list[dict[str, Any]] = []

    def _post(url: str, **kwargs: Any) -> httpx.Response:
        posts.append({"url": url, "json": kwargs.get("json")})
        return _json_response("POST", url, 200, {"request_id": "req-ext"})

    async def _request(self: Any, method: str, url: str, **kwargs: Any) -> httpx.Response:
        posts.append({"url": url, "json": kwargs.get("json"), "method": method})
        return _json_response(method, url, 200, {"request_id": "req-ext"})

    monkeypatch.setattr("xaikit.client.httpx.post", _post)
    monkeypatch.setattr(httpx.AsyncClient, "request", _request)
    return posts


def test_hr_listed_contract_stays_inside_static_role_and_features() -> None:
    """Catalog rule behind HR-C01, HR-C05, HR-C07, and HR-C12.

    No qualifying listed id returns None. It does not bootstrap to
    grok-imagine-video or grok-4.3. grok-imagine-video-latest has extend
    and a chat static role, so it is not a video candidate.
    """
    assert static_role_for_id(VIDEO_LATEST) == "chat"
    assert "video_extend" in feature_options(VIDEO_LATEST)
    assert "video_extend" not in feature_options(VIDEO_STABLE)
    assert "batch" not in feature_options(CHAT_47)
    assert feature_options(CHAT_43) == ["batch"]

    five = [describe_listed_id(mid)[0] for mid in FIVE_IDS]
    assert (
        contract_listed_model_for_need(None, "video_extend", role="video", catalog=five)
        is None
    )
    assert (
        contract_listed_model_for_need(
            VIDEO_STABLE, "video_extend", role="video", catalog=five
        )
        is None
    )

    latest_pool = [
        describe_listed_id(ONE_FIVE)[0],
        describe_listed_id(VIDEO_LATEST)[0],
    ]
    assert (
        contract_listed_model_for_need(
            ONE_FIVE, "video_extend", role="video", catalog=latest_pool
        )
        is None
    )

    only_47 = [describe_listed_id(CHAT_47)[0]]
    assert (
        contract_listed_model_for_need(CHAT_47, "batch", role="chat", catalog=only_47)
        is None
    )
    assert (
        contract_listed_model_for_need(None, "batch", role="chat", catalog=only_47)
        is None
    )
    assert (
        contract_listed_model_for_need(UNKNOWN, "batch", role="chat", catalog=only_47)
        == UNKNOWN
    )

    both = [describe_listed_id(CHAT_47)[0], describe_listed_id(CHAT_43)[0]]
    assert (
        contract_listed_model_for_need(CHAT_47, "batch", role="chat", catalog=both)
        == CHAT_43
    )
    quality_pool = [describe_listed_id(QUALITY)[0], describe_listed_id(ONE_FIVE)[0]]
    assert (
        contract_listed_model_for_need(None, "video_extend", role="video", catalog=quality_pool)
        == QUALITY
    )


def _unpinned_extend_raises(cls: type) -> None:
    host = _open(FIVE_IDS)
    try:
        client = _client(cls, host)
        with pytest.raises(RoleUnavailableOnHost) as caught:
            _extend(client)
        _assert_role(caught.value, "video", host)
        _assert_no_post(host)
    finally:
        _stop(host)


def test_hr_c01_five_id_extend_unpinned_raises() -> None:
    _unpinned_extend_raises(XaiClient)


def test_hr_c02_five_id_extend_unpinned_raises_async() -> None:
    _unpinned_extend_raises(AsyncXaiClient)


@pytest.mark.parametrize("cls", [XaiClient, AsyncXaiClient])
def test_hr_c03_pinned_15_snapshot_raises(cls: type) -> None:
    host = _open(FIVE_IDS)
    try:
        client = _client(cls, host)
        with pytest.raises(RoleUnavailableOnHost) as caught:
            _extend(client, model=VIDEO_STABLE)
        _assert_role(caught.value, "video", host)
        _assert_no_post(host)
    finally:
        _stop(host)


def _quality_extend_posts_quality(cls: type) -> None:
    host = _open((QUALITY, ONE_FIVE))
    try:
        client = _client(cls, host)
        _extend(client)
        _assert_extension(host, QUALITY)
    finally:
        _stop(host)


def test_hr_c04_listed_quality_posts_quality() -> None:
    _quality_extend_posts_quality(XaiClient)


def _latest_alias_raises(cls: type) -> None:
    host = _open((ONE_FIVE, VIDEO_LATEST))
    try:
        client = _client(cls, host)
        with pytest.raises(RoleUnavailableOnHost) as caught:
            _extend(client)
        _assert_role(caught.value, "video", host)
        _assert_no_post(host)
    finally:
        _stop(host)


def test_hr_c05_latest_alias_excluded_from_video_pool_raises() -> None:
    _latest_alias_raises(XaiClient)


def test_hr_c06_quality_post_and_latest_alias_raise_async() -> None:
    _quality_extend_posts_quality(AsyncXaiClient)
    _latest_alias_raises(AsyncXaiClient)


def _batch_omitted_raises(cls: type, monkeypatch: pytest.MonkeyPatch) -> None:
    capture = _BatchCapture()
    capture.install(monkeypatch)
    host = _open((CHAT_47,))
    try:
        client = _client(cls, host)
        with pytest.raises(RoleUnavailableOnHost) as caught:
            _add(client, [_row()])
        _assert_role(caught.value, "chat", host)
        assert capture.calls == []
        assert CHAT_43 not in capture.models()
        _assert_no_post(host)
    finally:
        _stop(host)


def test_hr_c07_batch_omitted_on_47_only_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _batch_omitted_raises(XaiClient, monkeypatch)


def _batch_row_47_raises(cls: type, monkeypatch: pytest.MonkeyPatch) -> None:
    capture = _BatchCapture()
    capture.install(monkeypatch)
    host = _open((CHAT_47,))
    try:
        client = _client(cls, host)
        with pytest.raises(RoleUnavailableOnHost) as caught:
            _add(client, [_row(CHAT_47)])
        _assert_role(caught.value, "chat", host)
        assert capture.calls == []
        assert capture.models() == []
        _assert_no_post(host)
    finally:
        _stop(host)


def test_hr_c08_batch_row_47_on_47_only_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _batch_row_47_raises(XaiClient, monkeypatch)


def test_hr_c09_batch_omitted_and_row_47_raise_async(monkeypatch: pytest.MonkeyPatch) -> None:
    _batch_omitted_raises(AsyncXaiClient, monkeypatch)
    _batch_row_47_raises(AsyncXaiClient, monkeypatch)


@pytest.mark.parametrize("cls", [XaiClient, AsyncXaiClient])
def test_hr_c10_row_47_remaps_to_listed_43(
    cls: type, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = _BatchCapture()
    capture.install(monkeypatch)
    host = _open((CHAT_47, CHAT_43))
    try:
        client = _client(cls, host)
        _add(client, [_row(CHAT_47)])
        assert capture.models() == [CHAT_43]
        assert len(capture.calls) == 1
        assert capture.calls[0]["operation"] == "add"
    finally:
        _stop(host)


@pytest.mark.parametrize("cls", [XaiClient, AsyncXaiClient])
def test_hr_c11_omitted_row_on_43_only_stays_43(
    cls: type, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = _BatchCapture()
    capture.install(monkeypatch)
    host = _open((CHAT_43,))
    try:
        client = _client(cls, host)
        _add(client, [_row()])
        assert capture.models() == [CHAT_43]
    finally:
        _stop(host)


@pytest.mark.parametrize("cls", [XaiClient, AsyncXaiClient])
def test_hr_c12_unknown_pin_stays_on_any_host(
    cls: type, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = _BatchCapture()
    capture.install(monkeypatch)

    inject_catalog(_default_rows())
    plain = _client(cls, model=CHAT_47)
    _add(plain, [_row(UNKNOWN)])
    assert capture.models() == [UNKNOWN]
    capture.calls.clear()

    host = _open((CHAT_47,))
    try:
        regional = _client(cls, host, model=CHAT_47)
        _add(regional, [_row(UNKNOWN)])
        assert capture.models() == [UNKNOWN]
        assert CHAT_43 not in capture.models()
    finally:
        _stop(host)


@pytest.mark.parametrize("cls", [XaiClient, AsyncXaiClient])
def test_hr_c13_default_host_keeps_static_remap(
    cls: type, monkeypatch: pytest.MonkeyPatch
) -> None:
    posts = _capture_default_posts(monkeypatch)
    capture = _BatchCapture()
    capture.install(monkeypatch)
    inject_catalog(_default_rows())
    client = _client(cls, model=CHAT_47)
    assert client.base_url.endswith("api.x.ai/v1")
    _extend(client)
    assert [row["json"]["model"] for row in posts] == [QUALITY]
    _add(client, [_row()])
    _add(client, [_row(CHAT_47)])
    assert capture.models() == [CHAT_43, CHAT_43]


@pytest.mark.parametrize("cls", [XaiClient, AsyncXaiClient])
def test_hr_c14_pinned_quality_posts_unchanged(cls: type) -> None:
    host = _open((QUALITY, ONE_FIVE))
    try:
        client = _client(cls, host)
        _extend(client, model=QUALITY)
        _assert_extension(host, QUALITY)
    finally:
        _stop(host)


@pytest.mark.parametrize("cls", [XaiClient, AsyncXaiClient])
def test_hr_c15_pinned_43_stays_43(cls: type, monkeypatch: pytest.MonkeyPatch) -> None:
    capture = _BatchCapture()
    capture.install(monkeypatch)
    host = _open((CHAT_47, CHAT_43))
    try:
        client = _client(cls, host)
        _add(client, [_row(CHAT_43)])
        assert capture.models() == [CHAT_43]
    finally:
        _stop(host)


@pytest.mark.parametrize("cls", [XaiClient, AsyncXaiClient])
def test_hr_c16_posted_models_are_ids_the_host_lists(
    cls: type, monkeypatch: pytest.MonkeyPatch
) -> None:
    extend_ids = (QUALITY, ONE_FIVE)
    host = _open(extend_ids)
    try:
        client = _client(cls, host)
        _extend(client)
        posted = _posted_models(host["records"])
        assert posted
        assert set(posted) <= set(extend_ids)
    finally:
        _stop(host)

    capture = _BatchCapture()
    capture.install(monkeypatch)
    batch_ids = (CHAT_47, CHAT_43)
    batch_host = _open(batch_ids)
    try:
        client = _client(cls, batch_host)
        _add(client, [_row(CHAT_47)])
        assert capture.models()
        assert set(capture.models()) <= set(batch_ids)
        http_models = _posted_models(batch_host["records"])
        assert set(http_models) <= set(batch_ids)
    finally:
        _stop(batch_host)


def test_hr_async_remap_loads_host_list_without_sync_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Async extend and batch repair preload the host list.

    Unpinned extend, a per-call pin, a client video pin, omitted batch
    repair, and a batch row pin all use the async fetch. The sync host
    list fetch is not called.
    """
    sync_calls: list[str] = []
    async_calls: list[str] = []

    def _sync_fetch(*args: Any, **kwargs: Any) -> Any:
        sync_calls.append("sync")
        raise AssertionError("sync host-list fetch on AsyncXaiClient")

    async def _async_fetch(*args: Any, **kwargs: Any) -> Any:
        async_calls.append("async")
        return await fetch_host_catalog_async(*args, **kwargs)

    monkeypatch.setattr("xaikit.client.fetch_host_catalog", _sync_fetch)
    monkeypatch.setattr("xaikit.async_client.fetch_host_catalog_async", _async_fetch)
    capture = _BatchCapture()
    capture.install(monkeypatch)

    def _no_sync() -> None:
        assert sync_calls == []

    five = _open(FIVE_IDS)
    try:
        unpinned = _client(AsyncXaiClient, five)
        with pytest.raises(RoleUnavailableOnHost) as unpinned_err:
            _extend(unpinned)
        assert unpinned_err.value.role == "video"
        _no_sync()

        per_call = _client(AsyncXaiClient, five)
        with pytest.raises(RoleUnavailableOnHost) as per_call_err:
            _extend(per_call, model=VIDEO_STABLE)
        assert per_call_err.value.role == "video"
        _no_sync()

        client_pin = _client(AsyncXaiClient, five, video_model=VIDEO_STABLE)
        with pytest.raises(RoleUnavailableOnHost) as client_pin_err:
            _extend(client_pin)
        assert client_pin_err.value.role == "video"
        _no_sync()
    finally:
        _stop(five)

    only_47 = _open((CHAT_47,))
    try:
        omitted = _client(AsyncXaiClient, only_47)
        with pytest.raises(RoleUnavailableOnHost) as omitted_err:
            _add(omitted, [_row()])
        assert omitted_err.value.role == "chat"
        _no_sync()

        row_pin = _client(AsyncXaiClient, only_47, model=CHAT_47)
        with pytest.raises(RoleUnavailableOnHost) as row_err:
            _add(row_pin, [_row(CHAT_47)])
        assert row_err.value.role == "chat"
        assert capture.calls == []
        _no_sync()
    finally:
        _stop(only_47)

    both = _open((CHAT_47, CHAT_43))
    try:
        repair = _client(AsyncXaiClient, both, model=CHAT_47)
        _add(repair, [_row()])
        _add(repair, [_row(CHAT_47)])
        assert capture.models() == [CHAT_43, CHAT_43]
        _no_sync()
    finally:
        _stop(both)

    assert async_calls == ["async"] * 6
    assert sync_calls == []
