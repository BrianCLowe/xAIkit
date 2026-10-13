"""CUT-2026-10-13-xk-regional-endpoint.

Graded cases R1-1..R1-8 and R2-1..R2-6, sync and async.
BLOCK mutants M1..M14 must fail at least one test here.
Offline only: loopback mock, socket guard, fake key.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from xaikit import AsyncXaiClient, XaiClient
from xaikit.catalog import (
    cached_catalog,
    catalog_source,
    clear_catalog_cache,
    inject_catalog,
    resolve_model,
)
from xaikit.provider import MockChatProvider
from xaikit.types import ModelInfo

KEY = "xai-test-FAKE"
CHAT_PAIR = ("grok-4.7", "grok-4.6")

pytestmark = pytest.mark.parametrize("cls", [XaiClient, AsyncXaiClient])


def _chat_tagged(ids: list[str]) -> dict[str, Any]:
    """REST shape that tags every model as chat. Roles must not be read from this."""
    return {
        "data": [
            {
                "id": mid,
                "object": "model",
                "role": "chat",
                "capabilities": ["chat"],
            }
            for mid in ids
        ]
    }


@pytest.fixture(autouse=True)
def _clean_catalog():
    inject_catalog(None)
    clear_catalog_cache()
    yield
    inject_catalog(None)
    clear_catalog_cache()


@pytest.fixture(autouse=True)
def _loopback_only(monkeypatch: pytest.MonkeyPatch):
    """Fail on any non-loopback TCP connect. api.x.ai must never be dialed."""

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


def _start_host(
    ids: list[str] | None = None,
    *,
    status: int = 200,
    body: Any = None,
    raw: bytes | None = None,
    delay: float = 0.0,
) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "ids": list(ids if ids is not None else CHAT_PAIR),
        "status": status,
        "body": body,
        "raw": raw,
        "delay": delay,
    }
    records: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def _serve(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            raw_body = self.rfile.read(length) if length else b""
            path = self.path.split("?", 1)[0]
            records.append(
                {
                    "method": self.command,
                    "path": path,
                    "authorization": self.headers.get("Authorization"),
                    "body": raw_body,
                }
            )
            if cfg["delay"] and path.endswith("/models"):
                time.sleep(cfg["delay"])
            if path.endswith("/models"):
                if cfg["raw"] is not None:
                    payload = cfg["raw"]
                    code = cfg["status"]
                    content_type = "text/plain"
                else:
                    code = cfg["status"]
                    content_type = "application/json"
                    if cfg["body"] is not None:
                        payload = json.dumps(cfg["body"]).encode()
                    elif code >= 400:
                        payload = b'{"error":"nope"}'
                    else:
                        payload = json.dumps(_chat_tagged(list(cfg["ids"]))).encode()
            elif path.endswith("/chat/completions"):
                code = 200
                content_type = "application/json"
                model = "grok-4.7"
                try:
                    model = str(json.loads(raw_body.decode() or "{}").get("model") or model)
                except json.JSONDecodeError:
                    pass
                payload = json.dumps(
                    {
                        "choices": [
                            {
                                "message": {"role": "assistant", "content": "ok"},
                                "finish_reason": "stop",
                            }
                        ],
                        "model": model,
                    }
                ).encode()
            elif path.endswith("/images/generations") or path.endswith("/images/edits"):
                code = 200
                content_type = "application/json"
                payload = json.dumps(
                    {"data": [{"url": "http://127.0.0.1/img.png"}]}
                ).encode()
            elif path.endswith("/videos/generations"):
                code = 200
                content_type = "application/json"
                payload = json.dumps({"request_id": "vid-1"}).encode()
            elif path.endswith("/tts"):
                code = 200
                content_type = "audio/mpeg"
                payload = b"audio"
            elif path.endswith("/stt"):
                code = 200
                content_type = "application/json"
                payload = json.dumps({"text": "hello"}).encode()
            else:
                code = 200
                content_type = "application/json"
                payload = b'{"ok":true}'
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:  # noqa: N802
            self._serve()

        def do_POST(self) -> None:  # noqa: N802
            self._serve()

        def log_message(self, fmt: str, *args: Any) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = int(server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return {
        "server": server,
        "thread": thread,
        "port": port,
        "host": f"127.0.0.1:{port}",
        "base": f"http://127.0.0.1:{port}/v1",
        "rest": f"http://127.0.0.1:{port}/region/v1",
        "records": records,
        "cfg": cfg,
    }


def _stop(host: dict[str, Any]) -> None:
    host["server"].shutdown()
    host["thread"].join(timeout=2)


@pytest.fixture
def host():
    started = _start_host()
    try:
        yield started
    finally:
        _stop(started)


def _call(client: Any, name: str, *args: Any, **kwargs: Any) -> Any:
    out = getattr(client, name)(*args, **kwargs)
    if asyncio.iscoroutine(out):
        return asyncio.run(out)
    return out


def _make(cls: type, **kwargs: Any) -> Any:
    params: dict[str, Any] = {"api_key": KEY}
    params.update(kwargs)
    return cls(**params)


def _model_gets(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in records if row["path"].endswith("/models") and row["method"] == "GET"]


def _paths_ending(records: list[dict[str, Any]], suffix: str) -> list[dict[str, Any]]:
    return [row for row in records if row["path"].endswith(suffix)]


def _catalog_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        rec
        for rec in caplog.records
        if rec.name == "xaikit.catalog" and rec.levelno >= logging.WARNING
    ]


def _assert_no_api_host(records: list[dict[str, Any]]) -> None:
    for row in records:
        assert "api.x.ai" not in row["path"]
        assert KEY not in row["path"]


def test_r1_1_best_and_economy_use_listed_ids(cls, host) -> None:
    """Best chat is grok-4.7. Economy follows shipped pricing (one price band)."""
    best = _make(cls, base_url=host["base"], intent="best", provider=MockChatProvider("ok"))
    economy = _make(
        cls, base_url=host["base"], intent="economy", provider=MockChatProvider("ok")
    )
    assert best.model == "grok-4.7"
    assert economy.model == "grok-4.7"
    assert best.model in CHAT_PAIR
    assert economy.model in CHAT_PAIR
    _assert_no_api_host(host["records"])


def test_r1_2_injected_newer_ids_stay_out(cls, host) -> None:
    inject_catalog(
        [
            ModelInfo(id="grok-5", capabilities=["chat"], input_per_million=3.0, created=50),
            ModelInfo(id="grok-4.8", capabilities=["chat"], input_per_million=0.4, created=40),
            ModelInfo(id="grok-4.7", capabilities=["chat"], input_per_million=2.0, created=30),
            ModelInfo(id="grok-4.6", capabilities=["chat"], input_per_million=1.0, created=20),
        ]
    )
    best = _make(cls, base_url=host["base"], intent="best", provider=MockChatProvider("ok"))
    economy = _make(
        cls, base_url=host["base"], intent="economy", provider=MockChatProvider("ok")
    )
    assert best.model == "grok-4.7"
    assert economy.model == "grok-4.6"


def test_r1_3_fetch_once_per_client_no_ttl(cls, host, monkeypatch: pytest.MonkeyPatch) -> None:
    inject_catalog(
        [ModelInfo(id="grok-marker", capabilities=["chat"], input_per_million=1.0, created=1)]
    )
    clear_catalog_cache()
    before = list(list_models_ids())
    source = catalog_source()

    provider = MockChatProvider("ok")
    client = _make(cls, base_url=host["base"], intent="best", provider=provider)
    assert client.model == "grok-4.7"
    assert client.model == "grok-4.7"
    assert client.model == "grok-4.7"
    _call(client, "chat", [{"role": "user", "content": "hi"}])
    _call(client, "chat", [{"role": "user", "content": "again"}])
    assert len(_model_gets(host["records"])) == 1

    monkeypatch.setattr("xaikit.catalog.time.time", lambda: 10**10)
    assert client.model == "grok-4.7"
    assert len(_model_gets(host["records"])) == 1

    other = _make(cls, base_url=host["base"], intent="best", provider=MockChatProvider("ok"))
    assert other.model == "grok-4.7"
    assert len(_model_gets(host["records"])) == 2

    assert catalog_source() == source
    assert list_models_ids() == before
    _assert_no_api_host(host["records"])


def list_models_ids() -> list[str]:
    rows = cached_catalog()
    if rows is None:
        from xaikit.catalog import list_models

        rows = list_models()
    return [row.id for row in rows]


def test_r1_4_pins_pass_through(cls, host, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="xaikit.catalog")
    pinned = _make(
        cls,
        base_url=host["rest"],
        model="grok-4-fast",
        intent="best",
    )
    _call(pinned, "chat", [{"role": "user", "content": "hi"}])
    per_call = _make(cls, base_url=host["rest"], intent="best")
    _call(per_call, "chat", [{"role": "user", "content": "hi"}], model="grok-4-fast")
    chats = _paths_ending(host["records"], "/chat/completions")
    assert len(chats) == 2
    for row in chats:
        assert json.loads(row["body"].decode())["model"] == "grok-4-fast"
    assert _catalog_warnings(caplog) == []

    provider = MockChatProvider("ok")
    grpc_pin = _make(
        cls,
        base_url=host["base"],
        model="grok-4-fast",
        intent="best",
        provider=provider,
    )
    _call(grpc_pin, "chat", [{"role": "user", "content": "hi"}])
    assert provider.calls[-1]["model"] == "grok-4-fast"
    per_provider = MockChatProvider("ok")
    grpc_call = _make(cls, base_url=host["base"], intent="best", provider=per_provider)
    _call(grpc_call, "chat", [{"role": "user", "content": "hi"}], model="grok-4-fast")
    assert per_provider.calls[-1]["model"] == "grok-4-fast"
    assert _catalog_warnings(caplog) == []


def test_r1_5_models_request_uses_bearer(cls, host) -> None:
    client = _make(cls, base_url=host["base"], intent="best", provider=MockChatProvider("ok"))
    assert client.model == "grok-4.7"
    gets = _model_gets(host["records"])
    assert len(gets) == 1
    assert gets[0]["authorization"] == f"Bearer {KEY}"
    assert KEY not in gets[0]["path"]
    assert "api.x.ai" not in gets[0]["path"]


def test_r1_6_default_host_unchanged(
    cls, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control. Resolution matches resolve_model and no REST /v1/models call is made."""
    caplog.set_level(logging.WARNING, logger="xaikit.catalog")
    regional_fetches: list[str] = []

    def _refuse_regional_fetch(api_key: str, base_url: str) -> None:
        regional_fetches.append(base_url)
        raise AssertionError(f"non-loopback connection to {base_url}")

    monkeypatch.setattr("xaikit.client.fetch_host_catalog", _refuse_regional_fetch)
    catalog = [
        ModelInfo(id="grok-4.7", capabilities=["chat"], input_per_million=2.0, created=20),
        ModelInfo(id="grok-4.3", capabilities=["chat"], input_per_million=1.25, created=10),
        ModelInfo(id="grok-imagine-image-quality", capabilities=["image"], created=30),
        ModelInfo(id="grok-imagine-image", capabilities=["image"], created=10),
        ModelInfo(id="grok-imagine-video-1.5", capabilities=["video"], created=20),
        ModelInfo(id="grok-imagine-video", capabilities=["video"], created=10),
        ModelInfo(id="grok-voice-latest", capabilities=["voice"], created=20),
        ModelInfo(id="grok-voice-think-fast-1.0", capabilities=["voice"], created=10),
    ]
    inject_catalog(catalog)
    clear_catalog_cache()
    expected = {
        role: resolve_model(catalog=catalog, intent="best", role=role)
        for role in ("chat", "image", "video", "voice")
    }
    plain = _make(cls, intent="best", provider=MockChatProvider("ok"))
    explicit = _make(
        cls,
        intent="best",
        provider=MockChatProvider("ok"),
        base_url="https://api.x.ai/v1",
    )
    for client in (plain, explicit):
        assert client.model == expected["chat"]
        assert client.image_model == expected["image"]
        assert client.video_model == expected["video"]
        assert client.voice_model == expected["voice"]
    assert regional_fetches == []
    assert _catalog_warnings(caplog) == []


