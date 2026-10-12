"""A public price fetch must not raise from record, and a priced call must not fetch.

XK-AC-PRICE-3, XK-AC-PRICE-4. Real UsageMeter and InMemoryUsageSink.
The autouse fixture returns None from the gap fetch. These tests patch it again.
"""

from __future__ import annotations

import asyncio

import pytest

from xaikit import (
    AsyncXaiClient,
    InMemoryUsageSink,
    MockChatProvider,
    ModelInfo,
    UsageMeter,
    default_retry_policy,
    list_models,
)
from xaikit.catalog import clear_catalog_cache, inject_catalog
from xaikit.pricing import clear_public_price_cache

_EXC_TYPES = (ConnectionError, RuntimeError, ValueError)
_FETCH_ERRORS = (
    OSError,
    TimeoutError,
    ValueError,
    KeyError,
    ConnectionError,
    RuntimeError,
    Exception,
)


def _reset() -> None:
    inject_catalog(None)
    clear_catalog_cache()
    clear_public_price_cache()


def _partial_grok_47() -> ModelInfo:
    return ModelInfo(
        id="grok-4.7",
        capabilities=["chat"],
        input_per_million=2.0,
        output_per_million=6.0,
    )


def _load_partial_grok_47() -> None:
    inject_catalog([_partial_grok_47()])
    list_models()


def _install(monkeypatch: pytest.MonkeyPatch, fetch) -> dict[str, int]:
    calls = {"n": 0}

    def wrapped(url: str = "", timeout: float = 10.0):
        calls["n"] += 1
        return fetch(url=url, timeout=timeout)

    monkeypatch.setattr("xaikit.pricing.fetch_public_price_payload", wrapped)
    clear_public_price_cache()
    return calls


def _raising(exc_type: type[BaseException]):
    def fetch(url: str = "", timeout: float = 10.0) -> None:
        raise exc_type("gap down")

    return fetch


def _quiet(url: str = "", timeout: float = 10.0) -> None:
    return None


def _cost(model: str, usage: dict[str, int]) -> float | None:
    sink = InMemoryUsageSink()
    meter = UsageMeter(sink=sink)
    meter.record(purpose="t", model=model, usage=usage)
    saved = list(sink.iter_events())
    assert len(saved) == 1
    return saved[0].estimated_usd


@pytest.mark.parametrize("exc_type", _EXC_TYPES)
def test_price_3_long_prompt_fetch_error_records_bundled_cost(
    monkeypatch: pytest.MonkeyPatch,
    exc_type: type[BaseException],
) -> None:
    usage = {"prompt_tokens": 200000, "completion_tokens": 0}
    try:
        _reset()
        calls = _install(monkeypatch, _raising(exc_type))
        empty = _cost("grok-4.7", usage)

        _load_partial_grok_47()
        clear_public_price_cache()
        loaded = _cost("grok-4.7", usage)
    finally:
        _reset()

    assert empty == 0.8
    assert loaded == 0.8
    assert empty != 0.4
    assert calls["n"] == 0


@pytest.mark.parametrize("exc_type", _EXC_TYPES)
def test_price_3_cached_long_prompt_fetch_error_records_bundled_cost(
    monkeypatch: pytest.MonkeyPatch,
    exc_type: type[BaseException],
) -> None:
    usage = {
        "prompt_tokens": 1_000_000,
        "completion_tokens": 0,
        "cached_tokens": 400_000,
    }
    try:
        _reset()
        calls = _install(monkeypatch, _raising(exc_type))
        empty = _cost("grok-4.7", usage)

        _load_partial_grok_47()
        clear_public_price_cache()
        loaded = _cost("grok-4.7", usage)
    finally:
        _reset()

    assert empty == 2.8
    assert loaded == 2.8
    assert empty != 2.0
    assert calls["n"] == 0


@pytest.mark.parametrize("exc_type", _FETCH_ERRORS)
def test_price_3_unknown_model_fetch_error_records_none(
    monkeypatch: pytest.MonkeyPatch,
    exc_type: type[BaseException],
) -> None:
    usage = {"prompt_tokens": 1000, "completion_tokens": 0}
    try:
        _reset()
        calls = _install(monkeypatch, _raising(exc_type))
        sink = InMemoryUsageSink()
        meter = UsageMeter(sink=sink)
        event = meter.record(purpose="t", model="grok-9.9", usage=usage)
        saved = list(sink.iter_events())
    finally:
        _reset()

    assert saved == [event]
    assert event.estimated_usd is None
    assert calls["n"] == 1


def test_raised_fetch_is_cached_for_later_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    usage = {"prompt_tokens": 1000, "completion_tokens": 0}
    try:
        _reset()
        calls = _install(monkeypatch, _raising(ConnectionError))
        sink = InMemoryUsageSink()
        meter = UsageMeter(sink=sink)
        events = [
            meter.record(purpose="t", model="grok-9.9", usage=usage)
            for _ in range(3)
        ]
        saved = list(sink.iter_events())
    finally:
        _reset()

    assert saved == events
    assert [event.estimated_usd for event in events] == [None, None, None]
    assert calls["n"] == 1


