"""Catalog mapping + resolve helpers (offline)."""

from __future__ import annotations

from types import SimpleNamespace

from xaikit.catalog import (
    BOOTSTRAP_MODEL,
    ModelInfo,
    cheapest_model,
    model_info_from_language_proto,
    prefer_latest_model,
    resolve_model_selection,
)


def _lm(**kwargs: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        "name": "grok-4.5",
        "aliases": [],
        "version": "1.0",
        "output_modalities": [1],  # TEXT
        "input_modalities": [1],
        "created": None,
        "max_prompt_length": 128000,
        "prompt_text_token_price": None,
        "completion_text_token_price": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_non_reasoning_slug_is_not_tagged_reasoning() -> None:
    info = model_info_from_language_proto(
        _lm(
            name="grok-4.20-0309-non-reasoning",
            aliases=["grok-4.20-non-reasoning", "grok-4.20-beta-latest-non-reasoning"],
        )
    )
    assert "reasoning" not in info.capabilities
    assert "chat" in info.capabilities


def test_reasoning_slug_is_tagged_reasoning() -> None:
    info = model_info_from_language_proto(
        _lm(
            name="grok-4.20-0309-reasoning",
            aliases=["grok-4.20-reasoning-latest", "grok-4.20"],
        )
    )
    assert "reasoning" in info.capabilities


def test_plain_flagship_name_is_not_tagged_reasoning() -> None:
    info = model_info_from_language_proto(_lm(name="grok-4.6", aliases=[]))
    assert "reasoning" not in info.capabilities


def test_resolve_pin_beats_intent() -> None:
    cat = [
        ModelInfo(id="grok-4.5", capabilities=["chat"], input_per_million=20.0),
        ModelInfo(id="cheap", capabilities=["chat"], input_per_million=1.0),
    ]
    sel = resolve_model_selection(pin="grok-4.5", intent="cheapest", catalog=cat)
    assert sel.model_id == "grok-4.5"
    assert sel.source == "pin"


def test_resolve_cheapest_and_best() -> None:
    cat = [
        ModelInfo(id="grok-4.5", capabilities=["chat"], input_per_million=20.0, created=2),
        ModelInfo(id="grok-3-mini", capabilities=["chat"], input_per_million=0.3, created=1),
    ]
    cheap = resolve_model_selection(intent="cheapest", catalog=cat)
    assert cheap.model_id == "grok-3-mini"
    assert cheap.source == "intent:cheapest"
    best = resolve_model_selection(intent="best", catalog=cat)
    assert best.model_id == "grok-4.5"
    assert best.source == "intent:best"


def test_unknown_intent_falls_through_to_prefer_latest() -> None:
    cat = [
        ModelInfo(id=BOOTSTRAP_MODEL, capabilities=["chat"], created=1),
        ModelInfo(id="grok-4.6", capabilities=["chat"], created=2),
    ]
    sel = resolve_model_selection(intent="nope", catalog=cat)
    assert sel.model_id == prefer_latest_model(cat) == "grok-4.6"


def test_cheapest_ignores_unpriced_when_priced_exist() -> None:
    cat = [
        ModelInfo(id="mystery", capabilities=["chat"]),
        ModelInfo(id="mini", capabilities=["chat"], input_per_million=0.5),
    ]
    assert cheapest_model(cat) == "mini"