def test_r1_7_trailing_slash_is_default_other_bases_are_not(cls, host) -> None:
    catalog = [
        ModelInfo(id="grok-5", capabilities=["chat"], input_per_million=3.0, created=90),
        ModelInfo(id="grok-4.7", capabilities=["chat"], input_per_million=2.0, created=20),
        ModelInfo(id="grok-4.3", capabilities=["chat"], input_per_million=1.25, created=10),
        ModelInfo(id="grok-imagine-image", capabilities=["image"], created=10),
        ModelInfo(id="grok-imagine-video-1.5", capabilities=["video"], created=10),
        ModelInfo(id="grok-voice-latest", capabilities=["voice"], created=10),
    ]
    inject_catalog(catalog)
    clear_catalog_cache()
    before = len(host["records"])
    plain = _make(cls, intent="best", provider=MockChatProvider("ok"))
    slashed = _make(
        cls,
        intent="best",
        provider=MockChatProvider("ok"),
        base_url="https://api.x.ai/v1/",
    )
    assert slashed.base_url == "https://api.x.ai/v1"
    assert slashed.model == plain.model
    assert slashed.image_model == plain.image_model
    assert slashed.video_model == plain.video_model
    assert slashed.voice_model == plain.voice_model
    assert host["records"][before:] == []

    regional = _make(cls, base_url=host["base"], intent="best", provider=MockChatProvider("ok"))
    other_path = _make(
        cls, base_url=host["rest"], intent="best", provider=MockChatProvider("ok")
    )
    assert regional.model == "grok-4.7"
    assert other_path.model == "grok-4.7"
    assert len(_model_gets(host["records"])) == 2


