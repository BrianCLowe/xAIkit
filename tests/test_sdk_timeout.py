"""CUT-2026-10-14-xk-sdk-timeout.

Graded cases XK-TO-1 (TO1-1..TO1-10), XK-TO-2 (TO2-1..TO2-7), and XK-TO-3 (TO3-1..TO3-7).
Stall cases use a local insecure gRPC server. No live key and no api.x.ai.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import time
from concurrent import futures
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import grpc
import pytest

from xaikit import (
    AsyncXaiClient,
    MockChatProvider,
    XaiClient,
    XaiTimeoutError,
    default_retry_policy,
)
from xaikit.catalog import (
    BOOTSTRAP_MODEL,
    CATALOG_TIMEOUT_RETRY_SECONDS,
    cached_catalog,
    catalog_source,
    clear_catalog_cache,
    fetch_models_from_sdk,
    inject_catalog,
    list_models,
)
from xaikit.client import (
    _DEFERRED_CHAT_TIMEOUT,
    _EMBED_TIMEOUT,
    _FILES_TIMEOUT,
    _REALTIME_CLIENT_SECRETS_TIMEOUT,
    _REALTIME_CLOSE_TIMEOUT,
    _REALTIME_OPEN_TIMEOUT,
    _RESPONSES_TIMEOUT,
    _TOKENIZE_TIMEOUT,
    _TTS_VOICES_TIMEOUT,
    _VIDEO_DOWNLOAD_TIMEOUT,
    _VIDEO_POLL_TIMEOUT,
    _VIDEO_START_TIMEOUT,
    _VIDEO_WAIT_TIMEOUT,
)
from xaikit.errors import SDK_TIMEOUT_ENV
from xaikit.retry import RetryPolicy
from xaikit.types import ModelInfo
from xai_sdk.proto import batch_pb2_grpc, chat_pb2_grpc

FAKE_KEY = "xai-fake"
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "xaikit"
_STALL_SECONDS = 8.0

_BASE_INIT_PARAMS = [
    "self",
    "api_key",
    "model",
    "thought_level",
    "effort",
    "intent",
    "task",
    "usage_meter",
    "provider",
    "retry_policy",
    "credential_store",
    "subject",
    "image_model",
    "video_model",
    "voice_model",
    "bootstrap_model",
    "completion_tracer",
    "base_url",
]


@pytest.fixture(autouse=True)
def _offline_sdk_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "XAI_API_KEY",
        "XAI_MANAGEMENT_KEY",
        "XAI_BASE_URL",
        SDK_TIMEOUT_ENV,
        "XAITKIT_LIVE",
    ):
        monkeypatch.delenv(name, raising=False)
    inject_catalog(None)
    clear_catalog_cache()
    yield
    inject_catalog(None)
    clear_catalog_cache()


def _pins() -> dict[str, str]:
    return {
        "model": "grok-4.7",
        "image_model": "grok-imagine-image",
        "video_model": "grok-imagine-video-1.5",
        "voice_model": "grok-voice-latest",
    }


def _single_try() -> RetryPolicy:
    return RetryPolicy(max_attempts=1, backoff_seconds=0.0)


def _reply() -> SimpleNamespace:
    return SimpleNamespace(
        content="ok",
        reasoning_content="",
        finish_reason="stop",
        tool_calls=None,
        usage=None,
        service_tier=None,
    )


class _Status:
    def __init__(self, name: str) -> None:
        self.name = name

    def __str__(self) -> str:
        return f"StatusCode.{self.name}"


class _FakeRpcError(Exception):
    def __init__(self, name: str, details: str) -> None:
        super().__init__(details)
        self._name = name

    def code(self) -> _Status:
        return _Status(self._name)


class _CaptureClient:
    """Stand-in for xai_sdk Client / AsyncClient. Records constructor kwargs."""

    built: list[dict[str, Any]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self._async_api = bool(kwargs.pop("_async_api", False))
        self.kwargs = dict(kwargs)
        self.calls: list[str] = []
        self.creates: list[dict[str, Any]] = []
        type(self).built.append(self.kwargs)
        self.chat = self
        self.batch = self
        self.collections = self
        self.models = self

    def close(self) -> None:
        return None

    def create(self, **kwargs: Any) -> _CaptureClient:
        self.creates.append(dict(kwargs))
        return self

    def sample(self) -> Any:
        self.calls.append("sample")
        if self._raise is not None:
            raise self._raise
        response = _reply()
        if self._async_api:

            async def _go() -> SimpleNamespace:
                return response

            return _go()
        return response

    def stream(self) -> Any:
        self.calls.append("stream")
        response = _reply()
        chunk = SimpleNamespace(
            content="ok",
            reasoning_content="",
            tool_calls=None,
            usage=None,
        )
        if self._async_api:

            async def _agen() -> Any:
                yield response, chunk

            return _agen()

        def _gen() -> Any:
            yield response, chunk

        return _gen()

    def get(self, batch_id: str) -> dict[str, str]:
        self.calls.append("batch.get")
        return {"id": batch_id, "name": "job"}

    def upload_document(
        self,
        collection_id: str,
        name: str,
        data: bytes,
        fields: dict[str, str] | None = None,
    ) -> dict[str, str]:
        self.calls.append("upload_document")
        del collection_id, data, fields
        return {"id": "doc-1", "name": name}

    def list_language_models(self) -> list[object]:
        self.calls.append("list_language_models")
        return []

    def list_image_generation_models(self) -> list[object]:
        self.calls.append("list_image_generation_models")
        return []

    _raise: BaseException | None = None


def _install_capture(monkeypatch: pytest.MonkeyPatch, *, fail: BaseException | None = None) -> None:
    _CaptureClient.built = []
    _CaptureClient._raise = fail

    def sync_factory(*args: Any, **kwargs: Any) -> _CaptureClient:
        return _CaptureClient(*args, **kwargs)

    def async_factory(*args: Any, **kwargs: Any) -> _CaptureClient:
        kwargs["_async_api"] = True
        return _CaptureClient(*args, **kwargs)

    monkeypatch.setattr("xaikit.client.Client", sync_factory)
    monkeypatch.setattr("xaikit.async_client.AsyncClient", async_factory)
    monkeypatch.setattr("xai_sdk.Client", sync_factory)


def _without_timeout(kwargs: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in kwargs.items() if key != "timeout"}


def _assert_timeout(kwargs: dict[str, Any], expected: float) -> None:
    assert kwargs.get("timeout") == expected
    assert isinstance(kwargs["timeout"], float)
    assert kwargs["timeout"] != 0
    assert kwargs["timeout"] is not None


def _close_sync(client: XaiClient) -> None:
    closed: set[int] = set()
    for sdk in (getattr(client, "_chat_sdk", None), client._client):
        if sdk is None or id(sdk) in closed:
            continue
        closed.add(id(sdk))
        closer = getattr(sdk, "close", None)
        if callable(closer):
            closer()


class _StallChat(chat_pb2_grpc.ChatServicer):
    def GetCompletion(self, request: Any, context: grpc.ServicerContext) -> None:
        del request
        _stall(context)
        context.abort(grpc.StatusCode.DEADLINE_EXCEEDED, "Deadline Exceeded")

    def GetCompletionChunk(self, request: Any, context: grpc.ServicerContext) -> Any:
        del request
        _stall(context)
        context.abort(grpc.StatusCode.DEADLINE_EXCEEDED, "Deadline Exceeded")
        if False:
            yield None


class _StallBatch(batch_pb2_grpc.BatchMgmtServicer):
    def GetBatch(self, request: Any, context: grpc.ServicerContext) -> None:
        del request
        _stall(context)
        context.abort(grpc.StatusCode.DEADLINE_EXCEEDED, "Deadline Exceeded")


def _stall(context: grpc.ServicerContext) -> None:
    deadline = time.monotonic() + _STALL_SECONDS
    while time.monotonic() < deadline:
        if not context.is_active():
            return
        time.sleep(0.02)
    context.abort(grpc.StatusCode.DEADLINE_EXCEEDED, "Deadline Exceeded")


@pytest.fixture(scope="module")
def stall_port() -> Any:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    chat_pb2_grpc.add_ChatServicer_to_server(_StallChat(), server)
    batch_pb2_grpc.add_BatchMgmtServicer_to_server(_StallBatch(), server)
    port = server.add_insecure_port("127.0.0.1:0")
    assert port
    server.start()
    try:
        yield port
    finally:
        server.stop(0)


def _point_shared_client_at_stall(monkeypatch: pytest.MonkeyPatch, host: str) -> None:
    """Batch stays on the SDK default host. This test redirect keeps that call local."""
    import xaikit.async_client as async_mod
    import xaikit.client as sync_mod

    def _wrap(real: Any) -> Any:
        def factory(*args: Any, **kwargs: Any) -> Any:
            kwargs.setdefault("api_host", host)
            kwargs.setdefault("use_insecure_channel", True)
            return real(*args, **kwargs)

        return factory

    monkeypatch.setattr(sync_mod, "Client", _wrap(sync_mod.Client))
    monkeypatch.setattr(async_mod, "AsyncClient", _wrap(async_mod.AsyncClient))

    class _CatalogBomb:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            del args, kwargs
            raise AssertionError("stall test reached the catalog SDK client")

    monkeypatch.setattr("xai_sdk.Client", _CatalogBomb)
    inject_catalog(
        [ModelInfo(id="grok-4.7", capabilities=["chat", "image", "video", "voice"])]
    )
    clear_catalog_cache()


def _stall_client(port: int, **kwargs: Any) -> XaiClient:
    kwargs.setdefault("timeout", 1.0)
    kwargs.setdefault("retry_policy", _single_try())
    return XaiClient(
        api_key=FAKE_KEY,
        base_url=f"http://127.0.0.1:{port}",
        **_pins(),
        **kwargs,
    )


def _expect_timeout(call: Any, *, seconds: float) -> BaseException:
    started = time.monotonic()
    with pytest.raises(XaiTimeoutError) as caught:
        call()
    elapsed = time.monotonic() - started
    assert elapsed <= seconds + 2.0
    err = caught.value
    assert isinstance(err, XaiTimeoutError)
    assert isinstance(err, TimeoutError)
    assert not isinstance(err, RuntimeError)
    assert type(err).__name__ != "RpcError"
    return err


# --- XK-TO-1 ---


def test_to1_1_sync_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_capture(monkeypatch)
    client = XaiClient(api_key=FAKE_KEY, **_pins())
    assert len(_CaptureClient.built) == 1
    _assert_timeout(_CaptureClient.built[0], 180.0)
    assert client._sdk_timeout == 180.0


def test_to1_2_async_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_capture(monkeypatch)
    AsyncXaiClient(api_key=FAKE_KEY, **_pins())
    assert len(_CaptureClient.built) == 1
    _assert_timeout(_CaptureClient.built[0], 180.0)


@pytest.mark.parametrize(
    "base_url",
    ["http://127.0.0.1:9", "https://example.com/v1"],
)
def test_to1_3_sync_regional(monkeypatch: pytest.MonkeyPatch, base_url: str) -> None:
    _install_capture(monkeypatch)
    XaiClient(api_key=FAKE_KEY, base_url=base_url, timeout=180.0, **_pins())
    assert len(_CaptureClient.built) == 2
    for kwargs in _CaptureClient.built:
        _assert_timeout(kwargs, 180.0)
    assert _CaptureClient.built[0]["timeout"] == _CaptureClient.built[1]["timeout"]


@pytest.mark.parametrize(
    "base_url",
    ["http://127.0.0.1:9", "https://example.com/v1"],
)
def test_to1_4_async_regional(monkeypatch: pytest.MonkeyPatch, base_url: str) -> None:
    _install_capture(monkeypatch)
    AsyncXaiClient(api_key=FAKE_KEY, base_url=base_url, **_pins())
    assert len(_CaptureClient.built) == 2
    for kwargs in _CaptureClient.built:
        _assert_timeout(kwargs, 180.0)


def test_to1_5_catalog_default_and_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_capture(monkeypatch)
    monkeypatch.setenv(SDK_TIMEOUT_ENV, "30")
    fetch_models_from_sdk(FAKE_KEY)
    _assert_timeout(_CaptureClient.built[-1], 30.0)
    fetch_models_from_sdk(FAKE_KEY, timeout=2.5)
    _assert_timeout(_CaptureClient.built[-1], 2.5)


def test_to1_6_constructor_and_env_reach_every_site(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_capture(monkeypatch)
    monkeypatch.setenv(SDK_TIMEOUT_ENV, "90")
    XaiClient(api_key=FAKE_KEY, timeout=30)
    sync_sites = list(_CaptureClient.built)
    assert sync_sites
    for kwargs in sync_sites:
        _assert_timeout(kwargs, 30.0)

    _CaptureClient.built = []
    AsyncXaiClient(api_key=FAKE_KEY, timeout=30)
    assert _CaptureClient.built
    for kwargs in _CaptureClient.built:
        _assert_timeout(kwargs, 30.0)

    _CaptureClient.built = []
    XaiClient(api_key=FAKE_KEY, base_url="https://example.com/v1", timeout=30, **_pins())
    assert len(_CaptureClient.built) >= 2
    for kwargs in _CaptureClient.built:
        _assert_timeout(kwargs, 30.0)

    _CaptureClient.built = []
    AsyncXaiClient(api_key=FAKE_KEY, base_url="http://127.0.0.1:9", timeout=30, **_pins())
    assert len(_CaptureClient.built) >= 2
    for kwargs in _CaptureClient.built:
        _assert_timeout(kwargs, 30.0)

    clear_catalog_cache()
    _CaptureClient.built = []
    XaiClient(api_key=FAKE_KEY, timeout=30)
    assert any(row.get("timeout") == 30.0 for row in _CaptureClient.built)
    fetch_models_from_sdk(FAKE_KEY, timeout=30)
    _assert_timeout(_CaptureClient.built[-1], 30.0)


def test_to1_6_env_without_constructor(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_capture(monkeypatch)
    monkeypatch.setenv(SDK_TIMEOUT_ENV, "30")
    XaiClient(api_key=FAKE_KEY, **_pins())
    AsyncXaiClient(api_key=FAKE_KEY, **_pins())
    assert len(_CaptureClient.built) == 2
    for kwargs in _CaptureClient.built:
        _assert_timeout(kwargs, 30.0)


def test_to1_7_unit_is_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_capture(monkeypatch)
    XaiClient(api_key=FAKE_KEY, timeout=2.5, **_pins())
    AsyncXaiClient(api_key=FAKE_KEY, timeout=2.5, **_pins())
    assert len(_CaptureClient.built) == 2
    for kwargs in _CaptureClient.built:
        assert kwargs["timeout"] == 2.5
        assert kwargs["timeout"] != 2500
        assert kwargs["timeout"] != pytest.approx(2.5 / 60)


def test_to1_8_every_rpc_rides_a_timed_client(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_capture(monkeypatch)
    sync = XaiClient(api_key=FAKE_KEY, timeout=30, retry_policy=_single_try(), **_pins())
    sync_client = sync._client
    sync.chat([{"role": "user", "content": "hi"}])
    list(sync.chat_stream([{"role": "user", "content": "hi"}]))
    sync.get_batch("batch-1")
    sync.upload_document("col-1", "note.txt", b"hello")
    assert "sample" in sync_client.calls
    assert "stream" in sync_client.calls
    assert "batch.get" in sync_client.calls
    assert "upload_document" in sync_client.calls
    _assert_timeout(sync_client.kwargs, 30.0)

    async def _async_ops() -> None:
        client = AsyncXaiClient(
            api_key=FAKE_KEY,
            timeout=30,
            retry_policy=_single_try(),
            **_pins(),
        )
        sdk = client._client
        await client.chat([{"role": "user", "content": "hi"}])
        async for _chunk in client.chat_stream([{"role": "user", "content": "hi"}]):
            del _chunk
        await client.get_batch("batch-1")
        await client.upload_document("col-1", "note.txt", b"hello")
        assert "sample" in sdk.calls
        assert "stream" in sdk.calls
        assert "batch.get" in sdk.calls
        assert "upload_document" in sdk.calls
        _assert_timeout(sdk.kwargs, 30.0)

    asyncio.run(_async_ops())

    before = len(_CaptureClient.built)
    fetch_models_from_sdk(FAKE_KEY, timeout=30)
    catalog_kwargs = _CaptureClient.built[-1]
    _assert_timeout(catalog_kwargs, 30.0)
    assert len(_CaptureClient.built) == before + 1
    _assert_static_timeout_keywords()


def _assert_static_timeout_keywords() -> None:
    missing: list[str] = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        sdk_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "xai_sdk":
                for alias in node.names:
                    if alias.name in {"Client", "AsyncClient"}:
                        sdk_names.add(alias.asname or alias.name)
        if not sdk_names:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id not in sdk_names:
                continue
            if not any(kw.arg == "timeout" for kw in node.keywords):
                missing.append(f"{path.name}:{node.lineno}")
    assert missing == []


def test_to1_8_static_check() -> None:
    _assert_static_timeout_keywords()


@pytest.mark.parametrize("bad", [0, 0.0, -1, -0.01])
def test_to1_9_zero_and_negative_raise(monkeypatch: pytest.MonkeyPatch, bad: float) -> None:
    _install_capture(monkeypatch)
    with pytest.raises(ValueError):
        XaiClient(api_key=FAKE_KEY, timeout=bad, **_pins())
    with pytest.raises(ValueError):
        AsyncXaiClient(api_key=FAKE_KEY, timeout=bad, **_pins())
    assert _CaptureClient.built == []


def test_to1_9_none_is_default_not_sdk_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_capture(monkeypatch)
    XaiClient(api_key=FAKE_KEY, timeout=None, **_pins())
    AsyncXaiClient(api_key=FAKE_KEY, timeout=None, **_pins())
    assert len(_CaptureClient.built) == 2
    for kwargs in _CaptureClient.built:
        _assert_timeout(kwargs, 180.0)


def test_to1_9_env_zero_and_negative(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_capture(monkeypatch)
    for raw in ("0", "-1", "0.0"):
        monkeypatch.setenv(SDK_TIMEOUT_ENV, raw)
        with pytest.raises(ValueError):
            XaiClient(api_key=FAKE_KEY, **_pins())
        assert _CaptureClient.built == []


def test_to1_10_rest_timeouts_unchanged() -> None:
    assert _DEFERRED_CHAT_TIMEOUT == 120.0
    assert _FILES_TIMEOUT == 120.0
    assert _EMBED_TIMEOUT == 120.0
    assert _TOKENIZE_TIMEOUT == 60.0
    assert _RESPONSES_TIMEOUT == 120.0
    assert _VIDEO_START_TIMEOUT == 60.0
    assert _VIDEO_POLL_TIMEOUT == 60.0
    assert _VIDEO_DOWNLOAD_TIMEOUT == 120.0
    assert _VIDEO_WAIT_TIMEOUT == 600.0
    assert _TTS_VOICES_TIMEOUT == 30.0
    assert _REALTIME_OPEN_TIMEOUT == 30.0
    assert _REALTIME_CLOSE_TIMEOUT == 10.0
    assert _REALTIME_CLIENT_SECRETS_TIMEOUT == 30.0


# --- XK-TO-2 ---


def test_to2_1_sync_sample_stall(monkeypatch: pytest.MonkeyPatch, stall_port: int) -> None:
    _point_shared_client_at_stall(monkeypatch, f"127.0.0.1:{stall_port}")
    client = _stall_client(stall_port, timeout=1.0)
    try:
        _expect_timeout(
            lambda: client.chat([{"role": "user", "content": "hi"}]),
            seconds=1.0,
        )
    finally:
        _close_sync(client)


def test_to2_2_sync_stream_stall(monkeypatch: pytest.MonkeyPatch, stall_port: int) -> None:
    _point_shared_client_at_stall(monkeypatch, f"127.0.0.1:{stall_port}")
    client = _stall_client(stall_port, timeout=1.0)

    def _read() -> None:
        for _chunk in client.chat_stream([{"role": "user", "content": "hi"}]):
            del _chunk

    try:
        _expect_timeout(_read, seconds=1.0)
    finally:
        _close_sync(client)


def test_to2_3_async_sample_stall(monkeypatch: pytest.MonkeyPatch, stall_port: int) -> None:
    _point_shared_client_at_stall(monkeypatch, f"127.0.0.1:{stall_port}")

    async def _go() -> None:
        client = AsyncXaiClient(
            api_key=FAKE_KEY,
            base_url=f"http://127.0.0.1:{stall_port}",
            timeout=1.0,
            retry_policy=_single_try(),
            **_pins(),
        )
        started = time.monotonic()
        try:
            with pytest.raises(XaiTimeoutError) as caught:
                await client.chat([{"role": "user", "content": "hi"}])
            elapsed = time.monotonic() - started
            assert elapsed <= 1.0 + 2.0
            assert isinstance(caught.value, XaiTimeoutError)
            assert isinstance(caught.value, TimeoutError)
        finally:
            await client.aclose()

    asyncio.run(_go())


def test_to2_4_async_stream_stall(monkeypatch: pytest.MonkeyPatch, stall_port: int) -> None:
    _point_shared_client_at_stall(monkeypatch, f"127.0.0.1:{stall_port}")

    async def _go() -> None:
        client = AsyncXaiClient(
            api_key=FAKE_KEY,
            base_url=f"http://127.0.0.1:{stall_port}",
            timeout=1.0,
            retry_policy=_single_try(),
            **_pins(),
        )
        started = time.monotonic()
        try:
            with pytest.raises(XaiTimeoutError) as caught:
                async for _chunk in client.chat_stream([{"role": "user", "content": "hi"}]):
                    del _chunk
            elapsed = time.monotonic() - started
            assert elapsed <= 1.0 + 2.0
            assert isinstance(caught.value, XaiTimeoutError)
            assert not isinstance(caught.value, RuntimeError)
        finally:
            await client.aclose()

    asyncio.run(_go())


def test_to2_5_typed_error_export_and_stall(
    monkeypatch: pytest.MonkeyPatch, stall_port: int
) -> None:
    assert issubclass(XaiTimeoutError, TimeoutError)
    from xaikit import XaiTimeoutError as exported

    assert exported is XaiTimeoutError
    _point_shared_client_at_stall(monkeypatch, f"127.0.0.1:{stall_port}")
    client = _stall_client(stall_port, timeout=1.0)
    try:
        err = _expect_timeout(
            lambda: client.chat([{"role": "user", "content": "hi"}]),
            seconds=1.0,
        )
        assert type(err) is XaiTimeoutError
    finally:
        _close_sync(client)


def test_to2_6_default_retry_bounds_stall(
    monkeypatch: pytest.MonkeyPatch, stall_port: int
) -> None:
    _point_shared_client_at_stall(monkeypatch, f"127.0.0.1:{stall_port}")
    policy = default_retry_policy()
    seconds = 0.4
    client = _stall_client(stall_port, timeout=seconds, retry_policy=policy)
    delay = policy.backoff_seconds
    backoff_sum = 0.0
    for _attempt in range(policy.max_attempts - 1):
        backoff_sum += min(delay, policy.max_backoff_seconds)
        delay = min(delay * policy.backoff_multiplier, policy.max_backoff_seconds)
    upper = policy.max_attempts * seconds + backoff_sum + 2.0
    started = time.monotonic()
    try:
        with pytest.raises(XaiTimeoutError):
            client.chat([{"role": "user", "content": "hi"}])
        elapsed = time.monotonic() - started
        assert elapsed <= upper
        assert elapsed > seconds * 1.5
    finally:
        _close_sync(client)


def test_to2_7_batch_stall_sync_and_async(
    monkeypatch: pytest.MonkeyPatch, stall_port: int
) -> None:
    _point_shared_client_at_stall(monkeypatch, f"127.0.0.1:{stall_port}")
    sync = _stall_client(stall_port, timeout=1.0)
    try:
        _expect_timeout(lambda: sync.get_batch("batch-1"), seconds=1.0)
    finally:
        _close_sync(sync)

    async def _go() -> None:
        client = AsyncXaiClient(
            api_key=FAKE_KEY,
            base_url=f"http://127.0.0.1:{stall_port}",
            timeout=1.0,
            retry_policy=_single_try(),
            **_pins(),
        )
        started = time.monotonic()
        try:
            with pytest.raises(XaiTimeoutError) as caught:
                await client.get_batch("batch-1")
            assert time.monotonic() - started <= 1.0 + 2.0
            assert isinstance(caught.value, XaiTimeoutError)
        finally:
            await client.aclose()

    asyncio.run(_go())


# --- XK-TO-3 ---


def test_to3_2_other_construction_kwargs_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_capture(monkeypatch)
    XaiClient(api_key=FAKE_KEY, **_pins())
    shared = _without_timeout(_CaptureClient.built[0])
    assert shared == {"api_key": FAKE_KEY, "management_api_key": None}

    _CaptureClient.built = []
    XaiClient(api_key=FAKE_KEY, base_url="http://127.0.0.1:9", **_pins())
    assert _without_timeout(_CaptureClient.built[0]) == {
        "api_key": FAKE_KEY,
        "management_api_key": None,
    }
    regional = _without_timeout(_CaptureClient.built[1])
    assert regional == {
        "api_key": FAKE_KEY,
        "management_api_key": None,
        "api_host": "127.0.0.1:9",
        "use_insecure_channel": True,
    }

    _CaptureClient.built = []
    AsyncXaiClient(api_key=FAKE_KEY, base_url="https://example.com/v1", **_pins())
    assert _without_timeout(_CaptureClient.built[0]) == {
        "api_key": FAKE_KEY,
        "management_api_key": None,
    }
    assert _without_timeout(_CaptureClient.built[1])["api_host"] == "example.com"
    assert _without_timeout(_CaptureClient.built[1])["use_insecure_channel"] is False


def test_to3_3_timeout_does_not_leak_into_chat_create(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_capture(monkeypatch)
    client = XaiClient(api_key=FAKE_KEY, timeout=30, retry_policy=_single_try(), **_pins())
    client.chat([{"role": "user", "content": "hi"}], temperature=0.2, max_tokens=16)
    created = client._client.creates
    assert created
    assert "timeout" not in created[-1]
    assert created[-1]["model"] == "grok-4.7"
    assert created[-1]["temperature"] == 0.2
    assert "messages" in created[-1]


def test_to3_4_injected_provider_builds_no_sdk_client(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_capture(monkeypatch)
    provider = MockChatProvider(replies="from-mock")
    client = XaiClient(provider=provider, api_key=FAKE_KEY, retry_policy=_single_try(), **_pins())
    assert _CaptureClient.built == []
    assert client._client is None
    reply = client.chat([{"role": "user", "content": "hi"}])
    assert reply.content == "from-mock"


def test_to3_5_public_signature_keeps_existing_args() -> None:
    for cls in (XaiClient, AsyncXaiClient):
        sig = inspect.signature(cls.__init__)
        params = list(sig.parameters)
        head = [name for name in params if name != "timeout"]
        assert head == _BASE_INIT_PARAMS
        if "timeout" in sig.parameters:
            knob = sig.parameters["timeout"]
            assert knob.kind is inspect.Parameter.KEYWORD_ONLY
            assert knob.default is None
            assert params[-1] == "timeout"


def test_to3_6_retry_defaults_unchanged() -> None:
    policy = default_retry_policy()
    assert policy.max_attempts == 3
    assert policy.backoff_seconds == 0.5
    assert policy.backoff_multiplier == 2.0
    assert policy.max_backoff_seconds == 8.0
    assert policy.timeout_seconds == 0.0


@pytest.mark.parametrize("status_name", ["UNAUTHENTICATED", "RESOURCE_EXHAUSTED"])
def test_to3_7_non_timeout_errors_stay_runtime(
    monkeypatch: pytest.MonkeyPatch, status_name: str
) -> None:
    _install_capture(monkeypatch, fail=_FakeRpcError(status_name, "nope"))
    client = XaiClient(api_key=FAKE_KEY, retry_policy=_single_try(), **_pins())
    with pytest.raises(RuntimeError, match="xAI request failed") as caught:
        client.chat([{"role": "user", "content": "hi"}])
    assert not isinstance(caught.value, XaiTimeoutError)
    assert status_name.lower() not in type(caught.value).__name__.lower()


@pytest.mark.parametrize("bad", [0, 0.0, -1])
def test_list_models_invalid_sdk_timeout_is_not_cached(
    monkeypatch: pytest.MonkeyPatch, bad: float
) -> None:
    calls = {"n": 0}

    def _fetch(api_key: str, *, timeout: float | None = None) -> list[ModelInfo]:
        del api_key, timeout
        calls["n"] += 1
        raise RuntimeError("list down")

    monkeypatch.setattr("xaikit.catalog.fetch_models_from_sdk", _fetch)
    with pytest.raises(ValueError):
        list_models(api_key=FAKE_KEY, sdk_timeout=bad, force_refresh=True)
    assert calls["n"] == 0
    assert catalog_source() is None
    assert cached_catalog() is None

    rows = list_models(api_key=FAKE_KEY, force_refresh=True)
    assert calls["n"] == 1
    assert catalog_source() == "sdk-error"
    assert rows


@pytest.mark.parametrize("kind", ["xai", "deadline"])
def test_list_models_deadline_fallback_uses_short_retry_window(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    calls = {"n": 0}
    clock = {"t": 1_000_000.0}
    if kind == "xai":
        failure: BaseException = XaiTimeoutError("xAI SDK call timed out")
    else:
        failure = _FakeRpcError("DEADLINE_EXCEEDED", "Deadline Exceeded")

    def _fetch(api_key: str, *, timeout: float | None = None) -> list[ModelInfo]:
        del api_key, timeout
        calls["n"] += 1
        raise failure

    monkeypatch.setattr("xaikit.catalog.time.time", lambda: clock["t"])
    monkeypatch.setattr("xaikit.catalog.fetch_models_from_sdk", _fetch)
    rows = list_models(api_key=FAKE_KEY, sdk_timeout=1.0)
    assert [row.id for row in rows] == [BOOTSTRAP_MODEL, "grok-4.3"]
    assert catalog_source() == "sdk-error"
    assert calls["n"] == 1

    again = list_models(api_key=FAKE_KEY, sdk_timeout=1.0)
    assert [row.id for row in again] == [BOOTSTRAP_MODEL, "grok-4.3"]
    assert calls["n"] == 1

    clock["t"] += CATALOG_TIMEOUT_RETRY_SECONDS - 1
    held = list_models(api_key=FAKE_KEY, sdk_timeout=1.0)
    assert [row.id for row in held] == [BOOTSTRAP_MODEL, "grok-4.3"]
    assert calls["n"] == 1

    clock["t"] += 1
    refetched = list_models(api_key=FAKE_KEY, sdk_timeout=1.0)
    assert [row.id for row in refetched] == [BOOTSTRAP_MODEL, "grok-4.3"]
    assert calls["n"] == 2


def test_second_list_deadline_is_raised_and_uses_short_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"n": 0}
    clock = {"t": 1_000_000.0}

    class _Client:
        def __init__(self, api_key: str, timeout: float | None = None, **kwargs: object) -> None:
            del api_key, timeout, kwargs
            calls["n"] += 1
            self.models = self

        def list_language_models(self) -> list[object]:
            raise RuntimeError("language down")

        def list_image_generation_models(self) -> list[object]:
            raise _FakeRpcError("DEADLINE_EXCEEDED", "Deadline Exceeded")

        def close(self) -> None:
            return None

    monkeypatch.setattr("xaikit.catalog.time.time", lambda: clock["t"])
    monkeypatch.setattr("xai_sdk.Client", _Client)
    with pytest.raises(_FakeRpcError) as caught:
        fetch_models_from_sdk(FAKE_KEY, timeout=1.0)
    assert caught.value.code().name == "DEADLINE_EXCEEDED"
    assert calls["n"] == 1

    rows = list_models(api_key=FAKE_KEY, sdk_timeout=1.0)
    assert [row.id for row in rows] == [BOOTSTRAP_MODEL, "grok-4.3"]
    assert catalog_source() == "sdk-error"
    assert calls["n"] == 2

    list_models(api_key=FAKE_KEY, sdk_timeout=1.0)
    assert calls["n"] == 2

    clock["t"] += CATALOG_TIMEOUT_RETRY_SECONDS
    list_models(api_key=FAKE_KEY, sdk_timeout=1.0)
    assert calls["n"] == 3


def test_long_stream_doc_line() -> None:
    text = (ROOT / "docs" / "features" / "ClientChat.md").read_text(encoding="utf-8")
    assert "Callers with long streams should raise timeout= on the client." in text
    assert "XK-TO-1" in text
    assert "XK-TO-2" in text
    assert "XK-TO-3" in text
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## 0.4.0 (2026-10-14)" in changelog
    assert "XK-TO-1" in changelog
    version = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "0.4.0"' in version
