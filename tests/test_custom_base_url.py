"""CUT-2026-10-13-xk-custom-base-url.

Graded cases XK-AC-URL-1 (U1-1..U1-9) and XK-AC-URL-2 (U2-1..U2-5).
The assertions are specific enough to kill mutants M1..M14.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import socket
import threading
import warnings
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest

from xaikit import (
    XAI_CHAT_COMPLETIONS_URL,
    XAI_DEFERRED_CHAT_URL,
    XAI_EMBEDDINGS_URL,
    XAI_FILES_URL,
    XAI_IMAGE_EDITS_URL,
    XAI_IMAGES_URL,
    XAI_REALTIME_CLIENT_SECRETS_URL,
    XAI_REALTIME_URL,
    XAI_RESPONSES_URL,
    XAI_STT_URL,
    XAI_STT_WS_URL,
    XAI_TOKENIZE_URL,
    XAI_TTS_URL,
    XAI_TTS_VOICES_URL,
    XAI_TTS_WS_URL,
    XAI_VIDEO_EXTENSIONS_URL,
    XAI_VIDEO_STATUS_URL,
    XAI_VIDEOS_URL,
    AsyncXaiClient,
    XaiClient,
)
from xaikit.catalog import clear_catalog_cache, inject_catalog, list_models
from xaikit.realtime import realtime_session_url
from xaikit.stt_stream import stt_session_url
from xaikit.tts_stream import tts_session_url
from xaikit.types import ModelInfo

KEY = "xai-test-FAKE"
DEFAULT_BASE_URL = "https://api.x.ai/v1"
ROOT = Path(__file__).resolve().parents[1]

HISTORICAL_URLS = {
    "stt": "https://api.x.ai/v1/stt",
    "tts": "https://api.x.ai/v1/tts",
    "tts/voices": "https://api.x.ai/v1/tts/voices",
    "images/generations": "https://api.x.ai/v1/images/generations",
    "images/edits": "https://api.x.ai/v1/images/edits",
    "files": "https://api.x.ai/v1/files",
    "embeddings": "https://api.x.ai/v1/embeddings",
    "tokenize-text": "https://api.x.ai/v1/tokenize-text",
    "responses": "https://api.x.ai/v1/responses",
    "chat/completions": "https://api.x.ai/v1/chat/completions",
    "chat/deferred-completion": "https://api.x.ai/v1/chat/deferred-completion",
    "realtime/client_secrets": "https://api.x.ai/v1/realtime/client_secrets",
    "videos/generations": "https://api.x.ai/v1/videos/generations",
    "videos/extensions": "https://api.x.ai/v1/videos/extensions",
    "videos/{request_id}": "https://api.x.ai/v1/videos/{request_id}",
    "stt-ws": "wss://api.x.ai/v1/stt",
    "tts-ws": "wss://api.x.ai/v1/tts",
    "realtime-ws": "wss://api.x.ai/v1/realtime",
}

_FIXTURE = [
    ModelInfo(id="grok-test", capabilities=["chat", "image", "video", "voice"]),
]


def _pins() -> dict[str, str]:
    return {
        "model": "grok-test",
        "image_model": "grok-test",
        "video_model": "grok-test",
        "voice_model": "grok-test",
    }


def make_client(cls: type = XaiClient, base_url: str | None = None, **kwargs: Any):
    params: dict[str, Any] = {"api_key": KEY, **_pins()}
    if base_url is not None:
        params["base_url"] = base_url
    params.update(kwargs)
    return cls(**params)


@pytest.fixture(autouse=True)
def _injected_catalog():
    inject_catalog(_FIXTURE)
    clear_catalog_cache()
    yield
    inject_catalog(None)
    clear_catalog_cache()


@pytest.fixture(autouse=True)
def _loopback_only(monkeypatch: pytest.MonkeyPatch):
    """Fail the test on any non-loopback TCP connect."""

    def _host(address: Any) -> str:
        if isinstance(address, tuple) and address:
            return str(address[0])
        return str(address)

    def _check(address: Any) -> None:
        host = _host(address)
        if host not in {"127.0.0.1", "::1", "localhost"}:
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


@pytest.fixture
def http_server():
    records: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def _serve(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            names = {key.lower() for key in self.headers.keys()}
            records.append(
                {
                    "method": self.command,
                    "path": self.path,
                    "host": self.headers.get("Host"),
                    "authorization": self.headers.get("Authorization"),
                    "header_names": names,
                    "body": body,
                }
            )
            path = self.path.split("?", 1)[0]
            if path.endswith("/images/generations") or path.endswith("/images/edits"):
                payload: dict[str, Any] = {"data": [{"url": "http://127.0.0.1/img.png"}]}
            elif path.endswith("/chat/completions"):
                payload = {
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "hello"},
                            "finish_reason": "stop",
                        }
                    ],
                    "model": "grok-test",
                }
            elif path.endswith("/models"):
                payload = {"data": [{"id": "grok-from-proxy"}]}
            else:
                payload = {"ok": True}
            raw = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:  # noqa: N802
            self._serve()

        def do_POST(self) -> None:  # noqa: N802
            self._serve()

        def do_DELETE(self) -> None:  # noqa: N802
            self._serve()

        def log_message(self, fmt: str, *args: Any) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield {
            "base": f"http://127.0.0.1:{port}/proxy/v1",
            "bare": f"http://127.0.0.1:{port}",
            "port": port,
            "records": records,
        }
    finally:
        server.shutdown()
        thread.join(timeout=2)


def _assert_auth(record: dict[str, Any]) -> None:
    assert record["authorization"] == f"Bearer {KEY}"
    assert KEY not in record["path"]
    lowered = record["header_names"]
    assert "authorization" in lowered
    assert "x-api-key" not in lowered
    assert "api-key" not in lowered


def _quiet(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception:
        return None


class _Capture:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, str] | None, Any]] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        capture = self

        def _response(method: str, url: str) -> httpx.Response:
            return httpx.Response(
                200,
                json={"ok": True},
                request=httpx.Request(method, url),
            )

        def post(url, **kwargs):  # type: ignore[no-untyped-def]
            capture.calls.append(("POST", str(url), kwargs.get("headers"), kwargs.get("json")))
            return _response("POST", str(url))

        def get(url, **kwargs):  # type: ignore[no-untyped-def]
            capture.calls.append(("GET", str(url), kwargs.get("headers"), kwargs.get("json")))
            return _response("GET", str(url))

        def delete(url, **kwargs):  # type: ignore[no-untyped-def]
            capture.calls.append(("DELETE", str(url), kwargs.get("headers"), None))
            return _response("DELETE", str(url))

        monkeypatch.setattr(httpx, "post", post)
        monkeypatch.setattr(httpx, "get", get)
        monkeypatch.setattr(httpx, "delete", delete)
        monkeypatch.setattr("xaikit.client.httpx.post", post)
        monkeypatch.setattr("xaikit.client.httpx.get", get)
        monkeypatch.setattr("xaikit.client.httpx.delete", delete)

        class FakeAsync:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                return None

            async def __aenter__(self) -> FakeAsync:
                return self

            async def __aexit__(self, *args: Any) -> None:
                return None

            async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
                capture.calls.append(
                    (method.upper(), str(url), kwargs.get("headers"), kwargs.get("json"))
                )
                return _response(method, str(url))

            async def aclose(self) -> None:
                return None

        monkeypatch.setattr("xaikit.async_client.httpx.AsyncClient", FakeAsync)


def _exercise_sync(client: XaiClient) -> None:
    _quiet(client.chat, [{"role": "user", "content": "hi"}])
    _quiet(client.generate_image, "a cat")
    _quiet(client.edit_image, "edit", image_url="http://127.0.0.1/a.png")
    _quiet(client.upload_file, b"abc", "a.txt")
    _quiet(client.embed, "hi", model="grok-test")
    _quiet(client.tokenize, "hi")
    _quiet(client.create_response, "hi")
    _quiet(client.create_deferred_chat, [{"role": "user", "content": "hi"}])
    _quiet(client.get_deferred_chat, "job-1")
    _quiet(client.create_realtime_client_secret)
    _quiet(client.generate_video, "clip", into=[], wait=False)
    _quiet(
        client.extend_video,
        "more",
        video_url="http://127.0.0.1/v.mp4",
        into=[],
        wait=False,
    )
    _quiet(client.poll_video, "vid-1")
    _quiet(client.synthesize_speech, "hi")
    _quiet(client.list_tts_voices)
    _quiet(client.transcribe, b"abc")


async def _exercise_async(client: AsyncXaiClient) -> None:
    await _quiet_async(client.chat([{"role": "user", "content": "hi"}]))
    await _quiet_async(client.generate_image("a cat"))
    await _quiet_async(client.edit_image("edit", image_url="http://127.0.0.1/a.png"))
    await _quiet_async(client.upload_file(b"abc", "a.txt"))
    await _quiet_async(client.embed("hi", model="grok-test"))
    await _quiet_async(client.tokenize("hi"))
    await _quiet_async(client.create_response("hi"))
    await _quiet_async(client.create_deferred_chat([{"role": "user", "content": "hi"}]))
    await _quiet_async(client.get_deferred_chat("job-1"))
    await _quiet_async(client.create_realtime_client_secret())
    await _quiet_async(client.generate_video("clip", into=[], wait=False))
    await _quiet_async(
        client.extend_video("more", video_url="http://127.0.0.1/v.mp4", into=[], wait=False)
    )
    await _quiet_async(client.poll_video("vid-1"))
    await _quiet_async(client.synthesize_speech("hi"))
    await _quiet_async(client.list_tts_voices())
    await _quiet_async(client.transcribe(b"abc"))


async def _quiet_async(coro):  # type: ignore[no-untyped-def]
    try:
        return await coro
    except Exception:
        return None


def _paths(calls: list[tuple[str, str, Any, Any]]) -> list[tuple[str, str]]:
    out = []
    for method, url, _headers, _body in calls:
        out.append((method, urlsplit(url).path))
    return out


def test_u1_1_constructor_arg_sync_and_async(http_server) -> None:
    base = http_server["base"]
    sync = make_client(base_url=base)
    image = sync.generate_image("a cat")
    assert image["url"] == "http://127.0.0.1/img.png"
    assert http_server["records"][-1]["method"] == "POST"
    assert http_server["records"][-1]["path"] == "/proxy/v1/images/generations"
    _assert_auth(http_server["records"][-1])

    async def _once() -> dict[str, Any]:
        client = make_client(AsyncXaiClient, base_url=base)
        return await client.generate_image("a cat")

    again = asyncio.run(_once())
    assert again["url"] == "http://127.0.0.1/img.png"
    assert http_server["records"][-1]["path"] == "/proxy/v1/images/generations"
    _assert_auth(http_server["records"][-1])


def test_u1_2_env_fallback(monkeypatch: pytest.MonkeyPatch, http_server) -> None:
    monkeypatch.setenv("XAI_BASE_URL", http_server["base"])
    client = make_client()
    assert client.base_url == http_server["base"]
    client.generate_image("a cat")
    assert http_server["records"][-1]["path"] == "/proxy/v1/images/generations"


def test_u1_3_arg_beats_env_and_default(monkeypatch: pytest.MonkeyPatch, http_server) -> None:
    monkeypatch.setenv("XAI_BASE_URL", "http://127.0.0.1:1/env-only")
    client = make_client(base_url=http_server["base"])
    client.generate_image("a cat")
    assert http_server["records"][-1]["path"] == "/proxy/v1/images/generations"
    assert all("env-only" not in rec["path"] for rec in http_server["records"])
    assert client.base_url == http_server["base"]

    monkeypatch.delenv("XAI_BASE_URL", raising=False)
    plain = make_client()
    assert plain.base_url == "https://api.x.ai/v1"


def test_u1_4_blank_is_unset_and_env_is_sticky(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XAI_BASE_URL", "   ")
    assert make_client().base_url == DEFAULT_BASE_URL
    assert make_client(base_url="").base_url == DEFAULT_BASE_URL
    assert make_client(base_url="   ").base_url == DEFAULT_BASE_URL

    monkeypatch.setenv("XAI_BASE_URL", "http://127.0.0.1:9/from-env")
    sticky = make_client(base_url="  ")
    assert sticky.base_url == "http://127.0.0.1:9/from-env"
    monkeypatch.setenv("XAI_BASE_URL", "http://127.0.0.1:9/later")
    assert sticky.base_url == "http://127.0.0.1:9/from-env"


def test_u1_5_and_u2_4_rest_families_sync_and_async(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each REST family keeps its suffix. M9 fails one row. M10 fails the async half."""
    custom = "http://127.0.0.1:9/proxy/v1"
    expected = {
        "POST /proxy/v1/chat/completions",
        "POST /proxy/v1/images/generations",
        "POST /proxy/v1/images/edits",
        "POST /proxy/v1/files",
        "POST /proxy/v1/embeddings",
        "POST /proxy/v1/tokenize-text",
        "POST /proxy/v1/responses",
        "GET /proxy/v1/chat/deferred-completion/job-1",
        "POST /proxy/v1/realtime/client_secrets",
        "POST /proxy/v1/videos/generations",
        "POST /proxy/v1/videos/extensions",
        "GET /proxy/v1/videos/vid-1",
        "POST /proxy/v1/tts",
        "GET /proxy/v1/tts/voices",
        "POST /proxy/v1/stt",
        "GET /proxy/v1/models",
    }

    def _run(cls: type) -> set[str]:
        capture = _Capture()
        capture.install(monkeypatch)
        if cls is AsyncXaiClient:
            async def _go() -> None:
                client = make_client(cls, base_url=custom)
                await _exercise_async(client)

            asyncio.run(_go())
        else:
            client = make_client(cls, base_url=custom)
            _exercise_sync(client)
        inject_catalog(None)
        clear_catalog_cache()
        try:
            _quiet(
                list_models,
                api_key=KEY,
                base_url=custom,
                force_refresh=True,
                allow_fixture_fallback=False,
            )
        finally:
            inject_catalog(_FIXTURE)
            clear_catalog_cache()
        found = {f"{method} {path}" for method, path in _paths(capture.calls)}
        return found

    sync_found = _run(XaiClient)
    missing = expected - sync_found
    assert not missing, sorted(missing)
    async_found = _run(AsyncXaiClient)
    # models list is a module function, already covered on the sync pass
    async_expected = {item for item in expected if not item.startswith("GET /proxy/v1/models")}
    missing_async = async_expected - async_found
    assert not missing_async, sorted(missing_async)

    for call in sync_found:
        assert "api.x.ai" not in call
        assert KEY not in call