def test_r1_8_docs_name_the_acceptance_rows(cls) -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    catalog = (root / "docs/features/Catalog.md").read_text(encoding="utf-8")
    chat = (root / "docs/features/ClientChat.md").read_text(encoding="utf-8")
    assert "XK-AC-REGION-1" in catalog
    assert "XK-AC-REGION-2" in catalog
    assert "2026-10-13" in catalog
    assert "10% US" in catalog
    assert "XK-AC-REGION-1" in chat
    assert "XK-AC-REGION-2" in chat
    assert "Catalog.md" in chat


def test_r2_1_missing_role_raises_before_request(cls, host) -> None:
    import xaikit

    assert issubclass(xaikit.RoleUnavailableOnHost, xaikit.XaiKitError)
    client = _make(cls, base_url=host["base"], intent="best", provider=MockChatProvider("ok"))
    assert client.model == "grok-4.7"
    before = len(host["records"])
    calls = (
        ("generate_image", ("cat",), {}),
        ("generate_video", ("clip",), {"into": [], "wait": False}),
        ("synthesize_speech", ("hi",), {}),
        ("transcribe", (b"abc",), {}),
        ("open_realtime_session", (), {}),
        ("open_stt_session", (), {}),
        ("open_tts_session", (), {}),
    )
    for name, args, kwargs in calls:
        with pytest.raises(xaikit.RoleUnavailableOnHost):
            _call(client, name, *args, **kwargs)
    assert host["records"][before:] == []
    assert _paths_ending(host["records"], "/images/generations") == []
    assert _paths_ending(host["records"], "/videos/generations") == []
    assert _paths_ending(host["records"], "/tts") == []
    assert _paths_ending(host["records"], "/stt") == []
    _assert_no_api_host(host["records"])


