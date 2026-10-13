"""CUT-2026-10-13-xk-region-meter-premium.

Graded cases RM1-1..RM1-11 and RM2-1..RM2-7, sync and async.
BLOCK mutants M1..M17 must fail at least one test here.
Offline only: loopback mock, socket guard, fake key.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import socket
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest

from xaikit import AsyncXaiClient, InMemoryUsageSink, UsageMeter, XaiClient
from xaikit.catalog import clear_catalog_cache, inject_catalog, list_models
from xaikit.pricing import clear_public_price_cache
from xaikit.provider import MockChatProvider
from xaikit.types import ModelInfo

KEY = "xai-test-FAKE"
US = "https://us.api.x.ai/v1"
REPO = Path(__file__).resolve().parents[1]

BASIC = {"prompt_tokens": 1_000_000, "completion_tokens": 500_000}
CACHED = {
    "prompt_tokens": 1_000_000,
    "completion_tokens": 0,
    "cached_prompt_text_tokens": 400_000,
}
LONG = {"prompt_tokens": 250_000, "completion_tokens": 10_000}
LONG_CACHED = {
    "prompt_tokens": 250_000,
    "completion_tokens": 10_000,
    "cached_prompt_text_tokens": 100_000,
}
ONE_43 = {"prompt_tokens": 1, "completion_tokens": 0}
ONE_47 = {"prompt_tokens": 1, "completion_tokens": 0}

US_SPELLINGS = (
    "https://us.api.x.ai/v1/",
    "https://US.API.X.AI/v1",
    "https://Us.Api.X.Ai/v1/",
    "https://us.api.x.ai:443/v1",
    "https://us.api.x.ai",
    "https://us.api.x.ai:8443/v1",
    "http://us.api.x.ai/v1",
)
LOOKALIKES = (
    "https://eu.api.x.ai/v1",
    "https://us.api.x.ai.evil.example/v1",
    "https://xus.api.x.ai/v1",
    "https://api.x.ai.us/v1",
    "https://us-api.x.ai/v1",
)

_NET = {"connect": 0, "dns": 0}

pytestmark = pytest.mark.parametrize("cls", [XaiClient, AsyncXaiClient])


def _host_of(address: Any) -> str:
    if isinstance(address, tuple) and address:
        return str(address[0])
    return str(address)


def _loopback(host: str) -> bool:
    return host in {"127.0.0.1", "::1", "localhost"}


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch):
    inject_catalog(None)
    clear_catalog_cache()
    clear_public_price_cache()
    monkeypatch.delenv("XAI_BASE_URL", raising=False)
    _NET["connect"] = 0
    _NET["dns"] = 0

    orig_connect = socket.socket.connect
    orig_connect_ex = socket.socket.connect_ex
    orig_getaddrinfo = socket.getaddrinfo

    def connect(self, address):  # type: ignore[no-untyped-def]
        host = _host_of(address)
        if not _loopback(host):
            _NET["connect"] += 1
            raise AssertionError(f"non-loopback connection to {host}")
        return orig_connect(self, address)

    def connect_ex(self, address):  # type: ignore[no-untyped-def]
        host = _host_of(address)
        if not _loopback(host):
            _NET["connect"] += 1
            raise AssertionError(f"non-loopback connection to {host}")
        return orig_connect_ex(self, address)

    def getaddrinfo(host, *args, **kwargs):  # type: ignore[no-untyped-def]
        name = str(host)
        if not _loopback(name):
            _NET["dns"] += 1
            raise AssertionError(f"non-loopback DNS lookup for {name}")
        return orig_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    yield
    inject_catalog(None)
    clear_catalog_cache()
    clear_public_price_cache()


def _start_mock() -> dict[str, Any]:
    class Handler(BaseHTTPRequestHandler):
        def _serve(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            path = self.path.split("?", 1)[0]
            if path.endswith("/models"):
                body = json.dumps(
                    {
                        "data": [
                            {"id": "grok-4.7", "object": "model"},
                            {"id": "grok-4.6", "object": "model"},
                        ]
                    }
                ).encode()
            elif path.endswith("/images/generations") or path.endswith("/images/edits"):
                body = json.dumps(
                    {"data": [{"url": "http://127.0.0.1/img.png"}]}
                ).encode()
            elif path.endswith("/videos/generations") or path.endswith("/videos/extensions"):
                body = json.dumps({"request_id": "vid-1"}).encode()
            elif path.endswith("/chat/completions"):
                usage = BASIC
                try:
                    parsed = json.loads(raw.decode() or "{}")
                    if isinstance(parsed.get("usage"), dict):
                        usage = parsed["usage"]
                except json.JSONDecodeError:
                    parsed = {}
                body = json.dumps(
                    {
                        "choices": [
                            {
                                "message": {"role": "assistant", "content": "ok"},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": usage,
                    }
                ).encode()
            else:
                body = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

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
    return {"server": server, "thread": thread, "port": port}


@pytest.fixture
def mock_http(monkeypatch: pytest.MonkeyPatch):
    started = _start_mock()
    port = int(started["port"])

    def _rewrite(url: str) -> str:
        parts = urlsplit(str(url))
        if _loopback(parts.hostname or ""):
            return str(url)
        path = parts.path or "/"
        query = f"?{parts.query}" if parts.query else ""
        return f"http://127.0.0.1:{port}{path}{query}"

    orig_get = httpx.get
    orig_post = httpx.post

    def get(url, *args, **kwargs):  # type: ignore[no-untyped-def]
        return orig_get(_rewrite(url), *args, **kwargs)

    def post(url, *args, **kwargs):  # type: ignore[no-untyped-def]
        return orig_post(_rewrite(url), *args, **kwargs)

    class _RedirectAsync(httpx.AsyncClient):
        async def request(self, method, url, **kwargs):  # type: ignore[no-untyped-def]
            return await super().request(method, _rewrite(url), **kwargs)

    monkeypatch.setattr(httpx, "get", get)
    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(httpx, "AsyncClient", _RedirectAsync)
    try:
        yield started
    finally:
        started["server"].shutdown()
        started["thread"].join(timeout=2)


def _meter() -> UsageMeter:
    return UsageMeter(InMemoryUsageSink())


def _make(
    cls: type,
    meter: UsageMeter,
    usage: dict[str, Any],
    *,
    base_url: str | None,
    model: str = "grok-4.7",
    **kwargs: Any,
) -> Any:
    return cls(
        api_key=KEY,
        model=model,
        base_url=base_url,
        usage_meter=meter,
        provider=MockChatProvider("ok", default_usage=dict(usage)),
        image_model=kwargs.pop("image_model", "grok-imagine-image"),
        video_model=kwargs.pop("video_model", "grok-imagine-video-1.5"),
        voice_model=kwargs.pop("voice_model", "grok-voice-think-fast-2.0"),
        **kwargs,
    )


def _call(result: Any) -> Any:
    if inspect.isawaitable(result):
        return asyncio.run(result)
    return result


def _chat(
    client: Any,
    *,
    model: str | None = None,
    purpose: str = "meter",
    parent_id: str | None = None,
) -> Any:
    return _call(
        client.chat(
            [{"role": "user", "content": "hi"}],
            purpose=purpose,
            model=model,
            parent_id=parent_id,
        )
    )


def _usd(meter: UsageMeter) -> float | None:
    events = meter.events()
    assert len(events) == 1, [e.estimated_usd for e in events]
    assert "host" not in type(events[0]).model_fields
    return events[0].estimated_usd


def _price(
    cls: type,
    usage: dict[str, Any],
    base_url: str | None,
    *,
    model: str = "grok-4.7",
    call_model: str | None = None,
) -> float | None:
    meter = _meter()
    client = _make(cls, meter, usage, base_url=base_url, model=model)
    _chat(client, model=call_model)
    return _usd(meter)


def test_rm1_1_basic_tokens(cls, mock_http: dict[str, Any]) -> None:
    # 1_000_000 prompt tokens are the long tier (4.0 and 12.0), so the base is 10.
    assert _price(cls, BASIC, None) == 10.0
    assert _price(cls, BASIC, US) == 11.0
    proxy = f"http://127.0.0.1:{mock_http['port']}/proxy/v1"
    assert _price(cls, BASIC, proxy) == 10.0


def test_rm1_2_cached_input_keys(cls, mock_http: dict[str, Any]) -> None:
    for key in ("cached_tokens", "cached_prompt_tokens", "cached_prompt_text_tokens"):
        usage = {
            "prompt_tokens": 1_000_000,
            "completion_tokens": 0,
            key: 400_000,
        }
        assert _price(cls, usage, None) == 2.8
        assert _price(cls, usage, US) == 3.08


def test_rm1_3_long_context(cls, mock_http: dict[str, Any]) -> None:
    assert _price(cls, LONG, None) == 1.12
    assert _price(cls, LONG, US) == 1.232
    assert _price(cls, LONG_CACHED, None) == 0.82
    assert _price(cls, LONG_CACHED, US) == 0.902


def test_rm1_4_rounding(cls, mock_http: dict[str, Any]) -> None:
    assert _price(cls, ONE_43, None, model="grok-4.3") == 0.00000125
    assert _price(cls, ONE_43, US, model="grok-4.3") == 0.00000138
    assert _price(cls, ONE_47, None) == 0.000002
    assert _price(cls, ONE_47, US) == 0.0000022


def test_rm1_5_host_spelling(cls, mock_http: dict[str, Any]) -> None:
    for base in US_SPELLINGS:
        assert _price(cls, BASIC, base) == 11.0
    direct = _meter()
    direct.record(
        purpose="meter",
        model="grok-4.7",
        usage=dict(BASIC),
        host="https://US.API.X.AI/v1",
    )
    assert _usd(direct) == 11.0
    omitted = UsageMeter().record(
        purpose="meter",
        model="grok-4.7",
        usage=dict(BASIC),
        host=None,
    )
    assert omitted.estimated_usd == 10.0


def test_rm1_6_client_host_threads_and_env(
    cls, mock_http: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _price(cls, BASIC, US, model="grok-4.7", call_model="grok-4.6") == 11.0

    shared = _meter()
    us = _make(cls, shared, BASIC, base_url=US, model="grok-4.7")
    default = _make(cls, shared, BASIC, base_url=None, model="grok-4.7")
    if cls is AsyncXaiClient:

        async def _both() -> None:
            await asyncio.gather(
                us.chat(
                    [{"role": "user", "content": "hi"}],
                    purpose="meter",
                    parent_id="us",
                ),
                default.chat(
                    [{"role": "user", "content": "hi"}],
                    purpose="meter",
                    parent_id="default",
                ),
            )

        asyncio.run(_both())
    else:
        barrier = threading.Barrier(2)

        def _run(client: Any, parent: str) -> None:
            barrier.wait(timeout=5)
            client.chat(
                [{"role": "user", "content": "hi"}],
                purpose="meter",
                parent_id=parent,
            )

        threads = [
            threading.Thread(target=_run, args=(us, "us")),
            threading.Thread(target=_run, args=(default, "default")),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
    us_events = shared.events(parent_id="us")
    default_events = shared.events(parent_id="default")
    assert [e.estimated_usd for e in us_events] == [11.0]
    assert [e.estimated_usd for e in default_events] == [10.0]

    monkeypatch.setenv("XAI_BASE_URL", US)
    assert _price(cls, BASIC, None) == 11.0
    assert _price(cls, BASIC, "https://api.x.ai/v1/") == 10.0


def test_rm1_7_async_gather_matches_sync_numbers(
    cls, mock_http: dict[str, Any]
) -> None:
    """RM1-1 numbers on both clients, gathered together."""
    shared = _meter()
    us = _make(AsyncXaiClient, shared, BASIC, base_url=US)
    default = _make(AsyncXaiClient, shared, BASIC, base_url=None)

    async def _both() -> None:
        await asyncio.gather(
            us.chat(
                [{"role": "user", "content": "hi"}],
                purpose="meter",
                parent_id="us",
            ),
            default.chat(
                [{"role": "user", "content": "hi"}],
                purpose="meter",
                parent_id="default",
            ),
        )

    asyncio.run(_both())
    assert shared.events(parent_id="us")[0].estimated_usd == 11.0
    assert shared.events(parent_id="default")[0].estimated_usd == 10.0
    assert _price(XaiClient, BASIC, US) == 11.0


def test_rm1_8_price_sources(cls, mock_http: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    inject_catalog(
        [
            ModelInfo(
                id="qa-catalog-only",
                capabilities=["chat"],
                input_per_million=4.0,
                output_per_million=8.0,
                cached_input_per_million=1.0,
            )
        ]
    )
    list_models()
    assert _price(cls, BASIC, None, model="qa-catalog-only") == 8.0
    assert _price(cls, BASIC, US, model="qa-catalog-only") == 8.8
    inject_catalog(None)
    clear_catalog_cache()

    assert _price(cls, BASIC, None, model="grok-4.7") == 10.0
    assert _price(cls, BASIC, US, model="grok-4.7") == 11.0

    payload = {
        "fetched": "2026-10-13",
        "source_url": "https://example.invalid/prices.json",
        "models": {
            "qa-gap-only": {
                "input_per_million": 2.0,
                "output_per_million": 6.0,
            }
        },
    }
    monkeypatch.setattr(
        "xaikit.pricing.fetch_public_price_payload",
        lambda url="", timeout=10.0: payload,
    )
    clear_public_price_cache()
    assert _price(cls, BASIC, None, model="qa-gap-only") == 5.0
    assert _price(cls, BASIC, US, model="qa-gap-only") == 5.5


def test_rm1_9_one_host_table(cls, mock_http: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    from xaikit.pricing import REGIONAL_TOKEN_PREMIUM

    hits: list[str] = []
    for path in (REPO / "src").rglob("*.py"):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "0.10" in line or "1.10" in line:
                hits.append(f"{path}:{lineno}:{line.strip()}")
    assert hits == [
        f"{REPO / 'src' / 'xaikit' / 'pricing.py'}:{_premium_line()}:{_premium_text()}"
    ]
    assert list(REGIONAL_TOKEN_PREMIUM) == ["us.api.x.ai"]
    assert REGIONAL_TOKEN_PREMIUM["us.api.x.ai"] == 0.10

    monkeypatch.setitem(REGIONAL_TOKEN_PREMIUM, "us.api.x.ai", 0.20)
    assert _price(cls, BASIC, US) == 12.0
    monkeypatch.setitem(REGIONAL_TOKEN_PREMIUM, "preview.example", 0.10)
    assert _price(cls, BASIC, "https://preview.example/v1") == 11.0


def _premium_line() -> int:
    text = (REPO / "src" / "xaikit" / "pricing.py").read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), 1):
        if "0.10" in line or "1.10" in line:
            return lineno
    raise AssertionError("premium literal missing")


def _premium_text() -> str:
    text = (REPO / "src" / "xaikit" / "pricing.py").read_text(encoding="utf-8")
    for line in text.splitlines():
        if "0.10" in line or "1.10" in line:
            return line.strip()
    raise AssertionError("premium literal missing")


def test_rm1_10_server_ticks_win(cls, mock_http: dict[str, Any]) -> None:
    usage = {
        "prompt_tokens": 1,
        "completion_tokens": 0,
        "cost_in_usd_ticks": 55_000_000_000,
    }
    assert _price(cls, usage, US) == 5.5
    assert _price(cls, usage, None) == 5.5
    # The same token counts without ticks take the premium, so this case
    # fails when the host table is missing.
    assert _price(cls, ONE_47, US) == 0.0000022


def test_rm1_11_image_input_tokens(cls, mock_http: dict[str, Any]) -> None:
    inject_catalog(
        [
            ModelInfo(
                id="grok-4.7",
                capabilities=["chat"],
                input_per_million=2.0,
                output_per_million=6.0,
                image_token_per_million=2.0,
            )
        ]
    )
    list_models()
    usage = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "prompt_image_tokens": 1_000_000,
    }
    assert _price(cls, usage, None) == 2.0
    assert _price(cls, usage, US) == 2.2


def test_rm2_1_default_host_matches_base(cls, mock_http: dict[str, Any]) -> None:
    assert _price(cls, BASIC, None) == 10.0
    assert _price(cls, BASIC, "https://api.x.ai/v1/") == 10.0
    assert _price(cls, CACHED, "https://api.x.ai/v1/") == 2.8
    assert _price(cls, LONG, None) == 1.12
    assert _price(cls, LONG_CACHED, "https://api.x.ai/v1/") == 0.82
    assert _price(cls, ONE_43, None, model="grok-4.3") == 0.00000125


def test_rm2_2_unknown_hosts_stay_base(cls, mock_http: dict[str, Any]) -> None:
    proxy = f"http://127.0.0.1:{mock_http['port']}/proxy/v1"
    for base in (proxy, *LOOKALIKES):
        assert _price(cls, BASIC, base) == 10.0


def test_rm2_3_non_token_units_stay_base(cls, mock_http: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    meter = _meter()
    client = _make(
        cls,
        meter,
        BASIC,
        base_url=US,
        model="grok-4.7",
        image_model="grok-imagine-image",
        video_model="grok-imagine-video-1.5",
        voice_model="grok-voice-think-fast-2.0",
    )
    _call(client.generate_image("a red cube", purpose="image"))
    assert meter.events(purpose="image")[0].estimated_usd == 0.02

    _call(
        client.generate_video(
            "a red cube",
            duration=5,
            resolution="480p",
            into=[],
            wait=False,
            purpose="video",
        )
    )
    assert meter.events(purpose="video")[0].estimated_usd == 0.4

    clock = {"now": 0.0}

    def _monotonic() -> float:
        return clock["now"]

    class _Ws:
        def send(self, message: str) -> None:
            return None

        def close(self) -> None:
            return None

    def _connect(uri: str, **kwargs: Any) -> _Ws:
        return _Ws()

    async def _connect_async(uri: str, **kwargs: Any) -> _Ws:
        return _Ws()

    monkeypatch.setattr("xaikit.realtime.time.monotonic", _monotonic)
    monkeypatch.setattr("xaikit.client.connect_realtime_websocket", _connect)
    monkeypatch.setattr(
        "xaikit.async_client.connect_realtime_websocket_async",
        _connect_async,
    )
    if cls is AsyncXaiClient:

        async def _voice() -> None:
            session = await client.open_realtime_session(purpose="voice")
            clock["now"] = 60.0
            await session.close()

        asyncio.run(_voice())
    else:
        session = client.open_realtime_session(purpose="voice")
        clock["now"] = 60.0
        session.close()
    assert meter.events(purpose="voice")[0].estimated_usd == 0.08


def test_rm2_4_standalone_meter_keeps_base(cls) -> None:
    event = UsageMeter().record(
        purpose="meter",
        model="grok-4.7",
        prompt_tokens=1_000_000,
        completion_tokens=500_000,
        thought_level="low",
        modality="chat",
        apply_price_table=True,
        success=True,
    )
    assert event.estimated_usd == 10.0
    assert "host" not in type(event).model_fields


def test_rm2_5_no_offbox_network(cls, mock_http: dict[str, Any]) -> None:
    assert _price(cls, BASIC, US) == 11.0
    assert _NET["connect"] == 0
    assert _NET["dns"] == 0


def test_rm2_6_rollups_use_adjusted_values(cls, mock_http: dict[str, Any]) -> None:
    meter = _meter()
    us = _make(cls, meter, BASIC, base_url=US)
    default = _make(cls, meter, BASIC, base_url=None)
    _chat(us, purpose="roll", parent_id="job")
    _chat(default, purpose="roll", parent_id="job")
    assert meter.cost_by_purpose("roll").estimated_usd == 21.0
    assert meter.cost_by_parent("job").estimated_usd == 21.0
    now = datetime.now(timezone.utc)
    period = meter.cost_for_period(now - timedelta(days=1), now + timedelta(days=1))
    assert period.estimated_usd == 21.0


def test_rm2_7_docs_replace_the_gap_note(cls) -> None:
    catalog = (REPO / "docs" / "features" / "Catalog.md").read_text(encoding="utf-8")
    usage_doc = (REPO / "docs" / "features" / "UsageObservability.md").read_text(
        encoding="utf-8"
    )
    changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "does not apply the 10% US endpoint token premium" not in catalog
    assert "does not apply the 10% US token premium" not in catalog
    assert "follow-up cut" not in catalog
    assert "XK-AC-REGION-METER-1" in catalog
    assert "XK-AC-REGION-METER-2" in catalog
    assert "XK-AC-REGION-METER-1" in usage_doc
    assert "XK-AC-REGION-METER-2" in usage_doc
    assert "REGIONAL_TOKEN_PREMIUM" in usage_doc
    assert "us.api.x.ai" in usage_doc
    assert "cost_in_usd_ticks" in usage_doc
    unreleased = changelog.split("## 0.3.0", 1)[0]
    assert "10% US endpoint token premium" in unreleased
    assert "does not apply" not in unreleased