def test_price_4_short_prompt_does_not_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    usage = {"prompt_tokens": 100000, "completion_tokens": 0}
    try:
        _reset()
        calls = _install(monkeypatch, _quiet)

        empty = _cost("grok-4.7", usage)
        assert empty == 0.2
        assert calls["n"] == 0

        _load_partial_grok_47()
        clear_public_price_cache()
        loaded = _cost("grok-4.7", usage)
        assert loaded == 0.2
        assert calls["n"] == 0

        _reset()
        calls = _install(monkeypatch, _quiet)
        bundled = _cost("grok-4", usage)
        assert bundled == 0.3
        assert calls["n"] == 0
    finally:
        _reset()


def test_price_4_ticks_do_not_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    usage = {
        "prompt_tokens": 100000,
        "completion_tokens": 0,
        "cost_in_usd_ticks": 10_000_000_000,
    }
    try:
        _reset()
        calls = _install(monkeypatch, _quiet)
        cost = _cost("grok-4.8", usage)
    finally:
        _reset()

    assert cost == 1.0
    assert calls["n"] == 0


def test_price_4_long_and_cached_prompts_do_not_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    long_usage = {"prompt_tokens": 200000, "completion_tokens": 0}
    cached_usage = {
        "prompt_tokens": 1_000_000,
        "completion_tokens": 0,
        "cached_tokens": 400_000,
    }
    try:
        _reset()
        calls = _install(monkeypatch, _quiet)
        empty_long = _cost("grok-4.7", long_usage)
        empty_cached = _cost("grok-4.7", cached_usage)

        _load_partial_grok_47()
        clear_public_price_cache()
        loaded_long = _cost("grok-4.7", long_usage)
        loaded_cached = _cost("grok-4.7", cached_usage)
    finally:
        _reset()

    assert empty_long == 0.8
    assert loaded_long == 0.8
    assert empty_cached == 2.8
    assert loaded_cached == 2.8
    assert calls["n"] == 0


def _async_chat(model: str, usage: dict[str, int]) -> tuple[str, float | None]:
    sink = InMemoryUsageSink()
    provider = MockChatProvider(replies="ok", default_usage=usage)
    client = AsyncXaiClient(
        provider=provider,
        model=model,
        image_model="grok-imagine-image",
        video_model="grok-imagine-video",
        voice_model="grok-voice-think-fast-1.0",
        usage_meter=UsageMeter(sink=sink),
        retry_policy=default_retry_policy(max_attempts=1, backoff_seconds=0.0),
    )
    inject_catalog(None)
    clear_catalog_cache()

    async def _run() -> str:
        resp = await client.chat(
            [{"role": "user", "content": "hi"}],
            purpose="t",
        )
        return resp.content

    content = asyncio.run(_run())
    saved = list(sink.iter_events())
    assert len(saved) == 1
    return content, saved[0].estimated_usd


def test_async_client_shares_the_meter_when_fetch_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    try:
        _reset()
        calls = _install(monkeypatch, _raising(ConnectionError))
        content, cost = _async_chat(
            "grok-4.7",
            {"prompt_tokens": 200000, "completion_tokens": 0},
        )
        unknown_content, unknown_cost = _async_chat(
            "grok-9.9",
            {"prompt_tokens": 1000, "completion_tokens": 0},
        )
    finally:
        _reset()

    assert content == "ok"
    assert cost == 0.8
    assert unknown_content == "ok"
    assert unknown_cost is None
    assert calls["n"] == 1


def test_async_raised_fetch_is_cached_for_later_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    usage = {"prompt_tokens": 1000, "completion_tokens": 0}
    try:
        _reset()
        calls = _install(monkeypatch, _raising(ConnectionError))
        sink = InMemoryUsageSink()
        provider = MockChatProvider(replies="ok", default_usage=usage)
        client = AsyncXaiClient(
            provider=provider,
            model="grok-9.9",
            image_model="grok-imagine-image",
            video_model="grok-imagine-video",
            voice_model="grok-voice-think-fast-1.0",
            usage_meter=UsageMeter(sink=sink),
            retry_policy=default_retry_policy(max_attempts=1, backoff_seconds=0.0),
        )
        inject_catalog(None)
        clear_catalog_cache()

        async def _run() -> list[str]:
            contents: list[str] = []
            for _ in range(3):
                resp = await client.chat(
                    [{"role": "user", "content": "hi"}],
                    purpose="t",
                )
                contents.append(resp.content)
            return contents

        contents = asyncio.run(_run())
        saved = list(sink.iter_events())
    finally:
        _reset()

    assert contents == ["ok", "ok", "ok"]
    assert len(saved) == 3
    assert [event.estimated_usd for event in saved] == [None, None, None]
    assert calls["n"] == 1