def test_r2_2_error_names_role_and_host(cls, host) -> None:
    import xaikit

    client = _make(cls, base_url=host["base"], intent="best", provider=MockChatProvider("ok"))
    expected = {
        "generate_image": ("image", ("cat",), {}),
        "generate_video": ("video", ("clip",), {"into": [], "wait": False}),
        "synthesize_speech": ("voice", ("hi",), {}),
        "open_realtime_session": ("voice", (), {}),
        "open_tts_session": ("voice", (), {}),
        "transcribe": ("speech-to-text", (b"abc",), {}),
        "open_stt_session": ("speech-to-text", (), {}),
    }
    for name, (role, args, kwargs) in expected.items():
        with pytest.raises(xaikit.RoleUnavailableOnHost) as caught:
            _call(client, name, *args, **kwargs)
        err = caught.value
        assert err.role == role
        assert err.host == host["host"]
        assert role in str(err)
        assert host["host"] in str(err)


def test_r2_3_pinned_role_model_passes_through(cls, host, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="xaikit.catalog")
    pinned = _make(
        cls,
        base_url=host["base"],
        intent="best",
        image_model="grok-imagine-image",
        provider=MockChatProvider("ok"),
    )
    _call(pinned, "generate_image", "cat")
    per_call = _make(cls, base_url=host["base"], intent="best", provider=MockChatProvider("ok"))
    _call(per_call, "generate_image", "cat", model="grok-imagine-image")
    posts = _paths_ending(host["records"], "/images/generations")
    assert len(posts) == 2
    for row in posts:
        assert json.loads(row["body"].decode())["model"] == "grok-imagine-image"
    assert _catalog_warnings(caplog) == []
    _assert_no_api_host(host["records"])


