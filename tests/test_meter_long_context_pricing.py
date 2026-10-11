"""Long and cached rates missing on a catalog row come from the gap file.

XK-AC-PRICE-1, XK-AC-PRICE-2. Real UsageMeter and a real catalog inject.
The fetch is patched to the committed gap file so the run stays offline.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from xaikit import InMemoryUsageSink, ModelInfo, UsageMeter, list_models
from xaikit.catalog import clear_catalog_cache, inject_catalog
from xaikit.pricing import clear_public_price_cache

_GAP_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "data" / "xai_public_prices.json"
)


def _gap_payload() -> dict[str, Any]:
    return json.loads(_GAP_PATH.read_text(encoding="utf-8"))


def _install_gap(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any] | None
) -> list[int]:
    fetches: list[int] = []

    def fake_fetch(url: str = "", timeout: float = 10.0) -> dict[str, Any] | None:
        fetches.append(1)
        return payload

    monkeypatch.setattr("xaikit.pricing.fetch_public_price_payload", fake_fetch)
    clear_public_price_cache()
    return fetches


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
    clear_public_price_cache()


def test_price_1_long_prompt_matches_with_or_without_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_gap(monkeypatch, _gap_payload())
    usage = {"prompt_tokens": 200000, "completion_tokens": 0}
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


def test_price_2_cached_long_prompt_matches_gap_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _gap_payload()
    _install_gap(monkeypatch, payload)
    row = payload["models"]["grok-4.7"]
    figure = (600_000 / 1_000_000) * row["input_long_per_million"] + (
        400_000 / 1_000_000
    ) * row["cached_input_long_per_million"]
    assert figure == 2.8

    cached_keys = (
        "cached_tokens",
        "cached_prompt_tokens",
        "cached_prompt_text_tokens",
    )
    try:
        costs: list[tuple[float | None, float | None]] = []
        for key in cached_keys:
            usage = {
                "prompt_tokens": 1_000_000,
                "completion_tokens": 0,
                key: 400_000,
            }
            inject_catalog(None)
            clear_catalog_cache()
            clear_public_price_cache()
            empty = _record("grok-4.7", usage)

            inject_catalog([_partial("grok-4.7")])
            list_models()
            clear_public_price_cache()
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


def test_server_ticks_win_over_the_long_rate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetches = _install_gap(monkeypatch, _gap_payload())
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
    assert fetches == []


def test_missing_short_cached_rate_comes_from_the_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_gap(monkeypatch, _gap_payload())
    usage = {
        "prompt_tokens": 100000,
        "completion_tokens": 0,
        "cached_tokens": 40_000,
    }
    try:
        inject_catalog([_partial("grok-4.7")])
        list_models()
        cost = _record("grok-4.7", usage)
    finally:
        _reset()

    assert cost == 0.14
    assert cost != 0.2


def test_long_output_rate_comes_from_the_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_gap(monkeypatch, _gap_payload())
    usage = {"prompt_tokens": 200000, "completion_tokens": 1000}
    try:
        inject_catalog([_partial("grok-4.7")])
        list_models()
        cost = _record("grok-4.7", usage)
    finally:
        _reset()

    assert cost == 0.812
    assert cost != 0.406


def test_catalog_long_input_rate_beats_the_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_gap(monkeypatch, _gap_payload())
    usage = {"prompt_tokens": 200000, "completion_tokens": 0}
    try:
        inject_catalog([_partial("grok-4.7", input_long_per_million=8.0)])
        list_models()
        cost = _record("grok-4.7", usage)
    finally:
        _reset()

    assert cost == 1.6
    assert cost != 0.8


def test_catalog_cached_rate_beats_the_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_gap(monkeypatch, _gap_payload())
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
    assert cost != 0.14


def test_catalog_long_cached_rate_beats_the_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_gap(monkeypatch, _gap_payload())
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


def test_short_prompt_stays_on_the_short_rate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetches = _install_gap(monkeypatch, _gap_payload())
    usage = {"prompt_tokens": 100000, "completion_tokens": 0}
    try:
        inject_catalog(None)
        clear_catalog_cache()
        empty = _record("grok-4.7", usage)

        inject_catalog([_partial("grok-4.7")])
        list_models()
        clear_public_price_cache()
        before = len(fetches)
        loaded = _record("grok-4.7", usage)
        after = len(fetches)
    finally:
        _reset()

    assert empty == 0.2
    assert loaded == 0.2
    assert empty == loaded
    assert loaded != 0.4
    assert after == before


def test_missing_gap_keeps_the_short_catalog_rate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_gap(monkeypatch, None)
    usage = {"prompt_tokens": 200000, "completion_tokens": 0}
    try:
        inject_catalog([_partial("grok-4.7")])
        list_models()
        cost = _record("grok-4.7", usage)
    finally:
        _reset()

    assert cost == 0.4


def test_unknown_model_stays_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_gap(monkeypatch, _gap_payload())
    try:
        inject_catalog(None)
        clear_catalog_cache()
        cost = _record(
            "not-a-grok",
            {"prompt_tokens": 200000, "completion_tokens": 0},
        )
    finally:
        _reset()

    assert cost is None


def test_gap_row_without_long_rates_keeps_the_catalog_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_gap(monkeypatch, _gap_payload())
    usage = {"prompt_tokens": 200000, "completion_tokens": 0}
    try:
        inject_catalog([_partial("grok-voice-latest")])
        list_models()
        cost = _record("grok-voice-latest", usage)
    finally:
        _reset()

    assert cost == 0.4
    assert cost != 0.0


def test_dated_id_uses_the_gap_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_gap(monkeypatch, _gap_payload())
    usage = {"prompt_tokens": 200000, "completion_tokens": 0}
    try:
        inject_catalog([_partial("grok-4.7-latest")])
        list_models()
        cost = _record("grok-4.7-latest", usage)
    finally:
        _reset()

    assert cost == 0.8
    assert cost != 0.4
