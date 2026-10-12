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


def test_xk_ac_doc_2_readme_and_issue_config_say_0_2_0() -> None:
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    config = (_ROOT / ".github/ISSUE_TEMPLATE/config.yml").read_text(encoding="utf-8")
    assert "0.1.3" not in readme
    assert "0.1.3" not in config
    assert "git+https://github.com/BrianCLowe/xAIkit@v0.2.0" in readme
    assert "This repo's version is 0.2.0." in config
