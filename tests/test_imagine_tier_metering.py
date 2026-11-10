"""CUT-2026-11-06-xk-imagine-tier-metering.

TM-AC-1: the request contract and the watcher accept the 1.5k Imagine
resolution. TM-AC-2: Imagine usage events carry the contracted resolution,
quality, and input count, so metering equals the direct estimate_usd with
the same knobs, including on the cached-catalog path.

Offline only. Every test blocks non-loopback sockets (and create_connection),
patches the catalog SDK fetch and the public price fetch to raise, fakes
httpx.post for the sync client and httpx.AsyncClient (request and post) for
the async client. The key is a literal fake; no real credential is used.
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
from typing_extensions import Self

from xaikit import (
    AsyncXaiClient,
    InMemoryUsageSink,
    MockChatProvider,
    UsageMeter,
    XaiClient,
    default_price_table,
    default_retry_policy,
)
from xaikit.catalog import (
    clear_catalog_cache,
    contract_imagine_resolution,
    imagine_generate_knobs,
    inject_catalog,
    list_models,
)
from xaikit.types import ModelInfo

_ROOT = Path(__file__).resolve().parents[1]
_API_KEY = "xai-test-fake"
IMAGE_2 = "grok-imagine-image-2.0"
IMAGE_PLAIN = "grok-imagine-image"
CLIENTS = ["sync", "async"]


def _load_watch():
    path = _ROOT / "scripts" / "watch_xai_models.py"
    spec = importlib.util.spec_from_file_location("watch_xai_models_tm", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch):
    for name in ("XAI_API_KEY", "XAI_BASE_URL", "XAI_MANAGEMENT_KEY", "XAITKIT_LIVE"):
        monkeypatch.delenv(name, raising=False)

    def _no_network(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("network fetch attempted in an offline test")

    def _no_socket(self: Any, address: Any) -> Any:
        raise AssertionError(f"socket connect attempted: {address!r}")

    monkeypatch.setattr(socket.socket, "connect", _no_socket)
    monkeypatch.setattr(socket.socket, "connect_ex", _no_socket)
    monkeypatch.setattr(socket, "create_connection", _no_network)
    monkeypatch.setattr("xaikit.pricing.fetch_public_price_payload", _no_network)
    monkeypatch.setattr("xaikit.catalog.fetch_models_from_sdk", _no_network)
    # Default: no real HTTP at all. Tests that need a response install a fake.
    monkeypatch.setattr("xaikit.client.httpx.post", _no_network)
    inject_catalog(None)
    clear_catalog_cache()
    yield
    inject_catalog(None)
    clear_catalog_cache()


def _payload(count: int) -> dict[str, Any]:
    return {"data": [{"url": f"https://example.invalid/{i}.png"} for i in range(count)]}


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    returned: int = 1,
    status: int = 200,
    raw: bytes | None = None,
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def _response(method: str, url: str) -> httpx.Response:
        request = httpx.Request(method, url)
        if raw is not None:
            return httpx.Response(status, content=raw, request=request)
        if status >= 400:
            return httpx.Response(status, json={"error": "x"}, request=request)
        return httpx.Response(status, json=_payload(returned), request=request)

    def _post(url: str, **kwargs: Any) -> httpx.Response:
        calls.append({"method": "POST", "url": url, **kwargs})
        return _response("POST", url)

    class FakeAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            del args, kwargs

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *args: object) -> bool:
            del args
            return False

        async def aclose(self) -> None:
            return None

        async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
            calls.append({"method": method, "url": url, **kwargs})
            return _response(method, url)

        async def post(self, url: str, **kwargs: Any) -> httpx.Response:
            return await self.request("POST", url, **kwargs)

    monkeypatch.setattr("xaikit.client.httpx.post", _post)
    monkeypatch.setattr("xaikit.async_client.httpx.AsyncClient", FakeAsyncClient)
    return calls


def _client(kind: str, sink: InMemoryUsageSink, image_model: str = IMAGE_2) -> Any:
    clear_catalog_cache()
    cls = XaiClient if kind == "sync" else AsyncXaiClient
    return cls(
        provider=MockChatProvider(),
        model="grok-3-mini",
        api_key=_API_KEY,
        image_model=image_model,
        video_model="grok-imagine-video",
        voice_model="grok-voice-latest",
        usage_meter=UsageMeter(sink=sink),
        retry_policy=default_retry_policy(max_attempts=1, backoff_seconds=0.0),
    )


def _call(client: Any, name: str, *args: Any, **kwargs: Any) -> Any:
    out = getattr(client, name)(*args, **kwargs)
    if asyncio.iscoroutine(out):
        return asyncio.run(out)
    return out


def _body(call: dict[str, Any]) -> dict[str, Any]:
    if "json" in call:
        return call["json"]
    return json.loads(call["content"])


def _direct(model: str = IMAGE_2, *, count: int = 1, **knobs: Any) -> float:
    got = default_price_table().estimate_usd(model, usage={"image_count": count}, **knobs)
    assert got is not None
    return got


def _cache_catalog_row(model: str = IMAGE_2, per_image_usd: float = 0.04) -> None:
    inject_catalog([ModelInfo(id=model, capabilities=["image"], per_image_usd=per_image_usd)])
    assert [row.id for row in list_models()] == [model]


def _only_event(sink: InMemoryUsageSink) -> Any:
    events = list(sink.iter_events())
    assert len(events) == 1
    return events[0]


# ---------------- TM-AC-1 ----------------


def test_tm_c01_contract_accepts_1_5k() -> None:
    """TM-C01. 1.5k is kept and normalized; 1k/2k unchanged; 4k still omitted."""
    assert contract_imagine_resolution("1.5k") == "1.5k"
    assert contract_imagine_resolution("1.5K") == "1.5k"
    assert contract_imagine_resolution(" 1.5k ") == "1.5k"
    assert contract_imagine_resolution("1k") == "1k"
    assert contract_imagine_resolution("2k") == "2k"
    assert contract_imagine_resolution("4k") is None
    # TMQ-5: the resolution contract is the same for every model.
    for model in (IMAGE_2, IMAGE_PLAIN):
        assert imagine_generate_knobs(model, resolution="1.5k")["resolution"] == "1.5k"


@pytest.mark.parametrize("kind", CLIENTS)
def test_tm_c02_generate_sends_1_5k(kind: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """TM-C02. The captured body carries resolution 1.5k and quality low."""
    calls = _install(monkeypatch)
    client = _client(kind, InMemoryUsageSink())
    _call(client, "generate_image", "cat", resolution="1.5k", quality="low", purpose="tm")
    assert len(calls) == 1
    body = _body(calls[0])
    assert body["model"] == IMAGE_2
    assert body.get("resolution") == "1.5k"
    assert body.get("quality") == "low"


def test_tm_c03_watcher_extracts_1_5k() -> None:
    """TM-C03. Watcher reports 1.5k, no spurious 5k, and keeps old tokens."""
    watch = _load_watch()
    text = "Imagine 2.0 renders at 1k, 1.5k and 2k. Video 480p, 720p, 1080p. Upscale to 4k."
    found = watch.extract_resolutions(text)
    assert "1.5k" in found
    assert "5k" not in found
    for token in ("1k", "2k", "4k", "480p", "720p", "1080p"):
        assert token in found
    assert watch.extract_resolutions("1.5K output") == ["1.5k"]
    assert watch.extract_resolutions("sizes 21k and 11.5k and v1.5k") == []
    baseline = json.loads(
        (_ROOT / "scripts" / "data" / "xai_models_watch.json").read_text(encoding="utf-8")
    )
    assert "1.5k" not in [str(r).lower() for r in baseline.get("resolutions") or []]
    live = {"slugs": list(baseline.get("slugs") or []), "resolutions": found}
    delta = watch.diff_watch(live, baseline)
    assert "1.5k" in delta["resolutions"]


# ---------------- TM-AC-2 ----------------

_TIER_USAGE = {"image_count": 1, "resolution": "2k", "quality": "medium", "input_images": 1}


def test_tm_c04_meter_equals_direct_estimate() -> None:
    """TM-C04. A 2k medium, one-input, one-image Imagine event meters 0.09."""
    direct = _direct(resolution="2k", quality="medium", input_images=1)
    assert direct == 0.09
    meter = UsageMeter(sink=InMemoryUsageSink())
    event = meter.record(purpose="tm", model=IMAGE_2, usage=dict(_TIER_USAGE), modality="imagine")
    assert event.estimated_usd == direct


@pytest.mark.parametrize("kind", CLIENTS)
@pytest.mark.parametrize(
    "resolution, quality, want",
    [("2k", "medium", 0.08), ("1.5k", "low", 0.05)],
)
def test_tm_c05_generate_meters_direct_estimate(
    kind: str,
    resolution: str,
    quality: str,
    want: float,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TM-C05. Client generate meters the tier price; equals the direct estimate."""
    _install(monkeypatch)
    sink = InMemoryUsageSink()
    client = _client(kind, sink)
    _call(client, "generate_image", "cat", resolution=resolution, quality=quality, purpose="tm")
    event = _only_event(sink)
    assert event.success is True
    assert event.estimated_usd == want
    assert event.estimated_usd == _direct(resolution=resolution, quality=quality)


