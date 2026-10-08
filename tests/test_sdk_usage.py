"""Chat SDK usage reaches the meter: server ticks, else the price table."""

from __future__ import annotations

import pytest

from xaikit import SdkChatProvider, UsageMeter
from xaikit.catalog import clear_catalog_cache
from xaikit.pricing import ModelPrice, PriceTable, clear_public_price_cache
from xaikit.provider import _usage_from_sdk


class _Usage:
    def __init__(
        self,
        *,
        prompt_tokens: int,
        completion_tokens: int,
        cost_in_usd_ticks: int,
        cached_prompt_text_tokens: int,
        ticks_set: bool,
    ) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.cost_in_usd_ticks = cost_in_usd_ticks
        self.cached_prompt_text_tokens = cached_prompt_text_tokens
        self._ticks_set = ticks_set

    def HasField(self, name: str) -> bool:
        if name == "cost_in_usd_ticks":
            return self._ticks_set
        return False


class _Sample:
    def __init__(self, usage: _Usage) -> None:
        self.usage = usage
        self.content = "ok"
        self.reasoning_content = None
        self.finish_reason = "stop"
        self.tool_calls = None
        self.service_tier = None


class _Chat:
    def __init__(self, sample: _Sample) -> None:
        self._sample = sample

    def sample(self) -> _Sample:
        return self._sample


class _ChatApi:
    def __init__(self, sample: _Sample) -> None:
        self._sample = sample

    def create(self, **kwargs: object) -> _Chat:
        return _Chat(self._sample)


class _Client:
    def __init__(self, sample: _Sample) -> None:
        self.chat = _ChatApi(sample)


def _usage(
    *,
    ticks_set: bool,
    ticks: int = 0,
    cached: int = 0,
    prompt: int = 1_000_000,
    completion: int = 0,
) -> _Usage:
    return _Usage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        cost_in_usd_ticks=ticks,
        cached_prompt_text_tokens=cached,
        ticks_set=ticks_set,
    )


def _provider_usage(usage: _Usage) -> dict:
    provider = SdkChatProvider(_Client(_Sample(usage)))
    response = provider.complete(
        [{"role": "user", "content": "hi"}],
        model="grok-4.7",
    )
    assert response.usage == _usage_from_sdk(_Sample(usage))
    assert response.usage is not None
    return response.usage


def _meter(monkeypatch: pytest.MonkeyPatch, price_table: PriceTable | None = None) -> UsageMeter:
    clear_catalog_cache()
    clear_public_price_cache()
    monkeypatch.setattr("xaikit.usage.public_price_table", lambda **kwargs: None)
    return UsageMeter(price_table=price_table)


def test_sdk_usage_ticks_and_cached_tokens_reach_the_meter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    usage = _provider_usage(
        _usage(ticks_set=True, ticks=10_000_000_000, cached=400_000)
    )
    assert usage["cost_in_usd_ticks"] == 10_000_000_000
    assert usage["cached_prompt_text_tokens"] == 400_000
    assert usage["prompt_tokens"] == 1_000_000

    event = _meter(monkeypatch).record(
        purpose="ticks",
        model="grok-4.7",
        usage=usage,
    )
    # 10_000_000_000 ticks = $1. Table rate for 1M grok-4.7 input tokens is $2.
    assert event.estimated_usd == 1.0


def test_unset_sdk_ticks_fall_through_to_price_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    usage = _provider_usage(_usage(ticks_set=False, ticks=0, cached=400_000))
    assert "cost_in_usd_ticks" not in usage
    assert usage["cached_prompt_text_tokens"] == 400_000

    shipped = _meter(monkeypatch).record(
        purpose="table",
        model="grok-4.7",
        usage=usage,
    )
    # grok-4.7 shipped row has no cached rate, so the full prompt bills at $2/M.
    assert shipped.estimated_usd == 2.0

    cached_table = PriceTable(
        models={
            "grok-4.7": ModelPrice(
                input_per_million=2.0,
                output_per_million=6.0,
                cached_input_per_million=0.5,
            )
        }
    )
    discounted = _meter(monkeypatch, cached_table).record(
        purpose="cached",
        model="grok-4.7",
        usage=usage,
    )
    # 600k uncached at $2/M + 400k cached at $0.50/M.
    assert discounted.estimated_usd == 1.4


def test_zero_cached_prompt_text_tokens_are_omitted() -> None:
    usage = _usage_from_sdk(_Sample(_usage(ticks_set=False, ticks=0, cached=0)))
    assert usage == {"prompt_tokens": 1_000_000, "completion_tokens": 0}