@pytest.mark.parametrize("mode", ["500", "empty", "nonjson", "timeout", "refused"])
def test_r2_4_models_failure_warns_and_uses_static_catalog(
    cls, mode, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    caplog.set_level(logging.WARNING, logger="xaikit.catalog")
    if mode == "refused":
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])
        sock.close()
        base = f"http://127.0.0.1:{port}/v1"
        label = f"127.0.0.1:{port}"
        client = _make(cls, base_url=base, intent="best", provider=MockChatProvider("ok"))
        assert client.model == "grok-4.7"
        from xaikit.client import XAI_IMAGES_URL

        image_url = client._endpoint(XAI_IMAGES_URL)
        assert image_url == f"http://127.0.0.1:{port}/v1/images/generations"
        assert "api.x.ai" not in image_url
        with pytest.raises(RuntimeError) as caught:
            _call(client, "generate_image", "cat")
        text = str(caught.value)
        assert "api.x.ai" not in text
        assert "Connection refused" in text or "connection attempts failed" in text
    else:
        if mode == "timeout":
            monkeypatch.setattr("xaikit.catalog.HOST_MODELS_TIMEOUT_SECONDS", 0.15)
            started = _start_host(status=200, delay=0.6)
        elif mode == "500":
            started = _start_host(status=500)
        elif mode == "empty":
            started = _start_host(body={"data": []})
        else:
            started = _start_host(raw=b"not-json")
        try:
            client = _make(
                cls, base_url=started["base"], intent="best", provider=MockChatProvider("ok")
            )
            assert client.model == "grok-4.7"
            _call(client, "generate_image", "cat")
            posts = _paths_ending(started["records"], "/images/generations")
            assert len(posts) == 1
            assert posts[0]["path"].startswith(f"/v1/")
            body = json.loads(posts[0]["body"].decode())
            assert body["model"] == "grok-imagine-image-quality"
            assert "api.x.ai" not in posts[0]["path"]
            label = started["host"]
        finally:
            _stop(started)
    warnings = _catalog_warnings(caplog)
    assert len(warnings) == 1
    assert label in warnings[0].getMessage()
    assert client.model == "grok-4.7"
    assert len(_catalog_warnings(caplog)) == 1


def test_r2_4_warning_is_once_per_client(cls, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="xaikit.catalog")
    first = _start_host(status=500)
    second = _start_host(status=500)
    try:
        left = _make(cls, base_url=first["base"], intent="best", provider=MockChatProvider("ok"))
        right = _make(
            cls, base_url=second["base"], intent="best", provider=MockChatProvider("ok")
        )
        assert left.model == "grok-4.7"
        assert right.model == "grok-4.7"
        assert left.model == "grok-4.7"
        warnings = _catalog_warnings(caplog)
        assert len(warnings) == 2
        assert first["host"] in warnings[0].getMessage()
        assert second["host"] in warnings[1].getMessage()
    finally:
        _stop(first)
        _stop(second)


