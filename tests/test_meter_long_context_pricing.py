"""Long and cached rates missing on a catalog row come from the shipped table.

XK-AC-PRICE-1, XK-AC-PRICE-2. Real UsageMeter and a real catalog inject.
The conftest gap fetch stays None. Nothing here patches it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from xaikit import InMemoryUsageSink, ModelInfo, UsageMeter, list_models
from xaikit.catalog import clear_catalog_cache, inject_catalog
from xaikit.pricing import default_price_table

_GAP_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "data" / "xai_public_prices.json"
)
_RATE_FIELDS = (
    "cached_input_per_million",
    "input_long_per_million",
    "output_long_per_million",
    "cached_input_long_per_million",
)
_CACHED_KEYS = (
    "cached_tokens",
    "cached_prompt_tokens",
    "cached_prompt_text_tokens",
)


def _gap_payload() -> dict[str, Any]:
    return json.loads(_GAP_PATH.read_text(encoding="utf-8"))


def _partial(model_id: str, **rates: float) -> ModelInfo:
    return ModelInfo(
        id=model_id,
        capabilities=["chat"],
        input_per_million=rates.get("input_per_million", 2.0),
        output_per_million=rates.get("output_per_million", 6.0),
        cached_input_per_million=rates.get("cached_input_per_million"),
        input_long_per_million=rates.get("input_long_per_million"),
        output_long_per_million=rates.get("output_long_per_million"),
        cached_input_long_per_million=rates.get("cached_input_long_per_million"),
    )


def _record(model: str, usage: dict[str, Any]) -> float | None:
    meter = UsageMeter(sink=InMemoryUsageSink())
    event = meter.record(purpose="t", model=model, usage=usage)
    return event.estimated_usd


def _reset() -> None:
    inject_catalog(None)
    clear_catalog_cache()


def _prompt_only(tokens: int) -> dict[str, int]:
    return {"prompt_tokens": tokens, "completion_tokens": 0}


def test_price_1_long_prompt_matches_with_or_without_catalog() -> None:
    usage = _prompt_only(200000)
    try:
        inject_catalog(None)
        clear_catalog_cache()
        empty = _record("grok-4.7", usage)

        inject_catalog([_partial("grok-4.7")])
        list_models()
        loaded = _record("grok-4.7", usage)
    finally:
        _reset()

    assert empty == 0.8
    assert loaded == 0.8
    assert empty == loaded
    assert loaded != 0.4


def test_price_2_cached_long_prompt_matches_gap_file() -> None:
    row = _gap_payload()["models"]["grok-4.7"]
    figure = (600_000 / 1_000_000) * row["input_long_per_million"] + (
        400_000 / 1_000_000
    ) * row["cached_input_long_per_million"]
    assert figure == 2.8

    try:
        costs: list[tuple[float | None, float | None]] = []
        for key in _CACHED_KEYS:
            usage = _prompt_only(1_000_000)
            usage[key] = 400_000
            inject_catalog(None)
            clear_catalog_cache()
            empty = _record("grok-4.7", usage)

            inject_catalog([_partial("grok-4.7")])
            list_models()
            loaded = _record("grok-4.7", usage)
            costs.append((empty, loaded))
    finally:
        _reset()

    for empty, loaded in costs:
        assert empty == 2.8
        assert loaded == 2.8
        assert empty == figure
        assert loaded == figure
        assert loaded != 2.0


def test_long_context_boundary_is_inclusive() -> None:
    expected = {
        199999: round(199999 / 1_000_000 * 2.0, 8),
        200000: round(200000 / 1_000_000 * 4.0, 8),
        200001: round(200001 / 1_000_000 * 4.0, 8),
    }
    wrong_tier = {
        199999: round(199999 / 1_000_000 * 4.0, 8),
        200000: round(200000 / 1_000_000 * 2.0, 8),
        200001: round(200001 / 1_000_000 * 2.0, 8),
    }
    try:
        seen: list[tuple[int, float | None, float | None]] = []
        for tokens in (199999, 200000, 200001):
            usage = _prompt_only(tokens)
            inject_catalog(None)
            clear_catalog_cache()
            empty = _record("grok-4.7", usage)
            inject_catalog([_partial("grok-4.7")])
            list_models()
            loaded = _record("grok-4.7", usage)
            seen.append((tokens, empty, loaded))
    finally:
        _reset()

    for tokens, empty, loaded in seen:
        assert empty == expected[tokens]
        assert loaded == expected[tokens]
        assert empty == loaded
        assert empty != wrong_tier[tokens]


def test_short_prompt_keeps_the_catalog_cached_rate() -> None:
    usage = {
        "prompt_tokens": 100000,
        "completion_tokens": 0,
        "cached_tokens": 40_000,
    }
    try:
        inject_catalog([_partial("grok-4.7", cached_input_per_million=9.0)])
        list_models()
        cost = _record("grok-4.7", usage)
    finally:
        _reset()

    assert cost == 0.48
    assert cost != 0.16


def test_server_ticks_win_over_the_long_rate() -> None:
    usage = {
        "prompt_tokens": 200000,
        "completion_tokens": 0,
        "cost_in_usd_ticks": 10_000_000_000,
    }
    try:
        inject_catalog([_partial("grok-4.7")])
        list_models()
        cost = _record("grok-4.7", usage)
    finally:
        _reset()

    assert cost == 1.0
    assert cost != 0.8


def test_catalog_long_input_is_not_overwritten() -> None:
    try:
        inject_catalog([_partial("grok-4.7", input_long_per_million=8.0)])
        list_models()
        cost = _record("grok-4.7", _prompt_only(200000))
    finally:
        _reset()

    assert cost == 1.6
    assert cost != 0.8


def test_catalog_long_output_is_not_overwritten() -> None:
    usage = {"prompt_tokens": 200000, "completion_tokens": 1000}
    try:
        inject_catalog([_partial("grok-4.7", output_long_per_million=99.0)])
        list_models()
        cost = _record("grok-4.7", usage)
    finally:
        _reset()

    assert cost == 0.899
    assert cost != 0.812


def test_catalog_long_cached_rate_is_not_overwritten() -> None:
    usage = {
        "prompt_tokens": 1_000_000,
        "completion_tokens": 0,
        "cached_tokens": 400_000,
    }
    try:
        inject_catalog(
            [_partial("grok-4.7", cached_input_long_per_million=3.0)]
        )
        list_models()
        cost = _record("grok-4.7", usage)
    finally:
        _reset()

    assert cost == 3.6
    assert cost != 2.8


def test_catalog_cached_input_is_not_overwritten_on_a_short_prompt() -> None:
    usage = {
        "prompt_tokens": 100000,
        "completion_tokens": 0,
        "cached_prompt_tokens": 40_000,
    }
    try:
        inject_catalog([_partial("grok-4.7", cached_input_per_million=9.0)])
        list_models()
        cost = _record("grok-4.7", usage)
    finally:
        _reset()

    assert cost == 0.48
    assert cost != round(60_000 / 1_000_000 * 2.0 + 40_000 / 1_000_000 * 0.5, 8)


def test_grok_4_5_long_rate_prices_offline() -> None:
    usage = {
        "prompt_tokens": 1_000_000,
        "completion_tokens": 0,
        "cached_prompt_text_tokens": 400_000,
    }
    try:
        inject_catalog(None)
        clear_catalog_cache()
        empty = _record("grok-4.5", usage)
        inject_catalog(
            [
                _partial(
                    "grok-4.5",
                    input_per_million=2.0,
                    output_per_million=6.0,
                )
            ]
        )
        list_models()
        loaded = _record("grok-4.5", usage)
    finally:
        _reset()

    assert empty == 2.64
    assert loaded == 2.64
    assert empty != 2.0


def test_bundled_long_and_cached_rates_match_the_gap_file() -> None:
    payload = _gap_payload()
    table = default_price_table()
    compared = 0
    for model_id, row in payload["models"].items():
        if not isinstance(row, dict):
            continue
        present = {
            name: row[name]
            for name in _RATE_FIELDS
            if name in row and row[name] is not None
        }
        if not present:
            continue
        price = table.price_for(model_id)
        assert price is not None
        for name, expected in present.items():
            assert getattr(price, name) == expected
            compared += 1
    assert compared > 0


def test_unknown_model_stays_unset() -> None:
    try:
        inject_catalog(None)
        clear_catalog_cache()
        cost = _record("not-a-grok", _prompt_only(200000))
    finally:
        _reset()

    assert cost is None