@pytest.mark.parametrize("kind", CLIENTS)
@pytest.mark.parametrize("sources", [1, 2, 3])
def test_tm_c06_edit_meters_each_input(
    kind: str, sources: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TM-C06 (TMQ-2). Edit meters base plus one media input per source sent, not n."""
    calls = _install(monkeypatch)
    sink = InMemoryUsageSink()
    client = _client(kind, sink)
    urls = [f"https://example.invalid/src-{i}.png" for i in range(sources)]
    if sources == 1:
        _call(client, "edit_image", "make it blue", image_url=urls[0], n=3, purpose="tm")
    else:
        _call(client, "edit_image", "make it blue", images=urls, n=1, purpose="tm")
    body = _body(calls[0])
    assert ("image" in body) == (sources == 1)
    event = _only_event(sink)
    want = round(0.04 + 0.01 * sources, 8)
    assert event.estimated_usd == want
    assert event.estimated_usd == _direct(input_images=sources)


def test_tm_c07_cached_catalog_meter_equals_direct_estimate() -> None:
    """TM-C07 (TMQ-3). With a cached 2.0 row at the shipped base, the meter keeps the knobs."""
    _cache_catalog_row()
    meter = UsageMeter(sink=InMemoryUsageSink())
    event = meter.record(purpose="tm", model=IMAGE_2, usage=dict(_TIER_USAGE), modality="imagine")
    assert event.estimated_usd == _direct(resolution="2k", quality="medium", input_images=1)
    assert event.estimated_usd == 0.09


@pytest.mark.parametrize("kind", CLIENTS)
def test_tm_c07_cached_catalog_client_generate_and_edit(
    kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TM-C07 through the client: generate 2k medium 0.08, edit one source 0.05."""
    _install(monkeypatch)
    sink = InMemoryUsageSink()
    client = _client(kind, sink)
    _cache_catalog_row()
    _call(client, "generate_image", "cat", resolution="2k", quality="medium", purpose="tm")
    _call(client, "edit_image", "blue", image_url="https://example.invalid/a.png", purpose="tm")
    got = [event.estimated_usd for event in sink.iter_events()]
    assert got == [
        _direct(resolution="2k", quality="medium"),
        _direct(input_images=1),
    ]
    assert got == [0.08, 0.05]


def test_tm_c07_cached_catalog_other_base_keeps_its_rate() -> None:
    """A cached base that differs from the shipped base keeps its flat rate (plan TM-PQ-1)."""
    _cache_catalog_row(per_image_usd=0.05)
    meter = UsageMeter(sink=InMemoryUsageSink())
    event = meter.record(purpose="tm", model=IMAGE_2, usage=dict(_TIER_USAGE), modality="imagine")
    assert event.estimated_usd == round(0.05 + 0.01, 8)


@pytest.mark.parametrize("kind", CLIENTS)
def test_tm_c08_count_is_images_returned(kind: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """TM-C08. n=4 that returns 2 images at 2k medium meters 2 x 0.08."""
    calls = _install(monkeypatch, returned=2)
    sink = InMemoryUsageSink()
    client = _client(kind, sink)
    _call(client, "generate_image", "cat", n=4, resolution="2k", quality="medium", purpose="tm")
    assert _body(calls[0])["n"] == 4
    event = _only_event(sink)
    assert event.estimated_usd == 0.16
    assert event.estimated_usd == _direct(count=2, resolution="2k", quality="medium")


# ---------------- regression ----------------


def test_tm_c09_ticks_still_win() -> None:
    """TM-C09. cost_in_usd_ticks on the usage event wins over the knob estimate."""
    meter = UsageMeter(sink=InMemoryUsageSink())
    usage = dict(_TIER_USAGE, cost_in_usd_ticks=1_230_000_000)
    event = meter.record(purpose="tm", model=IMAGE_2, usage=usage, modality="imagine")
    assert event.estimated_usd == 0.123
    _cache_catalog_row()
    event = meter.record(purpose="tm", model=IMAGE_2, usage=dict(usage), modality="imagine")
    assert event.estimated_usd == 0.123


@pytest.mark.parametrize("kind", CLIENTS)
@pytest.mark.parametrize("failure", ["http500", "non_json"])
def test_tm_c09_failed_calls_invent_no_tier_price(
    kind: str, failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TM-C09. HTTP error and non-JSON still record success False with no tier price."""
    if failure == "http500":
        _install(monkeypatch, status=500)
    else:
        _install(monkeypatch, raw=b"not json")
    sink = InMemoryUsageSink()
    client = _client(kind, sink)
    with pytest.raises(RuntimeError):
        _call(client, "generate_image", "cat", resolution="2k", quality="medium", purpose="tm")
    event = _only_event(sink)
    assert event.success is False
    assert event.estimated_usd in (None, _direct())
    assert event.estimated_usd != _direct(resolution="2k", quality="medium")


@pytest.mark.parametrize("kind", CLIENTS)
def test_tm_c10_non_2_0_sku_unchanged(kind: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """TM-C10. grok-imagine-image omits quality and meters its base rate times count."""
    calls = _install(monkeypatch, returned=2)
    sink = InMemoryUsageSink()
    client = _client(kind, sink, image_model=IMAGE_PLAIN)
    _call(client, "generate_image", "cat", n=2, resolution="2k", quality="medium", purpose="tm")
    body = _body(calls[0])
    assert "quality" not in body
    assert body["resolution"] == "2k"
    event = _only_event(sink)
    assert event.estimated_usd == round(0.02 * 2, 8)