def test_r2_5_no_silent_fallback_to_api(cls, host) -> None:
    import xaikit

    client = _make(cls, base_url=host["base"], intent="best", provider=MockChatProvider("ok"))
    with pytest.raises(xaikit.RoleUnavailableOnHost):
        _call(client, "generate_image", "cat")
    _assert_no_api_host(host["records"])
    assert all("api.x.ai" not in row["path"] for row in host["records"])


def test_r2_6_async_matches_sync_contract(cls, host, caplog: pytest.LogCaptureFixture) -> None:
    """R2-1, R2-2, and R2-4 hold for both clients. This case names the async half."""
    if cls is not AsyncXaiClient:
        client = _make(cls, base_url=host["base"], intent="best", provider=MockChatProvider("ok"))
        assert client.model == "grok-4.7"
        return
    import xaikit

    caplog.set_level(logging.WARNING, logger="xaikit.catalog")
    client = _make(cls, base_url=host["base"], intent="best")
    with pytest.raises(xaikit.RoleUnavailableOnHost) as caught:
        asyncio.run(client.generate_image("cat"))
    assert caught.value.role == "image"
    assert caught.value.host == host["host"]
    assert _paths_ending(host["records"], "/images/generations") == []
    failed = _start_host(status=500)
    try:
        fallback = _make(cls, base_url=failed["base"], intent="best")
        assert fallback.model == "grok-4.7"
        asyncio.run(fallback.generate_image("cat"))
        posts = _paths_ending(failed["records"], "/images/generations")
        assert len(posts) == 1
        assert "api.x.ai" not in posts[0]["path"]
        warnings = _catalog_warnings(caplog)
        assert len(warnings) == 1
        assert failed["host"] in warnings[0].getMessage()
    finally:
        _stop(failed)


def test_m5_clients_do_not_share_a_host_cache(cls) -> None:
    first = _start_host(["grok-4.7"])
    second = _start_host(["grok-4.6"])
    try:
        left = _make(cls, base_url=first["base"], intent="best", provider=MockChatProvider("ok"))
        right = _make(
            cls, base_url=second["base"], intent="best", provider=MockChatProvider("ok")
        )
        assert left.model == "grok-4.7"
        assert right.model == "grok-4.6"
        assert len(_model_gets(first["records"])) == 1
        assert len(_model_gets(second["records"])) == 1
    finally:
        _stop(first)
        _stop(second)


def test_m14_role_comes_from_static_catalog_not_rest_tag(cls) -> None:
    """REST tags every id as chat. A known image id stays image. An unknown id is chat."""
    import xaikit

    known = _start_host(["grok-4.7", "grok-imagine-image"])
    try:
        client = _make(cls, base_url=known["base"], intent="best", provider=MockChatProvider("ok"))
        assert client.model == "grok-4.7"
        assert client.image_model == "grok-imagine-image"
        _call(client, "generate_image", "cat")
        posts = _paths_ending(known["records"], "/images/generations")
        assert len(posts) == 1
        assert json.loads(posts[0]["body"].decode())["model"] == "grok-imagine-image"
        assert len(_model_gets(known["records"])) == 1
    finally:
        _stop(known)

    unknown = _start_host(
        body={
            "data": [
                {
                    "id": "grok-imagine-image-not-in-catalog",
                    "object": "model",
                    "role": "image",
                    "capabilities": ["image"],
                }
            ]
        }
    )
    try:
        client = _make(
            cls, base_url=unknown["base"], intent="best", provider=MockChatProvider("ok")
        )
        assert client.model == "grok-imagine-image-not-in-catalog"
        with pytest.raises(xaikit.RoleUnavailableOnHost) as caught:
            _call(client, "generate_image", "cat")
        assert caught.value.role == "image"
        assert _paths_ending(unknown["records"], "/images/generations") == []
    finally:
        _stop(unknown)
