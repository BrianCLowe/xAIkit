"""XK-AC-IMGN-1, XK-AC-IMGN-2, XK-AC-DOC-2.

Image calls return every data item, in order, and the meter prices the
per-image rate times the number of images returned. HTTP is mocked.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest
from typing_extensions import Self

from xaikit import (
    XAI_IMAGES_URL,
    AsyncXaiClient,
    InMemoryUsageSink,
    MockChatProvider,
    UsageMeter,
    XaiClient,
    default_price_table,
    default_retry_policy,
)
from xaikit.catalog import clear_catalog_cache

_ROOT = Path(__file__).resolve().parents[1]
_MODEL = "grok-imagine-image"
_API_KEY = "xai-test-fake"


def _rate() -> float:
    price = default_price_table().price_for(_MODEL)
    assert price is not None
    assert price.per_call_usd is not None
    return float(price.per_call_usd)


def _urls(count: int) -> list[str]:
    return [f"https://example.com/img-{index}.png" for index in range(count)]


def _payload(urls: list[str]) -> dict[str, Any]:
    return {"data": [{"url": url} for url in urls]}


def _block_live_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    def _no_network(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("live network call is not allowed in this test")

    monkeypatch.setattr("xaikit.pricing.fetch_public_price_payload", _no_network)
    monkeypatch.setattr("xaikit.catalog.fetch_models_from_sdk", _no_network)


def _sync_client(sink: InMemoryUsageSink) -> XaiClient:
    clear_catalog_cache()
    return XaiClient(
        provider=MockChatProvider(),
        model="grok-3-mini",
        api_key=_API_KEY,
        image_model=_MODEL,
        video_model="grok-imagine-video",
        voice_model="grok-voice-latest",
        usage_meter=UsageMeter(sink=sink),
        retry_policy=default_retry_policy(max_attempts=1),
    )


def _async_client(sink: InMemoryUsageSink) -> AsyncXaiClient:
    clear_catalog_cache()
    return AsyncXaiClient(
        provider=MockChatProvider(),
        model="grok-3-mini",
        api_key=_API_KEY,
        image_model=_MODEL,
        video_model="grok-imagine-video",
        voice_model="grok-voice-latest",
        usage_meter=UsageMeter(sink=sink),
        retry_policy=default_retry_policy(max_attempts=1, backoff_seconds=0.0),
    )


def _install_sync(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def _post(url: str, **kwargs: Any) -> httpx.Response:
        calls.append({"url": url, **kwargs})
        return httpx.Response(
            200,
            json=payload,
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("xaikit.client.httpx.post", _post)
    return calls


def _install_async(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    class FakeAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            del args, kwargs

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *args: object) -> bool:
            del args
            return False

        async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
            calls.append({"method": method, "url": url, **kwargs})
            return httpx.Response(
                200,
                json=payload,
                request=httpx.Request(method, url),
            )

    monkeypatch.setattr("xaikit.async_client.httpx.AsyncClient", FakeAsyncClient)
    return calls


def _assert_images(
    out: dict[str, Any],
    urls: list[str],
    *,
    sink: InMemoryUsageSink,
    requested_n: int,
    body: dict[str, Any],
) -> None:
    assert out["url"] == urls[0]
    assert out["b64_json"] is None
    assert out["file_id"] is None
    assert out["model"] == _MODEL
    assert [item["url"] for item in out["images"]] == urls
    assert body["n"] == requested_n
    assert body["model"] == _MODEL
    events = list(sink.iter_events())
    assert len(events) == 1
    event = events[0]
    assert event.success is True
    assert event.modality == "imagine"
    assert event.model == _MODEL
    assert event.estimated_usd == round(_rate() * len(urls), 8)


def test_xk_ac_imgn_1_sync_n4_returns_four_urls_and_meters_four_images(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _block_live_calls(monkeypatch)
    urls = _urls(4)
    calls = _install_sync(monkeypatch, _payload(urls))
    sink = InMemoryUsageSink()
    out = _sync_client(sink).generate_image("a red cube", n=4, purpose="demo.imagine")
    assert calls[0]["url"] == XAI_IMAGES_URL
    assert calls[0]["headers"]["Authorization"] == f"Bearer {_API_KEY}"
    _assert_images(out, urls, sink=sink, requested_n=4, body=calls[0]["json"])


def test_xk_ac_imgn_2_async_n4_returns_four_urls_and_meters_four_images(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run() -> None:
        _block_live_calls(monkeypatch)
        urls = _urls(4)
        calls = _install_async(monkeypatch, _payload(urls))
        sink = InMemoryUsageSink()
        out = await _async_client(sink).generate_image(
            "a red cube", n=4, purpose="demo.imagine"
        )
        assert calls[0]["url"] == XAI_IMAGES_URL
        assert calls[0]["headers"]["Authorization"] == f"Bearer {_API_KEY}"
        _assert_images(out, urls, sink=sink, requested_n=4, body=calls[0]["json"])

    asyncio.run(_run())


def test_sync_image_cost_uses_returned_count_not_requested_n(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _block_live_calls(monkeypatch)
    urls = _urls(2)
    calls = _install_sync(monkeypatch, _payload(urls))
    sink = InMemoryUsageSink()
    out = _sync_client(sink).generate_image("a red cube", n=4, purpose="demo.imagine")
    _assert_images(out, urls, sink=sink, requested_n=4, body=calls[0]["json"])


def test_async_image_cost_uses_returned_count_not_requested_n(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run() -> None:
        _block_live_calls(monkeypatch)
        urls = _urls(2)
        calls = _install_async(monkeypatch, _payload(urls))
        sink = InMemoryUsageSink()
        out = await _async_client(sink).generate_image(
            "a red cube", n=4, purpose="demo.imagine"
        )
        _assert_images(out, urls, sink=sink, requested_n=4, body=calls[0]["json"])

    asyncio.run(_run())


_UNSORTED_URLS = [
    "https://example.com/z3.png",
    "https://example.com/z1.png",
    "https://example.com/z2.png",
    "https://example.com/z0.png",
]
_NO_URL_ITEMS = [
    {"b64_json": "b64-z3", "file_id": "file-z3"},
    {"b64_json": "b64-z1", "file_id": "file-z1"},
    {"b64_json": "b64-z2", "file_id": "file-z2"},
    {"b64_json": "b64-z0", "file_id": "file-z0"},
]
_DUPLICATE_URLS = [
    "https://example.com/dup.png",
    "https://example.com/other.png",
    "https://example.com/dup.png",
]


def _generate_sync(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any], *, n: int
) -> tuple[dict[str, Any], list[dict[str, Any]], InMemoryUsageSink]:
    _block_live_calls(monkeypatch)
    calls = _install_sync(monkeypatch, payload)
    sink = InMemoryUsageSink()
    out = _sync_client(sink).generate_image("a red cube", n=n, purpose="demo.imagine")
    return out, calls, sink


def _generate_async(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any], *, n: int
) -> tuple[dict[str, Any], list[dict[str, Any]], InMemoryUsageSink]:
    async def _run() -> tuple[dict[str, Any], list[dict[str, Any]], InMemoryUsageSink]:
        _block_live_calls(monkeypatch)
        calls = _install_async(monkeypatch, payload)
        sink = InMemoryUsageSink()
        out = await _async_client(sink).generate_image(
            "a red cube", n=n, purpose="demo.imagine"
        )
        return out, calls, sink

    return asyncio.run(_run())


def test_sync_n4_keeps_unsorted_upstream_url_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out, calls, sink = _generate_sync(monkeypatch, _payload(_UNSORTED_URLS), n=4)
    assert calls[0]["json"]["n"] == 4
    _assert_images(out, _UNSORTED_URLS, sink=sink, requested_n=4, body=calls[0]["json"])


def test_async_n4_keeps_unsorted_upstream_url_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out, calls, sink = _generate_async(monkeypatch, _payload(_UNSORTED_URLS), n=4)
    assert calls[0]["json"]["n"] == 4
    _assert_images(out, _UNSORTED_URLS, sink=sink, requested_n=4, body=calls[0]["json"])


def _expected_no_url_images() -> list[dict[str, str | None]]:
    return [
        {
            "url": None,
            "b64_json": str(item["b64_json"]),
            "file_id": str(item["file_id"]),
        }
        for item in _NO_URL_ITEMS
    ]


def _assert_no_url_items(out: dict[str, Any]) -> None:
    images = _expected_no_url_images()
    assert out["images"] == images
    assert out["url"] == images[0]["url"]
    assert out["b64_json"] == images[0]["b64_json"]
    assert out["file_id"] == images[0]["file_id"]


def test_sync_n4_lists_b64_and_file_id_items_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out, calls, _sink = _generate_sync(monkeypatch, {"data": _NO_URL_ITEMS}, n=4)
    assert calls[0]["json"]["n"] == 4
    _assert_no_url_items(out)


def test_async_n4_lists_b64_and_file_id_items_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out, calls, _sink = _generate_async(monkeypatch, {"data": _NO_URL_ITEMS}, n=4)
    assert calls[0]["json"]["n"] == 4
    _assert_no_url_items(out)


def _assert_duplicate_urls_billed(out: dict[str, Any], sink: InMemoryUsageSink) -> None:
    assert [item["url"] for item in out["images"]] == _DUPLICATE_URLS
    assert len(out["images"]) == 3
    assert out["url"] == _DUPLICATE_URLS[0]
    assert _rate() == 0.02
    events = list(sink.iter_events())
    assert len(events) == 1
    assert events[0].estimated_usd == 0.06


def test_sync_keeps_duplicate_urls_and_bills_each_returned_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out, _calls, sink = _generate_sync(monkeypatch, _payload(_DUPLICATE_URLS), n=3)
    _assert_duplicate_urls_billed(out, sink)


def test_async_keeps_duplicate_urls_and_bills_each_returned_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out, _calls, sink = _generate_async(monkeypatch, _payload(_DUPLICATE_URLS), n=3)
    _assert_duplicate_urls_billed(out, sink)


_MIXED_ITEMS: list[dict[str, str]] = [
    {"url": "https://example.com/url-only.png"},
    {"b64_json": "b64-only"},
    {"file_id": "file-only"},
    {"url": "https://example.com/url-and-file.png", "file_id": "file-with-url"},
]


def _expected_mixed_images() -> list[dict[str, str | None]]:
    return [
        {"url": "https://example.com/url-only.png", "b64_json": None, "file_id": None},
        {"url": None, "b64_json": "b64-only", "file_id": None},
        {"url": None, "b64_json": None, "file_id": "file-only"},
        {
            "url": "https://example.com/url-and-file.png",
            "b64_json": None,
            "file_id": "file-with-url",
        },
    ]


def _assert_mixed_items(out: dict[str, Any], sink: InMemoryUsageSink) -> None:
    images = _expected_mixed_images()
    assert out["images"] == images
    assert len(out["images"]) == 4
    assert out["url"] == images[0]["url"]
    assert out["b64_json"] == images[0]["b64_json"]
    assert out["file_id"] == images[0]["file_id"]
    assert _rate() == 0.02
    events = list(sink.iter_events())
    assert len(events) == 1
    assert events[0].estimated_usd == 0.08


def test_sync_n4_keeps_mixed_url_b64_and_file_id_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out, calls, sink = _generate_sync(monkeypatch, {"data": _MIXED_ITEMS}, n=4)
    assert calls[0]["json"]["n"] == 4
    _assert_mixed_items(out, sink)


def test_async_n4_keeps_mixed_url_b64_and_file_id_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out, calls, sink = _generate_async(monkeypatch, {"data": _MIXED_ITEMS}, n=4)
    assert calls[0]["json"]["n"] == 4
    _assert_mixed_items(out, sink)


def test_xk_ac_doc_2_readme_and_issue_config_say_current_version() -> None:
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    config = (_ROOT / ".github/ISSUE_TEMPLATE/config.yml").read_text(encoding="utf-8")
    assert "0.1.3" not in readme
    assert "0.1.3" not in config
    assert "git+https://github.com/BrianCLowe/xAIkit@v0.5.1" in readme
    assert "This repo's version is 0.5.1." in config
