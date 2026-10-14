"""CUT-2026-10-14-xk-async-host-catalog.

Offline cases AHC-C01..C14. Loopback only. Fake key. No live network.
C12 is the existing wiring, regional, and SDK timeout modules in the full suite.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
import socket
import threading
import time
import warnings
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

import pytest

from xaikit import AsyncXaiClient, RoleUnavailableOnHost, XaiClient
from xaikit.catalog import (
    HOST_MODELS_TIMEOUT_SECONDS,
    fetch_host_catalog_async,
    static_fallback_models,
)
from xaikit.provider import MockChatProvider

KEY = "xai-test-FAKE"
MESSAGES = [{"role": "user", "content": "hi"}]
TICK_SECONDS = 0.05
CLIENT_TIMEOUT = 2.0
TIME_SLACK = 2.0


def _min_ticks(elapsed: float) -> int:
    """N = max(10, floor(0.5 * elapsed / 0.05))."""
    return max(10, math.floor(0.5 * elapsed / TICK_SECONDS))


@pytest.fixture(autouse=True)
def _clean_catalog():
    from xaikit.catalog import clear_catalog_cache, inject_catalog

    inject_catalog(None)
    clear_catalog_cache()
    yield
    inject_catalog(None)
    clear_catalog_cache()


@pytest.fixture(autouse=True)
def _loopback_only(monkeypatch: pytest.MonkeyPatch):
    """Fail on any non-loopback TCP connect."""

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


def _async_client(base: str, **kwargs: Any) -> AsyncXaiClient:
    params: dict[str, Any] = {
        "api_key": KEY,
        "base_url": base,
        "provider": MockChatProvider("ok"),
        "intent": "best",
    }
    params.update(kwargs)
    return AsyncXaiClient(**params)


def _sync_client(base: str, **kwargs: Any) -> XaiClient:
    params: dict[str, Any] = {
        "api_key": KEY,
        "base_url": base,
        "provider": MockChatProvider("ok"),
        "intent": "best",
    }
    params.update(kwargs)
    return XaiClient(**params)


def _effective_ids(client: Any) -> list[str]:
    loaded = client._regional_models
    if loaded is None:
        return [row.id for row in static_fallback_models()]
    return [info.id for info, _role in loaded]


def _stored_rows(client: Any) -> list[tuple[Any, ...]]:
    loaded = client._regional_models
    assert loaded is not None
    return [(info.id, info.created, info.owned_by, role) for info, role in loaded]


def _catalog_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        rec
        for rec in caplog.records
        if rec.name == "xaikit.catalog" and rec.levelno >= logging.WARNING
    ]


def _run(coro: Any) -> Any:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = asyncio.run(coro)
    pending = [
        item
        for item in caught
        if issubclass(item.category, RuntimeWarning) and "never awaited" in str(item.message)
    ]
    assert pending == []
    return result


async def _measure(work: Callable[[], Any]) -> tuple[Any, BaseException | None, int, float]:
    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(TICK_SECONDS)

    task = asyncio.create_task(ticker())
    started = time.monotonic()
    error: BaseException | None = None
    value: Any = None
    try:
        value = await work()
    except Exception as exc:
        error = exc
    elapsed = time.monotonic() - started
    counted = ticks
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    return value, error, counted, elapsed


def _start_stall() -> dict[str, Any]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(16)
    port = int(sock.getsockname()[1])
    stop = threading.Event()
    conns: list[socket.socket] = []
    guard = threading.Lock()

    def accept_loop() -> None:
        sock.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _addr = sock.accept()
            except (socket.timeout, TimeoutError, OSError):
                continue
            conn.setblocking(False)
            with guard:
                conns.append(conn)

    thread = threading.Thread(target=accept_loop, name="ahc-stall", daemon=True)
    thread.start()
    return {
        "sock": sock,
        "stop": stop,
        "conns": conns,
        "guard": guard,
        "thread": thread,
        "port": port,
        "base": f"http://127.0.0.1:{port}/v1",
    }


def _stop_stall(stall: dict[str, Any]) -> None:
    stall["stop"].set()
    try:
        stall["sock"].close()
    except OSError:
        pass
    with stall["guard"]:
        conns = list(stall["conns"])
    for conn in conns:
        try:
            conn.close()
        except OSError:
            pass
    stall["thread"].join(timeout=2)


def _closed_base() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return f"http://127.0.0.1:{port}/v1"


def _start_http(
    ids: list[str] | None = None,
    *,
    status: int = 200,
    created: dict[str, int] | None = None,
) -> dict[str, Any]:
    records: list[str] = []
    listed = list(ids or ["grok-4.7", "grok-4.6"])
    stamps = dict(created or {})

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802
            records.append(self.path.split("?", 1)[0])
            if status >= 400:
                body = b"nope"
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            payload = {
                "data": [
                    {
                        "id": mid,
                        "object": "model",
                        "created": stamps.get(mid, 1_700_000_000),
                        "owned_by": "xai",
                    }
                    for mid in listed
                ]
            }
            raw = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, fmt: str, *args: Any) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = int(server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, name="ahc-http", daemon=True)
    thread.start()
    return {
        "server": server,
        "thread": thread,
        "records": records,
        "port": port,
        "base": f"http://127.0.0.1:{port}/v1",
        "host": f"127.0.0.1:{port}",
    }


def _stop_http(host: dict[str, Any]) -> None:
    host["server"].shutdown()
    host["thread"].join(timeout=2)
    host["server"].server_close()


def _model_gets(records: list[str]) -> list[str]:
    return [path for path in records if path.endswith("/models")]


def test_ahc_c01_stall_ticker_keeps_running() -> None:
    stall = _start_stall()
    try:

        async def work() -> None:
            client = _async_client(stall["base"], timeout=CLIENT_TIMEOUT)
            await client.chat(MESSAGES)

        _value, error, ticks, elapsed = _run(_measure(work))
        assert error is None
        assert ticks >= _min_ticks(elapsed)
    finally:
        _stop_stall(stall)


def test_ahc_c02_stall_respects_client_timeout() -> None:
    assert HOST_MODELS_TIMEOUT_SECONDS == 30.0
    stall = _start_stall()
    try:

        async def work() -> None:
            client = _async_client(stall["base"], timeout=CLIENT_TIMEOUT)
            await client.chat(MESSAGES)

        _value, error, _ticks, elapsed = _run(_measure(work))
        assert error is None
        assert elapsed <= CLIENT_TIMEOUT + TIME_SLACK
    finally:
        _stop_stall(stall)


def test_ahc_c03_two_clients_stay_concurrent() -> None:
    stall = _start_stall()
    try:

        async def work() -> tuple[float, float]:
            left = _async_client(stall["base"], timeout=CLIENT_TIMEOUT)
            right = _async_client(stall["base"], timeout=CLIENT_TIMEOUT)

            async def one(client: AsyncXaiClient) -> float:
                started = time.monotonic()
                await client.chat(MESSAGES)
                return time.monotonic() - started

            return await asyncio.gather(one(left), one(right))

        value, error, ticks, elapsed = _run(_measure(work))
        assert error is None
        first, second = value
        assert first <= CLIENT_TIMEOUT + TIME_SLACK
        assert second <= CLIENT_TIMEOUT + TIME_SLACK
        assert ticks >= _min_ticks(elapsed)
    finally:
        _stop_stall(stall)


def test_ahc_c04_async_fetch_entry_point() -> None:
    stall = _start_stall()
    try:

        async def work() -> None:
            await fetch_host_catalog_async(KEY, stall["base"], timeout=CLIENT_TIMEOUT)

        _value, error, ticks, elapsed = _run(_measure(work))
        assert isinstance(error, RuntimeError)
        assert ticks >= _min_ticks(elapsed)
        assert elapsed <= CLIENT_TIMEOUT + TIME_SLACK
    finally:
        _stop_stall(stall)


def test_ahc_c05_down_async_matches_sync_fallback() -> None:
    base = _closed_base()
    sync = _sync_client(base)
    sync_model = sync.model

    async def work() -> tuple[AsyncXaiClient, str]:
        client = _async_client(base)
        await client.chat(MESSAGES)
        return client, client.model

    client, async_model = _run(work())
    assert async_model == sync_model
    assert client._regional_models is None
    assert sync._regional_models is None
    assert _effective_ids(client) == _effective_ids(sync)
    assert async_model == "grok-4.7"


def test_ahc_c06_stall_async_matches_sync_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("xaikit.catalog.HOST_MODELS_TIMEOUT_SECONDS", 0.2)
    stall = _start_stall()
    try:
        sync = _sync_client(stall["base"])
        sync_model = sync.model

        async def work() -> tuple[AsyncXaiClient, str]:
            client = _async_client(stall["base"])
            await client.chat(MESSAGES)
            return client, client.model

        client, async_model = _run(work())
        assert async_model == sync_model
        assert _effective_ids(client) == _effective_ids(sync)
        assert [row.id for row in static_fallback_models()] == _effective_ids(client)
    finally:
        _stop_stall(stall)


def test_ahc_c07_http_500_async_matches_sync_fallback() -> None:
    host = _start_http(status=500)
    try:
        sync = _sync_client(host["base"])
        sync_model = sync.model

        async def work() -> tuple[AsyncXaiClient, str]:
            client = _async_client(host["base"])
            await client.chat(MESSAGES)
            return client, client.model

        client, async_model = _run(work())
        assert async_model == sync_model
        assert client._regional_models is None
        assert sync._regional_models is None
        assert _effective_ids(client) == _effective_ids(sync)
    finally:
        _stop_http(host)


def test_ahc_c08_down_warns_once_with_sync_text(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="xaikit.catalog")
    base = _closed_base()
    caplog.clear()
    sync = _sync_client(base)
    assert sync.model == "grok-4.7"
    sync_messages = [rec.getMessage() for rec in _catalog_warnings(caplog)]
    caplog.clear()

    async def work() -> None:
        client = _async_client(base)
        await client.chat(MESSAGES)
        await client.chat(MESSAGES)

    _run(work())
    async_messages = [rec.getMessage() for rec in _catalog_warnings(caplog)]
    assert len(sync_messages) == 1
    assert async_messages == sync_messages
    assert "using the static catalog" in async_messages[0]


def test_ahc_c09_ok_async_matches_sync_models() -> None:
    host = _start_http(
        ["grok-4.6", "grok-4.7", "grok-imagine-image"],
        created={"grok-4.6": 100, "grok-4.7": 200, "grok-imagine-image": 300},
    )
    try:
        sync = _sync_client(host["base"])
        sync_model = sync.model
        sync_image = sync.image_model

        async def work() -> AsyncXaiClient:
            client = _async_client(host["base"])
            await client.chat(MESSAGES)
            return client

        client = _run(work())
        assert client.model == sync_model == "grok-4.7"
        assert client.image_model == sync_image == "grok-imagine-image"
        assert _stored_rows(client) == _stored_rows(sync)
    finally:
        _stop_http(host)


def test_ahc_c10_chat_only_host_image_raises() -> None:
    host = _start_http(["grok-4.7"])
    try:
        sync = _sync_client(host["base"])
        with pytest.raises(RoleUnavailableOnHost) as sync_caught:
            sync.generate_image("cat")

        async def work() -> RoleUnavailableOnHost:
            client = _async_client(host["base"])
            with pytest.raises(RoleUnavailableOnHost) as caught:
                await client.generate_image("cat")
            return caught.value

        async_exc = _run(work())
        sync_exc = sync_caught.value
        assert type(async_exc) is type(sync_exc)
        assert async_exc.role == sync_exc.role == "image"
        assert async_exc.host == sync_exc.host == host["host"]
        assert str(async_exc) == str(sync_exc)
    finally:
        _stop_http(host)


def test_ahc_c11_sync_stall_blocks_on_default_timeout() -> None:
    """Sync client keeps the 30 second host timeout and blocks the caller."""
    assert HOST_MODELS_TIMEOUT_SECONDS == 30.0
    stall = _start_stall()
    try:

        async def work() -> tuple[str, float, int]:
            ticks = 0

            async def ticker() -> None:
                nonlocal ticks
                while True:
                    ticks += 1
                    await asyncio.sleep(TICK_SECONDS)

            task = asyncio.create_task(ticker())
            await asyncio.sleep(0.12)
            before = ticks
            client = _sync_client(stall["base"])
            started = time.monotonic()
            client.chat(MESSAGES)
            elapsed = time.monotonic() - started
            during = ticks - before
            model = client.model
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            assert before >= 1
            return model, elapsed, during

        model, elapsed, during = _run(work())
        assert model == "grok-4.7"
        assert elapsed >= HOST_MODELS_TIMEOUT_SECONDS * 0.8
        assert during < 10
    finally:
        _stop_stall(stall)


def test_ahc_c13_second_chat_does_not_fetch_again() -> None:
    host = _start_http(["grok-4.7", "grok-4.6"])
    try:

        async def work() -> str:
            client = _async_client(host["base"])
            await client.chat(MESSAGES)
            await client.chat(MESSAGES)
            return client.model

        assert _run(work()) == "grok-4.7"
        assert len(_model_gets(host["records"])) == 1
    finally:
        _stop_http(host)


def test_ahc_c14_stall_timeout_ignores_host_cap_of_30() -> None:
    assert HOST_MODELS_TIMEOUT_SECONDS == 30.0
    stall = _start_stall()
    try:

        async def work() -> None:
            client = _async_client(stall["base"], timeout=CLIENT_TIMEOUT)
            await client.chat(MESSAGES)

        _value, error, _ticks, elapsed = _run(_measure(work))
        assert error is None
        assert elapsed <= CLIENT_TIMEOUT + TIME_SLACK
    finally:
        _stop_stall(stall)