def _assert_exact_urls(
    calls: list[tuple[str, str, dict[str, str] | None, Any]],
    expected: set[tuple[str, str]],
) -> None:
    found = {(method, url) for method, url, _headers, _body in calls}
    missing = expected - found
    assert not missing, sorted(missing)
    for _method, url, _headers, _body in calls:
        assert "api.x.ai" not in url
        assert KEY not in url


def _assert_bearer(
    calls: list[tuple[str, str, dict[str, str] | None, Any]],
    expected: set[tuple[str, str]],
) -> None:
    """Authorization stays Bearer on a non-default host. X-API-Key does not."""
    by_target: dict[tuple[str, str], dict[str, str] | None] = {}
    for method, url, headers, _body in calls:
        by_target[(method, url)] = headers
        assert "api.x.ai" not in url
    missing = expected - set(by_target)
    assert not missing, sorted(missing)
    for target in expected:
        headers = by_target[target] or {}
        lowered = {key.lower(): value for key, value in headers.items()}
        assert lowered.get("authorization") == f"Bearer {KEY}"
        assert "x-api-key" not in lowered


def test_m9_resource_urls_follow_custom_base(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resource GET/DELETE and deferred create use the path-prefix base, sync and async."""
    base = "http://127.0.0.1:9/proxy/v1"
    expected = {
        ("POST", f"{base}/chat/completions"),
        ("GET", f"{base}/tts/voices/eve"),
        ("GET", f"{base}/files/file-1"),
        ("DELETE", f"{base}/files/file-1"),
        ("GET", f"{base}/responses/resp-1"),
    }

    capture = _Capture()
    capture.install(monkeypatch)
    client = make_client(base_url=base)
    messages = [{"role": "user", "content": "hi"}]
    _quiet(client.create_deferred_chat, messages)
    _quiet(client.get_tts_voice, "eve")
    _quiet(client.get_file, "file-1")
    _quiet(client.delete_file, "file-1")
    _quiet(client.get_response, "resp-1")
    _assert_exact_urls(capture.calls, expected)

    capture.calls.clear()

    async def _go() -> None:
        client = make_client(AsyncXaiClient, base_url=base)
        messages = [{"role": "user", "content": "hi"}]
        await _quiet_async(client.create_deferred_chat(messages))
        await _quiet_async(client.get_tts_voice("eve"))
        await _quiet_async(client.get_file("file-1"))
        await _quiet_async(client.delete_file("file-1"))
        await _quiet_async(client.get_response("resp-1"))

    asyncio.run(_go())
    _assert_exact_urls(capture.calls, expected)


def test_m12_bearer_auth_on_custom_base(monkeypatch: pytest.MonkeyPatch) -> None:
    """Off the default host, helper calls still send Authorization: Bearer."""
    base = "http://127.0.0.1:9/proxy/v1"
    expected = {
        ("POST", f"{base}/stt"),
        ("GET", f"{base}/files/file-1"),
        ("DELETE", f"{base}/files/file-1"),
        ("GET", f"{base}/responses/resp-1"),
        ("POST", f"{base}/chat/completions"),
        ("GET", f"{base}/videos/vid-1"),
    }

    capture = _Capture()
    capture.install(monkeypatch)
    client = make_client(base_url=base)
    _quiet(client.transcribe, b"abc")
    _quiet(client.get_file, "file-1")
    _quiet(client.delete_file, "file-1")
    _quiet(client.get_response, "resp-1")
    _quiet(client.create_deferred_chat, [{"role": "user", "content": "hi"}])
    _quiet(client.poll_video, "vid-1")
    _assert_bearer(capture.calls, expected)

    capture.calls.clear()

    async def _go() -> None:
        async_client = make_client(AsyncXaiClient, base_url=base)
        await _quiet_async(async_client.transcribe(b"abc"))
        await _quiet_async(async_client.get_file("file-1"))
        await _quiet_async(async_client.delete_file("file-1"))
        await _quiet_async(async_client.get_response("resp-1"))
        await _quiet_async(async_client.create_deferred_chat([{"role": "user", "content": "hi"}]))
        await _quiet_async(async_client.poll_video("vid-1"))

    asyncio.run(_go())
    _assert_bearer(capture.calls, expected)


def test_u1_5_chat_body_is_not_deferred(monkeypatch: pytest.MonkeyPatch) -> None:
    capture = _Capture()
    capture.install(monkeypatch)
    client = make_client(base_url="http://127.0.0.1:9/proxy/v1")
    client.chat([{"role": "user", "content": "hi"}])
    chat_calls = [item for item in capture.calls if item[0] == "POST" and item[1].endswith("/chat/completions")]
    assert chat_calls
    body = chat_calls[-1][3]
    assert isinstance(body, dict)
    assert body.get("deferred") is not True
    capture.calls.clear()
    _quiet(client.create_deferred_chat, [{"role": "user", "content": "hi"}])
    deferred = [item for item in capture.calls if str(item[1]).endswith("/chat/completions")]
    assert deferred
    assert deferred[-1][3]["deferred"] is True


def test_u1_5_bare_host_chat_uses_grpc(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bare host: SDK api_host is host:port and http is insecure. Path prefix is REST."""
    opened: list[dict[str, Any]] = []

    class Dummy:
        def __init__(self, api_key: str, management_api_key: str | None = None, **kwargs: Any) -> None:
            opened.append({"api_key": api_key, "management_api_key": management_api_key, **kwargs})

        def close(self) -> None:
            return None

    monkeypatch.setattr("xaikit.client.Client", Dummy)
    monkeypatch.setattr("xaikit.async_client.AsyncClient", Dummy)

    bare = make_client(base_url="http://127.0.0.1:9")
    assert bare.base_url == "http://127.0.0.1:9"
    assert opened[-1]["api_host"] == "127.0.0.1:9"
    assert opened[-1]["use_insecure_channel"] is True

    https_v1 = make_client(base_url="https://example.com/v1")
    assert opened[-1]["api_host"] == "example.com"
    assert opened[-1]["use_insecure_channel"] is False

    default = make_client()
    assert "api_host" not in opened[-1]
    assert "use_insecure_channel" not in opened[-1]
    assert default.base_url == DEFAULT_BASE_URL

    capture = _Capture()
    capture.install(monkeypatch)
    from xaikit.provider import MockChatProvider

    provider = MockChatProvider("ok")
    gRPC_client = make_client(
        base_url="http://127.0.0.1:9",
        provider=provider,
    )
    gRPC_client.chat([{"role": "user", "content": "hi"}])
    assert provider.calls
    assert capture.calls == []


def test_u1_6_websockets_sync_and_async(monkeypatch: pytest.MonkeyPatch) -> None:
    """M1: each socket. M6: scheme map. M7: port kept. Query knobs stay."""
    seen: list[tuple[str, dict[str, str] | None]] = []

    def fake(uri: str, **kwargs: Any) -> Any:
        seen.append((uri, kwargs.get("additional_headers")))
        raise RuntimeError("ws-stop")

    async def fake_async(uri: str, **kwargs: Any) -> Any:
        seen.append((uri, kwargs.get("additional_headers")))
        raise RuntimeError("ws-stop")

    monkeypatch.setattr("xaikit.client.connect_stt_websocket", fake)
    monkeypatch.setattr("xaikit.client.connect_tts_websocket", fake)
    monkeypatch.setattr("xaikit.client.connect_realtime_websocket", fake)
    monkeypatch.setattr("xaikit.async_client.connect_stt_websocket_async", fake_async)
    monkeypatch.setattr("xaikit.async_client.connect_tts_websocket_async", fake_async)
    monkeypatch.setattr("xaikit.async_client.connect_realtime_websocket_async", fake_async)

    http_base = "http://127.0.0.1:9/proxy/v1"
    https_base = "https://voice.example:8443/x/v1"
    sync = make_client(base_url=http_base)
    _quiet(sync.open_stt_session)
    _quiet(sync.open_tts_session)
    _quiet(sync.open_realtime_session)

    async def _open() -> None:
        async_client = make_client(AsyncXaiClient, base_url=https_base)
        await _quiet_async(async_client.open_stt_session())
        await _quiet_async(async_client.open_tts_session())
        await _quiet_async(async_client.open_realtime_session())

    asyncio.run(_open())

    uris = [item[0] for item in seen]
    assert any(uri.startswith("ws://127.0.0.1:9/proxy/v1/stt?") for uri in uris)
    assert any(uri.startswith("ws://127.0.0.1:9/proxy/v1/tts?") for uri in uris)
    assert any(uri.startswith("ws://127.0.0.1:9/proxy/v1/realtime?") for uri in uris)
    assert any(uri.startswith("wss://voice.example:8443/x/v1/stt?") for uri in uris)
    assert any(uri.startswith("wss://voice.example:8443/x/v1/tts?") for uri in uris)
    assert any(uri.startswith("wss://voice.example:8443/x/v1/realtime?model=") for uri in uris)
    for uri, headers in seen:
        assert uri.split(":", 1)[0] in {"ws", "wss"}
        assert headers == {"Authorization": f"Bearer {KEY}"}
        assert KEY not in uri
        parts = urlsplit(uri)
        assert "//" not in parts.path


def test_u1_6_sockets_connect(http_server) -> None:
    """The three sockets actually connect, sync and async, and keep the prefix."""
    from websockets.asyncio.server import serve

    records: list[dict[str, Any]] = []
    started = threading.Event()
    box: dict[str, Any] = {}

    async def handler(ws) -> None:  # type: ignore[no-untyped-def]
        request = ws.request
        path = request.path
        records.append(
            {
                "path": path,
                "authorization": request.headers.get("Authorization"),
            }
        )
        if path.split("?", 1)[0].endswith("/stt"):
            await ws.send(json.dumps({"type": "transcript.created"}))
        try:
            async for _message in ws:
                pass
        except Exception:
            return

    async def main() -> None:
        stop = asyncio.Event()
        box["stop"] = stop
        async with serve(handler, "127.0.0.1", 0) as server:
            box["port"] = server.sockets[0].getsockname()[1]
            started.set()
            await stop.wait()

    loop = asyncio.new_event_loop()

    def runner() -> None:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(main())

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    assert started.wait(5)
    port = box["port"]
    base = f"http://127.0.0.1:{port}/proxy/v1"
    try:
        sync = make_client(base_url=base)
        stt = sync.open_stt_session()
        tts = sync.open_tts_session()
        rt = sync.open_realtime_session()
        stt.close()
        tts.close()
        rt.close()

        async def _async_open() -> None:
            client = make_client(AsyncXaiClient, base_url=base)
            stt_session = await client.open_stt_session()
            tts_session = await client.open_tts_session()
            rt_session = await client.open_realtime_session()
            await stt_session.close()
            await tts_session.close()
            await rt_session.close()

        asyncio.run(_async_open())
    finally:
        loop.call_soon_threadsafe(box["stop"].set)
        thread.join(timeout=3)

    paths = [item["path"].split("?", 1)[0] for item in records]
    assert paths.count("/proxy/v1/stt") >= 2
    assert paths.count("/proxy/v1/tts") >= 2
    assert paths.count("/proxy/v1/realtime") >= 2
    for item in records:
        assert item["authorization"] == f"Bearer {KEY}"
        assert KEY not in item["path"]


def test_u1_7_trailing_slash_and_no_v1_append(monkeypatch: pytest.MonkeyPatch) -> None:
    capture = _Capture()
    capture.install(monkeypatch)
    slashed = make_client(base_url="http://127.0.0.1:9/proxy/v1/")
    plain = make_client(base_url="http://127.0.0.1:9/proxy/v1")
    _quiet(slashed.generate_image, "a cat")
    _quiet(plain.generate_image, "a cat")
    assert capture.calls[0][1] == capture.calls[1][1]
    assert "//" not in urlsplit(capture.calls[0][1]).path
    capture.calls.clear()
    short = make_client(base_url="http://127.0.0.1:9/proxy")
    _quiet(short.generate_image, "a cat")
    assert urlsplit(capture.calls[-1][1]).path == "/proxy/images/generations"


def test_u1_8_one_api_host_literal() -> None:
    hits: list[str] = []
    for path in (ROOT / "src" / "xaikit").rglob("*.py"):
        # management-api.x.ai is a different host and is not this literal.
        text = path.read_text(encoding="utf-8").replace("management-api.x.ai", "")
        for number, line in enumerate(text.splitlines(), 1):
            if "api.x.ai" in line:
                hits.append(f"{path.relative_to(ROOT)}:{number}:{line.strip()}")
    assert hits == [
        'src/xaikit/base_url.py:14:DEFAULT_BASE_URL = "https://api.x.ai/v1"'
    ]


def test_u1_9_docs_name_the_acceptance_rows() -> None:
    client_chat = (ROOT / "docs" / "features" / "ClientChat.md").read_text(encoding="utf-8")
    assert "XK-AC-URL-1" in client_chat
    assert "XK-AC-URL-2" in client_chat
    assert "2026-10-13" in client_chat
    assert "XAI_BASE_URL" in client_chat
    for name in ("RealtimeVoice.md", "MediaRest.md"):
        body = (ROOT / "docs" / "features" / name).read_text(encoding="utf-8")
        assert "XK-AC-URL-1" in body
        assert "XK-AC-URL-2" in body
        assert "ClientChat.md" in body
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "base_url" in readme
    assert "XAI_BASE_URL" in readme


def test_u2_1_proxy_parses_chat_image_models_and_async(http_server) -> None:
    base = http_server["base"]
    client = make_client(base_url=base)
    chat = client.chat([{"role": "user", "content": "hi"}])
    assert chat.content == "hello"
    image = client.generate_image("a cat")
    assert image["url"] == "http://127.0.0.1/img.png"

    inject_catalog(None)
    clear_catalog_cache()
    try:
        models = list_models(
            api_key=KEY,
            base_url=base,
            force_refresh=True,
            allow_fixture_fallback=False,
        )
    finally:
        inject_catalog(_FIXTURE)
        clear_catalog_cache()
    assert [row.id for row in models] == ["grok-from-proxy"]

    async def _image() -> dict[str, Any]:
        async_client = make_client(AsyncXaiClient, base_url=base)
        return await async_client.generate_image("a cat")

    assert asyncio.run(_image())["url"] == "http://127.0.0.1/img.png"
    paths = [rec["path"] for rec in http_server["records"]]
    assert "/proxy/v1/chat/completions" in paths
    assert paths.count("/proxy/v1/images/generations") >= 2
    assert "/proxy/v1/models" in paths
    for rec in http_server["records"]:
        _assert_auth(rec)


def test_u2_2_any_host_and_rejected_urls() -> None:
    accepted = [
        "https://proxy.corp.internal:9443/llm/xai/v1",
        "http://192.0.2.10/v1",
        "http://localhost:9/v1",
    ]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        for raw in accepted:
            client = make_client(base_url=raw)
            assert client.base_url == raw
    assert not any("api.x.ai" in str(item.message) for item in caught)

    samples = [
        "ftp://example.com/v1",
        "http:///no-host",
        "http://example.com/v1?q=1",
        "http://example.com/v1#frag",
        "http://user-SECRET:pass-SECRET@example.com/v1",
    ]
    for raw in samples:
        with pytest.raises(ValueError) as exc_info:
            make_client(base_url=raw)
        text = str(exc_info.value)
        assert "user-SECRET" not in text
        assert "pass-SECRET" not in text
        assert raw not in text


def test_u2_3_auth_matches_default(monkeypatch: pytest.MonkeyPatch) -> None:
    capture = _Capture()
    capture.install(monkeypatch)
    default = make_client()
    custom = make_client(base_url="http://127.0.0.1:9/proxy/v1")
    _quiet(default.generate_image, "a cat")
    _quiet(custom.generate_image, "a cat")
    assert len(capture.calls) >= 2
    default_headers = capture.calls[0][2]
    custom_headers = capture.calls[1][2]
    assert default_headers == custom_headers
    assert default_headers == {
        "Authorization": f"Bearer {KEY}",
        "Content-Type": "application/json",
    }
    assert KEY not in capture.calls[1][1]


def test_u2_4_default_urls_and_constants_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    assert XAI_STT_URL == HISTORICAL_URLS["stt"]
    assert XAI_TTS_URL == HISTORICAL_URLS["tts"]
    assert XAI_TTS_VOICES_URL == HISTORICAL_URLS["tts/voices"]
    assert XAI_IMAGES_URL == HISTORICAL_URLS["images/generations"]
    assert XAI_IMAGE_EDITS_URL == HISTORICAL_URLS["images/edits"]
    assert XAI_FILES_URL == HISTORICAL_URLS["files"]
    assert XAI_EMBEDDINGS_URL == HISTORICAL_URLS["embeddings"]
    assert XAI_TOKENIZE_URL == HISTORICAL_URLS["tokenize-text"]
    assert XAI_RESPONSES_URL == HISTORICAL_URLS["responses"]
    assert XAI_CHAT_COMPLETIONS_URL == HISTORICAL_URLS["chat/completions"]
    assert XAI_DEFERRED_CHAT_URL == HISTORICAL_URLS["chat/deferred-completion"]
    assert XAI_REALTIME_CLIENT_SECRETS_URL == HISTORICAL_URLS["realtime/client_secrets"]
    assert XAI_VIDEOS_URL == HISTORICAL_URLS["videos/generations"]
    assert XAI_VIDEO_EXTENSIONS_URL == HISTORICAL_URLS["videos/extensions"]
    assert XAI_VIDEO_STATUS_URL == HISTORICAL_URLS["videos/{request_id}"]
    assert XAI_STT_WS_URL == HISTORICAL_URLS["stt-ws"]
    assert XAI_TTS_WS_URL == HISTORICAL_URLS["tts-ws"]
    assert XAI_REALTIME_URL == HISTORICAL_URLS["realtime-ws"]
    import inspect

    assert inspect.signature(stt_session_url).parameters["base"].default == XAI_STT_WS_URL
    assert inspect.signature(tts_session_url).parameters["base"].default == XAI_TTS_WS_URL
    assert inspect.signature(realtime_session_url).parameters["base"].default == XAI_REALTIME_URL

    capture = _Capture()
    capture.install(monkeypatch)
    client = make_client()
    assert client.base_url == DEFAULT_BASE_URL
    _exercise_sync(client)
    by_path = {urlsplit(url).path: url for _method, url, _headers, _body in capture.calls}
    assert by_path["/v1/images/generations"] == XAI_IMAGES_URL
    assert by_path["/v1/stt"] == XAI_STT_URL
    assert by_path["/v1/videos/vid-1"] == XAI_VIDEO_STATUS_URL.format(request_id="vid-1")

    calls = {"sdk": 0, "rest": 0}

    def sdk(key: str) -> list[ModelInfo]:
        calls["sdk"] += 1
        return _FIXTURE

    def rest(key: str, base_url: str) -> list[ModelInfo]:
        calls["rest"] += 1
        return _FIXTURE

    monkeypatch.setattr("xaikit.catalog.fetch_models_from_sdk", sdk)
    monkeypatch.setattr("xaikit.catalog.fetch_models_via_rest", rest)
    inject_catalog(None)
    clear_catalog_cache()
    try:
        list_models(api_key=KEY, force_refresh=True, allow_fixture_fallback=False)
        assert calls == {"sdk": 1, "rest": 0}
        list_models(
            api_key=KEY,
            base_url=DEFAULT_BASE_URL,
            force_refresh=True,
            allow_fixture_fallback=False,
        )
        assert calls["rest"] == 0
        assert calls["sdk"] == 2
    finally:
        inject_catalog(_FIXTURE)
        clear_catalog_cache()


def test_u2_4_collections_and_batch_ignore_base(monkeypatch: pytest.MonkeyPatch, http_server) -> None:
    seen: list[str] = []

    def collections(self, method: str, **kwargs: Any) -> object:
        seen.append(f"collections:{method}")
        return object()

    def batch(self, method: str, **kwargs: Any) -> object:
        seen.append(f"batch:{method}")
        return object()

    monkeypatch.setattr(XaiClient, "_collections_rpc", collections)
    monkeypatch.setattr(XaiClient, "_batch_rpc", batch)
    monkeypatch.setattr("xaikit.client.collection_to_dict", lambda raw: {"id": "c", "name": "n"})
    monkeypatch.setattr("xaikit.client.batch_to_dict", lambda raw: {"id": "b", "name": "n"})
    client = make_client(base_url=http_server["base"])
    before = len(http_server["records"])
    assert client.create_collection("notes")["id"] == "c"
    assert client.create_batch("job")["id"] == "b"
    assert seen == ["collections:create", "batch:create"]
    assert http_server["records"][before:] == []


def test_u2_5_key_never_in_repr_logs_or_userinfo_errors(caplog: pytest.LogCaptureFixture) -> None:
    client = make_client(base_url="http://127.0.0.1:9/proxy/v1")
    assert KEY not in repr(client)
    with pytest.raises(ValueError) as exc_info:
        make_client(base_url="http://user-SECRET:pass-SECRET@example.com/v1")
    text = str(exc_info.value)
    assert "user-SECRET" not in text
    assert "pass-SECRET" not in text
    assert KEY not in text
    with caplog.at_level(logging.DEBUG, logger="xaikit"):
        client = make_client()
    assert KEY not in caplog.text


def test_injected_provider_wins_over_rest_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    """An injected provider is the chat transport, including on a path-prefixed base."""
    from xaikit.provider import MockChatProvider

    capture = _Capture()
    capture.install(monkeypatch)
    provider = MockChatProvider("from-provider")

    sync = make_client(
        base_url="http://127.0.0.1:9/proxy/v1",
        provider=provider,
    )
    reply = sync.chat([{"role": "user", "content": "hi"}])
    assert reply.content == "from-provider"
    assert provider.calls
    assert provider.calls[-1]["kind"] == "complete"
    assert capture.calls == []

    async def _go() -> None:
        async_provider = MockChatProvider("from-async-provider")
        client = make_client(
            AsyncXaiClient,
            base_url="http://127.0.0.1:9/proxy/v1",
            provider=async_provider,
        )
        got = await client.chat([{"role": "user", "content": "hi"}])
        assert got.content == "from-async-provider"
        assert async_provider.calls
        assert capture.calls == []

    asyncio.run(_go())


def test_path_prefix_chat_stream_is_rest_sse(monkeypatch: pytest.MonkeyPatch) -> None:
    """chat_stream on a path-prefixed base is SSE on POST <base>/chat/completions."""
    lines = [
        'data: {"choices":[{"delta":{"content":"Hi"},"finish_reason":null}]}',
        'data: {"choices":[{"delta":{"content":"!"},"finish_reason":"stop"}],"usage":{"total_tokens":2}}',
        "data: [DONE]",
    ]

    def _forbid_grpc(self, *args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        raise AssertionError("chat_stream used gRPC")

    monkeypatch.setattr("xaikit.provider.SdkChatProvider.stream", _forbid_grpc)
    monkeypatch.setattr("xaikit.provider.AsyncSdkChatProvider.stream", _forbid_grpc)

    seen: list[dict[str, Any]] = []

    class _SyncStream:
        status_code = 200
        reason_phrase = "OK"
        text = ""

        def __enter__(self) -> _SyncStream:
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def iter_lines(self):  # type: ignore[no-untyped-def]
            yield from lines

        def read(self) -> bytes:
            return b""

    def fake_stream(method: str, url: str, **kwargs: Any) -> _SyncStream:
        seen.append({"method": method, "url": url, "json": kwargs.get("json"), "headers": kwargs.get("headers")})
        return _SyncStream()

    monkeypatch.setattr("xaikit.client.httpx.stream", fake_stream)
    sync = make_client(base_url="http://127.0.0.1:9/proxy/v1")
    chunks = list(sync.chat_stream([{"role": "user", "content": "hi"}]))
    assert seen[-1]["method"] == "POST"
    assert urlsplit(seen[-1]["url"]).path == "/proxy/v1/chat/completions"
    assert seen[-1]["json"]["stream"] is True
    assert seen[-1]["headers"]["Authorization"] == f"Bearer {KEY}"
    assert "".join(chunk.delta for chunk in chunks) == "Hi!"
    assert chunks[-1].accumulated == "Hi!"
    assert chunks[-1].finish_reason == "stop"

    class _AsyncStream:
        status_code = 200
        reason_phrase = "OK"

        async def __aenter__(self) -> _AsyncStream:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def aiter_lines(self):  # type: ignore[no-untyped-def]
            for line in lines:
                yield line

        async def aread(self) -> bytes:
            return b""

    class _AsyncHttp:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            return None

        def stream(self, method: str, url: str, **kwargs: Any) -> _AsyncStream:
            seen.append(
                {"method": method, "url": url, "json": kwargs.get("json"), "headers": kwargs.get("headers")}
            )
            return _AsyncStream()

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr("xaikit.async_client.httpx.AsyncClient", _AsyncHttp)

    async def _go() -> None:
        client = make_client(AsyncXaiClient, base_url="http://127.0.0.1:9/proxy/v1")
        got = [chunk async for chunk in client.chat_stream([{"role": "user", "content": "hi"}])]
        assert "".join(chunk.delta for chunk in got) == "Hi!"
        assert urlsplit(seen[-1]["url"]).path == "/proxy/v1/chat/completions"
        assert seen[-1]["json"]["stream"] is True

    asyncio.run(_go())


def test_rest_chat_applies_kit_wire_adapters(monkeypatch: pytest.MonkeyPatch) -> None:
    """REST chat sends function tools, named tool_choice, schema, and assistant tool_calls."""
    from pydantic import BaseModel

    class _Item(BaseModel):
        name: str

    capture = _Capture()
    capture.install(monkeypatch)
    client = make_client(base_url="http://127.0.0.1:9/proxy/v1")
    _quiet(
        client.chat,
        [
            {"role": "user", "content": "weather?"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "c1", "name": "get_weather", "arguments": {"city": "NYC"}},
                ],
            },
            {"role": "tool", "content": "72F", "tool_call_id": "c1"},
        ],
        tools=[
            {
                "name": "get_weather",
                "description": "Get the weather",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            }
        ],
        tool_choice={"name": "get_weather"},
    )
    body = capture.calls[-1][3]
    assert isinstance(body, dict)
    tool = body["tools"][0]
    assert tool["type"] == "function"
    assert tool["function"]["name"] == "get_weather"
    assert tool["function"]["parameters"]["required"] == ["city"]
    assert body["tool_choice"] == {"type": "function", "function": {"name": "get_weather"}}
    assistant = body["messages"][1]
    assert assistant["tool_calls"][0]["function"]["name"] == "get_weather"
    assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {"city": "NYC"}
    assert body["messages"][2]["role"] == "tool"
    assert body["messages"][2]["tool_call_id"] == "c1"

    capture.calls.clear()
    _quiet(client.chat_json, "item", schema=_Item)
    schema_body = capture.calls[-1][3]
    fmt = schema_body["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["schema"]["properties"]["name"]["type"] == "string"


def test_rest_empty_content_list_matches_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty part lists become "" . Assistant tool calls with empty content send null."""
    capture = _Capture()
    capture.install(monkeypatch)
    client = make_client(base_url="http://127.0.0.1:9/proxy/v1")
    _quiet(
        client.chat,
        [
            {"role": "user", "content": []},
            {
                "role": "assistant",
                "content": [],
                "tool_calls": [
                    {"id": "c1", "name": "get_weather", "arguments": {"city": "NYC"}},
                ],
            },
            {"role": "tool", "content": "72F", "tool_call_id": "c1"},
        ],
    )
    messages = capture.calls[-1][3]["messages"]
    assert messages[0]["content"] == ""
    assert messages[1]["content"] is None
    assert messages[1]["tool_calls"][0]["function"]["name"] == "get_weather"


def test_batch_and_collections_stay_on_sdk_default_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Custom api_host is only the chat gRPC client. Batch and collections keep SDK defaults."""
    opened: list[Any] = []

    class Dummy:
        def __init__(self, api_key: str, management_api_key: str | None = None, **kwargs: Any) -> None:
            self.kwargs = kwargs
            opened.append(self)

        def close(self) -> None:
            return None

    monkeypatch.setattr("xaikit.client.Client", Dummy)
    monkeypatch.setattr("xaikit.async_client.AsyncClient", Dummy)

    bare = make_client(base_url="http://127.0.0.1:9")
    assert bare._provider._client.kwargs.get("api_host") == "127.0.0.1:9"
    assert bare._provider._client.kwargs.get("use_insecure_channel") is True
    assert "api_host" not in bare._client.kwargs
    assert "use_insecure_channel" not in bare._client.kwargs
    assert bare._client is not bare._provider._client

    prefixed = make_client(base_url="http://127.0.0.1:9/proxy/v1")
    assert "api_host" not in prefixed._client.kwargs
    assert "use_insecure_channel" not in prefixed._client.kwargs

    default = make_client()
    assert default._client is default._provider._client
    assert "api_host" not in default._client.kwargs

    seen: list[Any] = []

    def _rpc(operation: str, *, sdk_client: Any = None, **kwargs: Any) -> dict[str, str]:
        seen.append(sdk_client)
        return {"id": "b1", "name": "n"}

    monkeypatch.setattr("xaikit.client.call_batch_rpc", _rpc)
    monkeypatch.setattr("xaikit.client.call_collections_rpc", _rpc)
    prefixed.create_batch("job")
    prefixed.create_collection("notes")
    assert seen
    assert all(client is prefixed._client for client in seen)
    assert all("api_host" not in client.kwargs for client in seen)

    async def _go() -> None:
        opened.clear()
        client = make_client(AsyncXaiClient, base_url="https://example.com/v1")
        assert client._provider._client.kwargs.get("api_host") == "example.com"
        assert "api_host" not in client._client.kwargs
        assert client._client is not client._provider._client
        proxy = make_client(AsyncXaiClient, base_url="http://127.0.0.1:9/proxy/v1")
        assert "api_host" not in proxy._client.kwargs

    asyncio.run(_go())


def test_rest_content_parts_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each kit content part reaches REST with the same fields the SDK path sends."""
    raw = b"\x00\x01inline-file"
    capture = _Capture()
    capture.install(monkeypatch)
    client = make_client(base_url="http://127.0.0.1:9/proxy/v1")
    _quiet(
        client.chat,
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "look"},
                    {"type": "image_url", "url": "https://example.com/a.png", "detail": "high"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "https://example.com/b.png", "detail": "low"},
                    },
                    {"type": "image", "url": "https://example.com/c.png"},
                    {"type": "file", "file_id": "file-1"},
                    {
                        "type": "file",
                        "data": raw,
                        "filename": "note.txt",
                        "mime_type": "text/plain",
                    },
                    {
                        "type": "file",
                        "url": "https://example.com/d.pdf",
                        "filename": "d.pdf",
                        "mime_type": "application/pdf",
                    },
                    {"type": "file_id", "id": "file-2"},
                    {"type": "video_url", "url": "https://example.com/v.mp4"},
                    {"type": "video", "file_id": "vid-1"},
                    "tail",
                ],
            }
        ],
    )
    body = capture.calls[-1][3]
    parts = body["messages"][0]["content"]
    assert parts == [
        {"type": "text", "text": "look"},
        {"type": "image_url", "url": "https://example.com/a.png", "detail": "high"},
        {"type": "image_url", "url": "https://example.com/b.png", "detail": "low"},
        {"type": "image_url", "url": "https://example.com/c.png", "detail": "auto"},
        {"type": "file", "file_id": "file-1"},
        {
            "type": "file",
            "data": base64.b64encode(raw).decode("ascii"),
            "filename": "note.txt",
            "mime_type": "text/plain",
        },
        {
            "type": "file",
            "url": "https://example.com/d.pdf",
            "filename": "d.pdf",
            "mime_type": "application/pdf",
        },
        {"type": "file", "file_id": "file-2"},
        {"type": "video_url", "url": "https://example.com/v.mp4", "mime_type": "video/mp4"},
        {"type": "video_url", "file_id": "vid-1"},
        {"type": "text", "text": "tail"},
    ]
    encoded = next(part["data"] for part in parts if part.get("type") == "file" and "data" in part)
    assert base64.b64decode(encoded) == raw


def test_m14_clients_do_not_share_a_resolved_base(monkeypatch: pytest.MonkeyPatch) -> None:
    capture = _Capture()
    capture.install(monkeypatch)
    first = make_client(base_url="http://127.0.0.1:9/proxy/a")
    second = make_client(base_url="http://127.0.0.1:9/proxy/b")
    _quiet(first.generate_image, "a cat")
    _quiet(second.generate_image, "a cat")
    assert urlsplit(capture.calls[0][1]).path == "/proxy/a/images/generations"
    assert urlsplit(capture.calls[1][1]).path == "/proxy/b/images/generations"
    assert first.base_url != second.base_url
