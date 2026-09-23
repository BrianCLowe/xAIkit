"""Unpinned clients follow the cached catalog; the meter fills price gaps."""

from __future__ import annotations

import pytest

from xaikit import MockChatProvider, UsageMeter, XaiClient, default_retry_policy
from xaikit.catalog import (
    ModelInfo,
    clear_catalog_cache,
    inject_catalog,
    list_models,
    set_test_fetch,
)
from xaikit.pricing import clear_public_price_cache, public_price_table


def _client(**kwargs: object) -> XaiClient:
    kwargs.setdefault("retry_policy", default_retry_policy(max_attempts=1))
    return XaiClient(**kwargs)  # type: ignore[arg-type]


def test_unpinned_client_reresolves_after_catalog_cache_clear() -> None:
    generation = {"n": 1}

    def fetch(key: str) -> list[ModelInfo]:
        assert key == "test-key"
        if generation["n"] == 1:
            ids = ("grok-4.7", "grok-4.8")
        else:
            ids = ("grok-4.8", "grok-4.9")
        return [
            ModelInfo(
                id=mid,
                capabilities=["chat"],
                input_per_million=2.0,
                output_per_million=6.0,
            )
            for mid in ids
        ]

    set_test_fetch(fetch)
    clear_catalog_cache()
    try:
        provider = MockChatProvider(replies="ok")
        client = _client(api_key="test-key", provider=provider)
        assert client.model == "grok-4.8"
        client.chat([{"role": "user", "content": "hi"}])
        assert provider.calls[0]["model"] == "grok-4.8"

        generation["n"] = 2
        clear_catalog_cache()
        client.chat([{"role": "user", "content": "again"}])
        assert client.model == "grok-4.9"
        assert provider.calls[1]["model"] == "grok-4.9"

        pinned_provider = MockChatProvider(replies="stay")
        pinned = _client(
            api_key="test-key",
            model="grok-4.3",
            provider=pinned_provider,
        )
        clear_catalog_cache()
        generation["n"] = 3
        pinned.chat([{"role": "user", "content": "pin"}])
        assert pinned.model == "grok-4.3"
        assert pinned_provider.calls[0]["model"] == "grok-4.3"
    finally:
        set_test_fetch(None)
        clear_catalog_cache()


def test_meter_uses_ticks_then_catalog_then_gap_then_static_then_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetches: list[int] = []

    def fake_fetch(url: str = "", timeout: float = 10.0) -> dict:
        fetches.append(1)
        return {
            "source_url": "https://docs.x.ai/developers/models",
            "models": {
                "grok-4.8": {
                    "input_per_million": 4.0,
                    "output_per_million": 8.0,
                }
            },
        }

    monkeypatch.setattr("xaikit.pricing.fetch_public_price_payload", fake_fetch)
    clear_public_price_cache()
    inject_catalog(None)
    clear_catalog_cache()
    meter = UsageMeter()
    try:
        ticks = meter.record(
            purpose="ticks",
            model="grok-4.8",
            usage={
                "cost_in_usd_ticks": 10_000_000_000,
                "prompt_tokens": 1_000_000,
                "completion_tokens": 0,
            },
        )
        assert ticks.estimated_usd == 1.0
        assert fetches == []

        inject_catalog(
            [
                ModelInfo(
                    id="grok-4.8",
                    capabilities=["chat"],
                    input_per_million=2.0,
                    output_per_million=6.0,
                )
            ]
        )
        list_models()
        catalog = meter.record(
            purpose="catalog",
            model="grok-4.8",
            usage={"prompt_tokens": 1_000_000, "completion_tokens": 0},
        )
        assert catalog.estimated_usd == 2.0
        assert fetches == []

        inject_catalog(None)
        clear_catalog_cache()
        clear_public_price_cache()
        gap = meter.record(
            purpose="gap",
            model="grok-4.8",
            usage={"prompt_tokens": 1_000_000, "completion_tokens": 0},
        )
        assert gap.estimated_usd == 4.0
        assert len(fetches) == 1
        again = meter.record(
            purpose="gap-cached",
            model="grok-4.8",
            usage={"prompt_tokens": 1_000_000, "completion_tokens": 0},
        )
        assert again.estimated_usd == 4.0
        assert len(fetches) == 1

        clear_public_price_cache()

        def empty_gap(url: str = "", timeout: float = 10.0) -> dict:
            fetches.append(1)
            return {"models": {"other-model": {"input_per_million": 9.0, "output_per_million": 9.0}}}

        monkeypatch.setattr("xaikit.pricing.fetch_public_price_payload", empty_gap)
        static = meter.record(
            purpose="static",
            model="grok-4.7",
            usage={"prompt_tokens": 1_000_000, "completion_tokens": 0},
        )
        assert static.estimated_usd == 2.0

        clear_public_price_cache()
        missing = meter.record(
            purpose="none",
            model="grok-9.9",
            usage={"prompt_tokens": 1_000_000, "completion_tokens": 0},
        )
        assert missing.estimated_usd is None
    finally:
        inject_catalog(None)
        clear_catalog_cache()
        clear_public_price_cache()


def test_public_price_table_fetches_at_most_once_per_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetches: list[float] = []

    def fake_fetch(url: str = "", timeout: float = 10.0) -> dict:
        fetches.append(timeout)
        return {
            "models": {
                "grok-4.8": {"input_per_million": 4.0, "output_per_million": 8.0}
            }
        }

    monkeypatch.setattr("xaikit.pricing.fetch_public_price_payload", fake_fetch)
    clear_public_price_cache()
    first = public_price_table(now=1_000.0)
    second = public_price_table(now=1_000.0 + 3600)
    assert first is not None and second is not None
    assert first.price_for("grok-4.8") is not None
    assert len(fetches) == 1
    third = public_price_table(now=1_000.0 + 24 * 3600)
    assert third is not None
    assert len(fetches) == 2
    clear_public_price_cache()
