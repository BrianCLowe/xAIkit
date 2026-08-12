"""Catalog mapping + resolve helpers (offline)."""

from __future__ import annotations

from types import SimpleNamespace

from xaikit.catalog import (
    BOOTSTRAP_MODEL,
    ModelInfo,
    economy_model,
    cheapest_model,
    intent_options,
    model_info_from_language_proto,
    normalize_intent,
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


def _live_like_catalog() -> list[ModelInfo]:
    """Shape of the 2026-08-12 xAI language catalog (prices + created)."""
    return [
        ModelInfo(
            id="grok-4.20-0309-non-reasoning",
            capabilities=["chat", "text"],
            input_per_million=12.5,
            created=1773014400,
        ),
        ModelInfo(
            id="grok-4.20-0309-reasoning",
            capabilities=["chat", "text", "reasoning"],
            input_per_million=12.5,
            created=1773014400,
        ),
        ModelInfo(
            id="grok-4.20-multi-agent-0309",
            capabilities=["chat", "text"],
            input_per_million=12.5,
            created=1773014400,
        ),
        ModelInfo(
            id="grok-4.3",
            capabilities=["chat", "text"],
            input_per_million=12.5,
            created=1776384000,
        ),
        ModelInfo(
            id="grok-4.5",
            capabilities=["chat", "text"],
            input_per_million=20.0,
            created=1782691200,
            aliases=["grok-4.5-latest", "grok-build-latest"],
        ),
        ModelInfo(
            id="grok-4.6",
            capabilities=["chat", "text"],
            input_per_million=20.0,
            created=1785974400,
        ),
        ModelInfo(
            id="grok-build-0.1",
            capabilities=["chat", "text"],
            input_per_million=10.0,
            created=1776297600,
            aliases=["grok-code-fast-1"],
        ),
    ]


def test_three_intents_on_live_like_lineup() -> None:
    cat = _live_like_catalog()
    cheap = resolve_model_selection(intent="cheapest", catalog=cat)
    economy = resolve_model_selection(intent="economy", catalog=cat)
    best = resolve_model_selection(intent="best", catalog=cat)
    assert cheap.model_id == "grok-4.20-0309-non-reasoning"
    assert cheap.source == "intent:cheapest"
    assert economy.model_id == "grok-4.3"
    assert economy.source == "intent:economy"
    assert best.model_id == "grok-4.6"
    assert best.source == "intent:best"
    # coding SKU is cheaper on paper but excluded from general intents
    assert cheapest_model(cat) != "grok-build-0.1"
    # grok-4.5 alias grok-build-latest must not exclude the flagship family
    assert best.model_id == "grok-4.6"


def test_intent_options_canonical_names() -> None:
    assert intent_options() == ["cheapest", "economy", "best"]
    assert normalize_intent("economy") == "economy"
    assert normalize_intent("best_value") is None
    assert normalize_intent("value") is None
    sel = resolve_model_selection(intent="economy", catalog=_live_like_catalog())
    assert sel.model_id == "grok-4.3"
    assert sel.source == "intent:economy"


def test_intents_overlap_when_lineup_is_thin() -> None:
    two = [
        ModelInfo(id="grok-4.3", capabilities=["chat"], input_per_million=12.5, created=1),
        ModelInfo(id="grok-4.6", capabilities=["chat"], input_per_million=20.0, created=2),
    ]
    assert resolve_model_selection(intent="cheapest", catalog=two).model_id == "grok-4.3"
    assert resolve_model_selection(intent="economy", catalog=two).model_id == "grok-4.3"
    assert resolve_model_selection(intent="best", catalog=two).model_id == "grok-4.6"

    one = [ModelInfo(id="grok-4.6", capabilities=["chat"], input_per_million=20.0, created=1)]
    assert resolve_model_selection(intent="cheapest", catalog=one).model_id == "grok-4.6"
    assert economy_model(one) == "grok-4.6"
    assert resolve_model_selection(intent="best", catalog=one).model_id == "grok-4.6"


def test_coding_only_catalog_still_resolves() -> None:
    cat = [
        ModelInfo(
            id="grok-build-0.1",
            capabilities=["chat"],
            input_per_million=10.0,
            created=1,
        )
    ]
    assert resolve_model_selection(intent="cheapest", catalog=cat).model_id == "grok-build-0.1"
    assert resolve_model_selection(intent="best", catalog=cat).model_id == "grok-build-0.1"
