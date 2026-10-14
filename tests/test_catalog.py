"""Catalog mapping + resolve helpers (offline)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from xaikit import AsyncXaiClient, MockChatProvider, XaiClient
from xaikit.catalog import (
    BOOTSTRAP_MODEL,
    DEFAULT_IMAGE_MODEL,
    DEFAULT_VIDEO_MODEL,
    DEFAULT_VOICE_MODEL,
    ModelInfo,
    best_model,
    catalog_source,
    cheapest_model,
    clear_catalog_cache,
    contract_model_for_need,
    economy_model,
    fetch_models_from_sdk,
    inject_catalog,
    intent_options,
    list_models,
    load_fixture_catalog,
    model_info_from_image_proto,
    model_info_from_language_proto,
    models_for_role,
    normalize_intent,
    prefer_latest_model,
    prefer_latest_video_model,
    resolve_model,
    resolve_model_selection,
    save_catalog_snapshot,
)
from xaikit.pricing import default_price_table

_WATCH_SLUGS_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "data" / "xai_models_watch.json"
)
_WATCH_VIDEO_IDS = (
    "grok-imagine-video",
    "grok-imagine-video-1.5",
    "grok-imagine-video-1.5-2026-05-30",
    "grok-imagine-video-1.5-lite",
    "grok-imagine-video-1.5-preview",
)


def _lm(**kwargs: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        "name": "grok-4.6",
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
        ModelInfo(id="grok-4.5", capabilities=["chat"], created=1),
        ModelInfo(id=BOOTSTRAP_MODEL, capabilities=["chat"], created=2),
    ]
    sel = resolve_model_selection(intent="nope", catalog=cat)
    assert sel.model_id == prefer_latest_model(cat) == BOOTSTRAP_MODEL


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

    same_band = [
        ModelInfo(id="grok-4.5", capabilities=["chat"], input_per_million=20.0, created=1),
        ModelInfo(id="grok-4.6", capabilities=["chat"], input_per_million=20.0, created=2),
    ]
    assert resolve_model_selection(intent="cheapest", catalog=same_band).model_id == "grok-4.6"
    assert resolve_model_selection(intent="economy", catalog=same_band).model_id == "grok-4.6"
    assert resolve_model_selection(intent="best", catalog=same_band).model_id == "grok-4.6"


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


def _mixed_role_catalog() -> list[ModelInfo]:
    """Chat + image + video + voice rows (unpriced media use public rates)."""
    return [
        *_live_like_catalog(),
        ModelInfo(id="grok-imagine-image", capabilities=["image"], created=1),
        ModelInfo(id="grok-imagine-image-2.0", capabilities=["image"], created=2),
        ModelInfo(id="grok-imagine-image-quality", capabilities=["image"], created=3),
        ModelInfo(id="grok-imagine-video", capabilities=["video"], created=1),
        ModelInfo(id="grok-imagine-video-1.5", capabilities=["video"], created=2),
        ModelInfo(id="grok-voice-think-fast-1.0", capabilities=["voice"], created=1),
        ModelInfo(id="grok-voice-think-fast-2.0", capabilities=["voice"], created=2),
        ModelInfo(id="grok-voice-latest", capabilities=["voice"], created=3),
        ModelInfo(
            id="grok-code-fast-image",
            capabilities=["image"],
            created=0,
            input_per_million=0.001,
        ),
    ]


def test_role_filters_pool() -> None:
    cat = _mixed_role_catalog()
    image_ids = {m.id for m in models_for_role(cat, "image")}
    video_ids = {m.id for m in models_for_role(cat, "video")}
    voice_ids = {m.id for m in models_for_role(cat, "voice")}
    chat_ids = {m.id for m in models_for_role(cat, "chat")}

    assert image_ids == {
        "grok-imagine-image",
        "grok-imagine-image-2.0",
        "grok-imagine-image-quality",
        "grok-code-fast-image",
    }
    assert video_ids == {"grok-imagine-video", "grok-imagine-video-1.5"}
    assert voice_ids == {
        "grok-voice-think-fast-1.0",
        "grok-voice-think-fast-2.0",
        "grok-voice-latest",
    }
    assert "grok-4.6" in chat_ids
    assert "grok-build-0.1" not in chat_ids
    assert image_ids.isdisjoint(chat_ids)
    assert video_ids.isdisjoint(chat_ids)
    assert voice_ids.isdisjoint(chat_ids)

    assert resolve_model_selection(intent="best", role="image", catalog=cat).model_id == (
        "grok-imagine-image-quality"
    )
    assert resolve_model_selection(intent="best", role="video", catalog=cat).model_id == (
        "grok-imagine-video-1.5"
    )
    assert resolve_model_selection(
        intent="best", role="video", need="video_extend", catalog=cat
    ).model_id == "grok-imagine-video"
    assert resolve_model_selection(intent="best", role="voice", catalog=cat).model_id == (
        "grok-voice-latest"
    )
    # chat default unchanged on a mixed catalog
    assert resolve_model_selection(intent="best", catalog=cat).model_id == "grok-4.6"
    assert resolve_model_selection(intent="cheapest", catalog=cat).model_id == (
        "grok-4.20-0309-non-reasoning"
    )


def test_coding_skip_does_not_apply_to_image_video_voice() -> None:
    cat = _mixed_role_catalog()
    # grok-build-0.1 is cheaper than general chat but skipped for chat only
    assert resolve_model_selection(intent="cheapest", catalog=cat).model_id != "grok-build-0.1"
    image_cheap = resolve_model_selection(intent="cheapest", role="image", catalog=cat)
    assert image_cheap.model_id == "grok-code-fast-image"
    assert image_cheap.source == "intent:cheapest"
    video_cheap = resolve_model_selection(intent="cheapest", role="video", catalog=cat)
    assert video_cheap.model_id == "grok-imagine-video"
    voice_cheap = resolve_model_selection(intent="cheapest", role="voice", catalog=cat)
    assert voice_cheap.model_id == "grok-voice-think-fast-1.0"


def _quality_newest_image_catalog() -> list[ModelInfo]:
    return [
        ModelInfo(id="grok-imagine-image", capabilities=["image"], created=1),
        ModelInfo(id="grok-imagine-image-2.0", capabilities=["image"], created=2),
        ModelInfo(id="grok-imagine-image-quality", capabilities=["image"], created=3),
    ]


def _price_table_with_image_2_0(per_call_usd: float):
    table = default_price_table()
    models = dict(table.models)
    models["grok-imagine-image-2.0"] = models["grok-imagine-image-2.0"].model_copy(
        update={"per_call_usd": per_call_usd}
    )
    return table.model_copy(update={"models": models})


def test_unpriced_media_uses_public_rates() -> None:
    cat = _quality_newest_image_catalog()
    assert resolve_model_selection(intent="cheapest", role="image", catalog=cat).model_id == (
        "grok-imagine-image"
    )
    assert resolve_model_selection(intent="economy", role="image", catalog=cat).model_id == (
        "grok-imagine-image"
    )
    assert resolve_model_selection(intent="best", role="image", catalog=cat).model_id == (
        "grok-imagine-image-quality"
    )

    video = [
        ModelInfo(id="grok-imagine-video", capabilities=["video"]),
        ModelInfo(id="grok-imagine-video-1.5", capabilities=["video"]),
    ]
    assert resolve_model_selection(intent="cheapest", role="video", catalog=video).model_id == (
        "grok-imagine-video"
    )
    assert resolve_model_selection(intent="best", role="video", catalog=video).model_id == (
        "grok-imagine-video-1.5"
    )
    assert resolve_model_selection(
        intent="best", role="video", need="video_extend", catalog=video
    ).model_id == "grok-imagine-video"
    assert resolve_model_selection(
        intent="best", role="video", need=["video_edit"], catalog=video
    ).model_id == "grok-imagine-video"
    assert resolve_model_selection(intent="economy", role="video", catalog=video).model_id == (
        "grok-imagine-video"
    )

    voice = [
        ModelInfo(id="grok-voice-think-fast-1.0", capabilities=["voice"]),
        ModelInfo(id="grok-voice-think-fast-2.0", capabilities=["voice"]),
    ]
    assert resolve_model_selection(intent="cheapest", role="voice", catalog=voice).model_id == (
        "grok-voice-think-fast-1.0"
    )
    assert resolve_model_selection(intent="best", role="voice", catalog=voice).model_id == (
        "grok-voice-think-fast-2.0"
    )


def test_stale_image_2_0_rate_makes_economy_pick_2_0(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale = _price_table_with_image_2_0(0.04)
    monkeypatch.setattr("xaikit.pricing.default_price_table", lambda: stale)
    cat = _quality_newest_image_catalog()
    assert (
        economy_model(cat, role="image"),
        cheapest_model(cat, role="image"),
        resolve_model_selection(intent="economy", role="image", catalog=cat).model_id,
        resolve_model_selection(intent="cheapest", role="image", catalog=cat).model_id,
    ) == (
        "grok-imagine-image-2.0",
        "grok-imagine-image",
        "grok-imagine-image-2.0",
        "grok-imagine-image",
    )


def test_image_economy_and_cheapest_resolve_to_grok_imagine_image() -> None:
    cat = _quality_newest_image_catalog()
    assert (
        economy_model(cat, role="image"),
        cheapest_model(cat, role="image"),
        resolve_model_selection(intent="economy", role="image", catalog=cat).model_id,
        resolve_model_selection(intent="cheapest", role="image", catalog=cat).model_id,
    ) == (
        "grok-imagine-image",
        "grok-imagine-image",
        "grok-imagine-image",
        "grok-imagine-image",
    )


def test_image_economy_when_2_0_is_newest_resolves_to_quality() -> None:
    cat = [
        ModelInfo(id="grok-imagine-image", capabilities=["image"], created=1),
        ModelInfo(id="grok-imagine-image-quality", capabilities=["image"], created=2),
        ModelInfo(id="grok-imagine-image-2.0", capabilities=["image"], created=3),
    ]
    assert (
        economy_model(cat, role="image"),
        cheapest_model(cat, role="image"),
        resolve_model_selection(intent="economy", role="image", catalog=cat).model_id,
        resolve_model_selection(intent="cheapest", role="image", catalog=cat).model_id,
    ) == (
        "grok-imagine-image-quality",
        "grok-imagine-image",
        "grok-imagine-image-quality",
        "grok-imagine-image",
    )


def test_thin_image_lineup_intents_overlap() -> None:
    one = [ModelInfo(id="grok-imagine-image-quality", capabilities=["image"], created=1)]
    assert resolve_model_selection(intent="cheapest", role="image", catalog=one).model_id == (
        "grok-imagine-image-quality"
    )
    assert resolve_model_selection(intent="economy", role="image", catalog=one).model_id == (
        "grok-imagine-image-quality"
    )
    assert resolve_model_selection(intent="best", role="image", catalog=one).model_id == (
        "grok-imagine-image-quality"
    )


def test_empty_role_pool_bootstraps_role_default() -> None:
    chat_only = [ModelInfo(id="grok-4.6", capabilities=["chat"], created=1)]
    image = resolve_model_selection(intent="best", role="image", catalog=chat_only)
    assert image.model_id == DEFAULT_IMAGE_MODEL
    assert image.source == "bootstrap"
    video = resolve_model_selection(role="video", catalog=chat_only)
    assert video.model_id == DEFAULT_VIDEO_MODEL
    voice = resolve_model(role="voice", catalog=chat_only)
    assert voice == DEFAULT_VOICE_MODEL


def test_video_lite_is_cheapest_and_not_the_flagship() -> None:
    """1.5 Lite is the $0.02 band. A date in the id must not make it best."""
    video = [
        ModelInfo(id="grok-imagine-video", capabilities=["video"], created=1),
        ModelInfo(id="grok-imagine-video-1.5", capabilities=["video"], created=2),
        ModelInfo(
            id="grok-imagine-video-1.5-lite",
            capabilities=["video"],
            created=99,
        ),
        ModelInfo(
            id="grok-imagine-video-1.5-lite-2026-10-04",
            capabilities=["video"],
            created=100,
        ),
        ModelInfo(
            id="grok-imagine-video-1.5-2026-05-30-lite",
            capabilities=["video"],
            created=101,
        ),
    ]
    assert (
        resolve_model_selection(intent="cheapest", role="video", catalog=video).model_id
        == "grok-imagine-video-1.5-lite"
    )
    assert (
        resolve_model_selection(intent="economy", role="video", catalog=video).model_id
        == "grok-imagine-video"
    )
    assert (
        resolve_model_selection(intent="best", role="video", catalog=video).model_id
        == "grok-imagine-video-1.5"
    )
    assert prefer_latest_video_model(video) == "grok-imagine-video-1.5"
    assert (
        resolve_model(intent="best", role="video", need="video_extend", catalog=video)
        == "grok-imagine-video"
    )
    assert (
        resolve_model(intent="cheapest", role="video", need="r2v", catalog=video)
        == "grok-imagine-video"
    )
    assert (
        resolve_model(intent="best", role="video", need="r2v", catalog=video)
        == "grok-imagine-video-1.5"
    )
    assert (
        resolve_model(intent="cheapest", role="video", need="1080p", catalog=video)
        == "grok-imagine-video-1.5-lite"
    )
    assert (
        resolve_model(intent="best", role="video", need="1080p", catalog=video)
        == "grok-imagine-video-1.5"
    )
    assert (
        contract_model_for_need(
            "grok-imagine-video-1.5-lite", "video_extend", role="video"
        )
        == "grok-imagine-video"
    )


def _watch_video_ids() -> list[str]:
    """Video ids from the committed watch file (the Imagine video block)."""
    payload = json.loads(_WATCH_SLUGS_PATH.read_text(encoding="utf-8"))
    slugs = [str(slug) for slug in payload["slugs"]]
    found = [slug for slug in slugs if slug in _WATCH_VIDEO_IDS]
    assert found == list(_WATCH_VIDEO_IDS)
    return found


def _video_catalog(
    ids: list[str], created_for: Callable[[str], int]
) -> list[ModelInfo]:
    return [
        ModelInfo(id=model_id, capabilities=["video"], created=created_for(model_id))
        for model_id in ids
    ]


def test_xk_ac_rank_2_plain_video_beats_snapshot_and_preview() -> None:
    """XK-AC-RANK-2: plain 1.5 beats the dated snapshot, preview, and lite."""
    ids = _watch_video_ids()
    plain = "grok-imagine-video-1.5"
    snapshot = "grok-imagine-video-1.5-2026-05-30"
    preview = "grok-imagine-video-1.5-preview"
    lite = "grok-imagine-video-1.5-lite"

    def _newer_variant(model_id: str) -> int:
        if model_id in {snapshot, preview, lite}:
            return 500
        return 10

    newer_variants = _video_catalog(ids, _newer_variant)
    assert (
        resolve_model_selection(intent="best", role="video", catalog=newer_variants).model_id
        == plain
    )
    assert prefer_latest_video_model(newer_variants) == plain
    assert resolve_model(intent="best", role="video", catalog=newer_variants) != snapshot
    assert resolve_model(intent="best", role="video", catalog=newer_variants) != preview
    assert resolve_model(intent="best", role="video", catalog=newer_variants) != lite

    tied_created = 42

    def _same_created(_model_id: str) -> int:
        return tied_created

    tied = _video_catalog(ids, _same_created)
    assert {row.created for row in tied} == {tied_created}
    assert (
        resolve_model_selection(intent="best", role="video", catalog=tied).model_id == plain
    )
    assert prefer_latest_video_model(tied) == plain
    assert resolve_model(intent="best", role="video", catalog=tied) not in {snapshot, preview, lite}


def test_xk_ac_rank_3_transcribe_ids_leave_voice() -> None:
    """XK-AC-RANK-3: transcribe ids are speech-to-text, never voice best."""
    rows = [
        model_info_from_language_proto(_lm(name="grok-voice-think-fast-1.0", created=1)),
        model_info_from_language_proto(_lm(name="grok-voice-think-fast-2.0", created=2)),
        model_info_from_language_proto(_lm(name="grok-voice-latest", created=3)),
        model_info_from_language_proto(_lm(name="grok-voice-transcribe-1.0", created=40)),
        model_info_from_language_proto(_lm(name="grok-voice-transcribe-2.0", created=50)),
        model_info_from_language_proto(_lm(name="grok-voice-transcribe-9.0", created=90)),
    ]
    transcribe_ids = {
        "grok-voice-transcribe-1.0",
        "grok-voice-transcribe-2.0",
        "grok-voice-transcribe-9.0",
    }
    voice_best = resolve_model_selection(intent="best", role="voice", catalog=rows)
    assert voice_best.model_id == "grok-voice-latest"
    assert voice_best.source == "intent:best"
    assert not voice_best.model_id.startswith("grok-voice-transcribe")
    assert resolve_model(role="voice", catalog=rows) == "grok-voice-latest"

    voice_ids = {row.id for row in models_for_role(rows, "voice")}
    assert voice_ids.isdisjoint(transcribe_ids)
    speech_ids = {row.id for row in models_for_role(rows, "speech-to-text")}
    assert speech_ids == transcribe_ids
    assert {row.id for row in models_for_role(rows, "chat")}.isdisjoint(transcribe_ids)

    speech_best = resolve_model_selection(intent="best", role="speech-to-text", catalog=rows)
    assert speech_best.model_id == "grok-voice-transcribe-9.0"
    assert speech_best.source == "intent:best"

    for model_id in ("grok-voice-transcribe-1.0", "grok-voice-transcribe-2.0"):
        solo = [
            row
            for row in rows
            if row.id == model_id or not row.id.startswith("grok-voice-transcribe")
        ]
        selected = resolve_model_selection(
            intent="best", role="speech-to-text", catalog=solo
        )
        assert selected.model_id == model_id
        assert selected.source == "intent:best"
        assert (
            resolve_model_selection(intent="best", role="voice", catalog=solo).model_id
            == "grok-voice-latest"
        )

    inject_catalog(rows)
    try:
        client = XaiClient(
            provider=MockChatProvider(),
            api_key="test-key",
            model="grok-4.7",
        )
        assert client.voice_model == "grok-voice-latest"
        assert not client.voice_model.startswith("grok-voice-transcribe")
    finally:
        inject_catalog(None)
        clear_catalog_cache()


def test_xk_ac_rank_3_voice_tagged_transcribe_stays_off_voice() -> None:
    """A newer transcribe row that already carries capability voice is not voice.

    inject_catalog, a fixture, or an older snapshot can store that tag. The
    converter is not what put it there.
    """
    transcribe = ModelInfo(
        id="grok-voice-transcribe-2.0",
        capabilities=["voice"],
        created=90,
    )
    rows = [
        ModelInfo(id="grok-voice-think-fast-1.0", capabilities=["voice"], created=1),
        ModelInfo(id="grok-voice-latest", capabilities=["voice"], created=3),
        transcribe,
    ]
    assert transcribe.created is not None
    assert transcribe.created > 3
    assert "voice" in transcribe.capabilities

    voice_best = resolve_model_selection(intent="best", role="voice", catalog=rows)
    assert voice_best.model_id == "grok-voice-latest"
    assert voice_best.source == "intent:best"
    assert not voice_best.model_id.startswith("grok-voice-transcribe")
    resolved = resolve_model(role="voice", catalog=rows)
    assert resolved == "grok-voice-latest"
    assert not resolved.startswith("grok-voice-transcribe")

    inject_catalog(rows)
    try:
        sync_client = XaiClient(
            provider=MockChatProvider(),
            api_key="test-key",
            model="grok-4.7",
        )
        async_client = AsyncXaiClient(
            provider=MockChatProvider(),
            api_key="test-key",
            model="grok-4.7",
        )
        assert sync_client.voice_model == "grok-voice-latest"
        assert async_client.voice_model == "grok-voice-latest"
        assert not sync_client.voice_model.startswith("grok-voice-transcribe")
        assert not async_client.voice_model.startswith("grok-voice-transcribe")
    finally:
        inject_catalog(None)
        clear_catalog_cache()


def test_xk_ac_rank_4_stable_video_beats_newer_preview() -> None:
    """XK-AC-RANK-4: stable 1.5 beats an in-test newer 2.0-preview.

    The watch file has no grok-imagine-video-2.0-preview row. This test adds
    that row itself. Lite stays out of best.
    """
    ids = _watch_video_ids()
    plain = "grok-imagine-video-1.5"
    preview_20 = "grok-imagine-video-2.0-preview"
    assert preview_20 not in ids
    lite_ids = [model_id for model_id in ids if "lite" in model_id]
    assert lite_ids

    def _created(model_id: str) -> int:
        if model_id == preview_20:
            return 900
        return 10

    catalog = _video_catalog([*ids, preview_20], _created)
    preview_row = next(row for row in catalog if row.id == preview_20)
    assert preview_row.created == 900
    assert all((row.created or 0) < 900 for row in catalog if row.id != preview_20)

    selected = resolve_model_selection(intent="best", role="video", catalog=catalog)
    assert selected.model_id == plain
    assert selected.source == "intent:best"
    assert selected.model_id != preview_20
    assert prefer_latest_video_model(catalog) == plain
    assert best_model(catalog, role="video") == plain
    assert resolve_model(intent="best", role="video", catalog=catalog) == plain
    for lite in lite_ids:
        assert selected.model_id != lite
        assert prefer_latest_video_model(catalog) != lite


def test_xk_ac_rank_4_stable_lite_loses_to_non_lite_preview() -> None:
    """XK-AC-RANK-4: a newer stable lite id stays below every non-lite preview.

    The pool has no stable non-lite id. Lite still loses to the preview.
    """
    older_preview = "grok-imagine-video-1.5-preview"
    preview = "grok-imagine-video-2.0-preview"
    lite = "grok-imagine-video-3.0-lite"
    catalog = [
        ModelInfo(id=older_preview, capabilities=["video"], created=10),
        ModelInfo(id=preview, capabilities=["video"], created=20),
        ModelInfo(id=lite, capabilities=["video"], created=900),
    ]
    assert {row.id for row in catalog} == {older_preview, preview, lite}
    assert all(row.id == lite or row.id.endswith("-preview") for row in catalog)
    lite_row = next(row for row in catalog if row.id == lite)
    assert lite_row.created == 900
    assert all((row.created or 0) < 900 for row in catalog if row.id != lite)

    selected = resolve_model_selection(intent="best", role="video", catalog=catalog)
    assert selected.model_id == preview
    assert selected.source == "intent:best"
    assert selected.model_id != lite
    assert prefer_latest_video_model(catalog) == preview
    assert best_model(catalog, role="video") == preview
    assert resolve_model(intent="best", role="video", catalog=catalog) == preview


def test_xk_ac_rank_5_stable_beats_newer_preview_in_every_role() -> None:
    """XK-AC-RANK-5: a newer preview loses best to the stable model in every role.

    Transcribe stays off voice even when it is stable and newer.
    """
    stable_created = 10
    preview_created = 900
    video_ids = _watch_video_ids()
    preview_20 = "grok-imagine-video-2.0-preview"

    def _video_created(model_id: str) -> int:
        if model_id == preview_20:
            return preview_created
        return stable_created

    catalogs = {
        "chat": [
            ModelInfo(id="grok-4.7", capabilities=["chat"], created=stable_created),
            ModelInfo(
                id="grok-5-preview",
                capabilities=["chat"],
                created=preview_created,
            ),
        ],
        "image": [
            ModelInfo(
                id="grok-imagine-image",
                capabilities=["image"],
                created=stable_created,
            ),
            ModelInfo(
                id="grok-imagine-image-2.0-preview",
                capabilities=["image"],
                created=preview_created,
            ),
        ],
        "video": _video_catalog([*video_ids, preview_20], _video_created),
        "voice": [
            ModelInfo(
                id="grok-voice-think-fast-1.0",
                capabilities=["voice"],
                created=stable_created,
            ),
            ModelInfo(
                id="grok-voice-think-fast-9.0-preview",
                capabilities=["voice"],
                created=preview_created,
            ),
            ModelInfo(
                id="grok-voice-transcribe-9.0",
                capabilities=["speech-to-text", "voice"],
                created=preview_created + 1,
            ),
        ],
        "speech-to-text": [
            ModelInfo(
                id="grok-voice-transcribe-1.0",
                capabilities=["speech-to-text"],
                created=stable_created,
            ),
            ModelInfo(
                id="grok-voice-transcribe-9.0-preview",
                capabilities=["speech-to-text"],
                created=preview_created,
            ),
        ],
    }
    expected = {
        "chat": "grok-4.7",
        "image": "grok-imagine-image",
        "video": "grok-imagine-video-1.5",
        "voice": "grok-voice-think-fast-1.0",
        "speech-to-text": "grok-voice-transcribe-1.0",
    }
    assert set(catalogs) == set(expected)
    for role, want in expected.items():
        catalog = catalogs[role]
        selected = resolve_model_selection(intent="best", role=role, catalog=catalog)
        assert selected.model_id == want
        assert selected.source == "intent:best"
        assert best_model(catalog, role=role) == want
        assert prefer_latest_model(catalog, role=role) == want
        assert resolve_model(intent="best", role=role, catalog=catalog) == want

    voice_rows = catalogs["voice"]
    voice_ids = {row.id for row in models_for_role(voice_rows, "voice")}
    assert "grok-voice-transcribe-9.0" not in voice_ids
    assert all(not model_id.startswith("grok-voice-transcribe") for model_id in voice_ids)
    speech_ids = {row.id for row in models_for_role(voice_rows, "speech-to-text")}
    assert speech_ids == {"grok-voice-transcribe-9.0"}

    segment = [
        ModelInfo(id="grok-4.7", capabilities=["chat"], created=stable_created),
        ModelInfo(id="grok-5-previewing", capabilities=["chat"], created=preview_created),
    ]
    assert (
        resolve_model_selection(intent="best", role="chat", catalog=segment).model_id
        == "grok-5-previewing"
    )


def test_xk_ac_rank_6_preview_only_pool_resolves_to_preview() -> None:
    """XK-AC-RANK-6: a preview-only pool resolves to a preview, not a default."""
    video = [
        ModelInfo(
            id="grok-imagine-video-1.5-preview",
            capabilities=["video"],
            created=20,
        ),
        ModelInfo(
            id="grok-imagine-video-2.0-preview",
            capabilities=["video"],
            created=5,
        ),
    ]
    image = [
        ModelInfo(id="grok-imagine-image-preview", capabilities=["image"], created=10),
        ModelInfo(
            id="grok-imagine-image-2.0-preview",
            capabilities=["image"],
            created=50,
        ),
    ]
    chat = [
        ModelInfo(id="grok-4.7-preview", capabilities=["chat"], created=20),
        ModelInfo(id="grok-5-preview", capabilities=["chat"], created=5),
    ]
    cases = (
        ("video", video, "grok-imagine-video-2.0-preview", DEFAULT_VIDEO_MODEL),
        ("image", image, "grok-imagine-image-2.0-preview", DEFAULT_IMAGE_MODEL),
        ("chat", chat, "grok-5-preview", BOOTSTRAP_MODEL),
    )
    for role, catalog, want, fallback in cases:
        assert want != fallback
        selected = resolve_model_selection(intent="best", role=role, catalog=catalog)
        assert selected.model_id == want
        assert selected.source == "intent:best"
        assert selected.model_id is not None
        assert best_model(catalog, role=role) == want
        assert prefer_latest_model(catalog, role=role) == want
        assert resolve_model(intent="best", role=role, catalog=catalog) == want
    assert prefer_latest_video_model(video) == "grok-imagine-video-2.0-preview"


def test_need_filters_best_for_the_job() -> None:
    video = [
        ModelInfo(id="grok-imagine-video", capabilities=["video"], created=1),
        ModelInfo(id="grok-imagine-video-1.5", capabilities=["video"], created=2),
    ]
    only_15 = [ModelInfo(id="grok-imagine-video-1.5", capabilities=["video"], created=2)]
    chat = [
        ModelInfo(id="grok-4.5", capabilities=["chat"], created=1),
        ModelInfo(id="grok-4.6", capabilities=["chat"], created=2),
    ]

    assert resolve_model(
        intent="best", role="video", need="video_extend", catalog=video
    ) == "grok-imagine-video"
    empty = resolve_model_selection(
        intent="best", role="video", need="video_extend", catalog=only_15
    )
    assert empty.model_id == "grok-imagine-video"
    assert empty.source == "bootstrap"
    pin = resolve_model_selection(
        pin="grok-imagine-video-1.5",
        intent="best",
        role="video",
        need="video_extend",
        catalog=video,
    )
    assert pin.model_id == "grok-imagine-video-1.5"
    assert pin.source == "pin"
    assert resolve_model(intent="best", need="web_search", catalog=chat) == "grok-4.6"

    assert (
        contract_model_for_need("grok-imagine-video-1.5", "video_extend", role="video")
        == "grok-imagine-video"
    )
    assert (
        contract_model_for_need("grok-imagine-video", "video_extend", role="video")
        == "grok-imagine-video"
    )
    assert (
        contract_model_for_need("future-extend-sku", "video_extend", role="video")
        == "future-extend-sku"
    )
    assert (
        contract_model_for_need("grok-4.6", "batch", role="chat", catalog=chat)
        == "grok-4.3"
    )
    assert (
        contract_model_for_need("grok-4.7", "batch", role="chat", catalog=chat)
        == "grok-4.3"
    )
    assert (
        contract_model_for_need("grok-4.5", "batch", role="chat", catalog=chat)
        == "grok-4.3"
    )
    assert (
        contract_model_for_need("grok-4.3", "batch", role="chat", catalog=chat)
        == "grok-4.3"
    )
    assert resolve_model(intent="best", need="batch", catalog=chat) == "grok-4.3"


def test_language_proto_video_slug_is_not_chat() -> None:
    info = model_info_from_language_proto(_lm(name="grok-imagine-video-1.5", aliases=[]))
    assert "video" in info.capabilities
    assert "chat" not in info.capabilities
    assert not info.is_chat


def test_image_proto_maps_price_and_capability() -> None:
    info = model_info_from_image_proto(
        SimpleNamespace(
            name="grok-imagine-image-quality",
            aliases=["grok-imagine-image-pro"],
            version="1",
            image_price=50,
            created=None,
            max_prompt_length=0,
        )
    )
    assert info.id == "grok-imagine-image-quality"
    assert info.capabilities == ["image"]
    assert info.input_per_million is None
    assert info.per_image_usd == 50.0
    assert info.aliases == ["grok-imagine-image-pro"]


def test_image_proto_video_slug_tagged_video() -> None:
    info = model_info_from_image_proto(
        SimpleNamespace(
            name="grok-imagine-video-1.5",
            aliases=[],
            version=None,
            image_price=None,
            created=None,
            max_prompt_length=None,
        )
    )
    assert info.capabilities == ["video"]
    assert info.input_per_million is None


def _fake_sdk_client(
    *,
    language: list[object] | BaseException,
    images: list[object] | BaseException,
):
    class FakeModels:
        def list_language_models(self) -> list[object]:
            if isinstance(language, BaseException):
                raise language
            return language

        def list_image_generation_models(self) -> list[object]:
            if isinstance(images, BaseException):
                raise images
            return images

    class FakeClient:
        def __init__(self, api_key: str, timeout: float | None = None, **kwargs: object) -> None:
            assert api_key == "test-key"
            del timeout, kwargs
            self.models = FakeModels()

        def close(self) -> None:
            pass

    return FakeClient


def test_fetch_includes_image_models(monkeypatch: pytest.MonkeyPatch) -> None:
    import xai_sdk

    monkeypatch.setattr(
        xai_sdk,
        "Client",
        _fake_sdk_client(
            language=[_lm(name="grok-4.6")],
            images=[
                SimpleNamespace(
                    name="grok-imagine-image-quality",
                    aliases=[],
                    version=None,
                    image_price=50,
                    created=None,
                    max_prompt_length=None,
                )
            ],
        ),
    )
    models = fetch_models_from_sdk("test-key")
    by_id = {m.id: m for m in models}
    assert "grok-4.6" in by_id
    assert "grok-imagine-image-quality" in by_id
    assert "image" in by_id["grok-imagine-image-quality"].capabilities
    assert "chat" in by_id["grok-4.6"].capabilities


def test_fetch_image_list_failure_keeps_language_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import xai_sdk

    monkeypatch.setattr(
        xai_sdk,
        "Client",
        _fake_sdk_client(
            language=[_lm(name="grok-4.6")],
            images=RuntimeError("image list down"),
        ),
    )
    models = fetch_models_from_sdk("test-key")
    assert [m.id for m in models] == ["grok-4.6"]


def test_fetch_language_list_failure_keeps_image_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import xai_sdk

    monkeypatch.setattr(
        xai_sdk,
        "Client",
        _fake_sdk_client(
            language=RuntimeError("language list down"),
            images=[
                SimpleNamespace(
                    name="grok-imagine-image",
                    aliases=[],
                    version=None,
                    image_price=None,
                    created=None,
                    max_prompt_length=None,
                )
            ],
        ),
    )
    models = fetch_models_from_sdk("test-key")
    assert [m.id for m in models] == ["grok-imagine-image"]
    assert models[0].capabilities == ["image"]


def test_fetch_all_lists_fail_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    import xai_sdk

    monkeypatch.setattr(
        xai_sdk,
        "Client",
        _fake_sdk_client(
            language=RuntimeError("language list down"),
            images=RuntimeError("image list down"),
        ),
    )
    with pytest.raises(RuntimeError, match="list down"):
        fetch_models_from_sdk("test-key")


def test_list_models_sdk_total_failure_falls_back_to_fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import xai_sdk

    clear_catalog_cache()
    monkeypatch.setattr(
        xai_sdk,
        "Client",
        _fake_sdk_client(
            language=RuntimeError("language list down"),
            images=RuntimeError("image list down"),
        ),
    )
    fixture = tmp_path / "cat.json"
    fixture.write_text(
        '[{"id": "from-fixture", "capabilities": ["chat"]}]',
        encoding="utf-8",
    )
    models = list_models(
        api_key="test-key",
        fixture_path=fixture,
        force_refresh=True,
    )
    assert [m.id for m in models] == ["from-fixture"]
    clear_catalog_cache()


def test_image_role_ranks_on_public_per_call_not_sdk_token_units() -> None:
    cat = [
        ModelInfo(
            id="grok-imagine-image-quality",
            capabilities=["image"],
            input_per_million=0.001,
        ),
        ModelInfo(id="grok-imagine-image", capabilities=["image"]),
    ]
    cheap = resolve_model_selection(intent="cheapest", role="image", catalog=cat)
    assert cheap.model_id == "grok-imagine-image"


def test_bootstrap_model_is_current_flagship() -> None:
    assert BOOTSTRAP_MODEL == "grok-4.7"


def test_language_proto_token_price_uses_docs_scale() -> None:
    info = model_info_from_language_proto(
        _lm(
            name="grok-4.7",
            prompt_text_token_price=20000,
            completion_text_token_price=60000,
            cached_prompt_token_price=5000,
            prompt_image_token_price=20000,
            prompt_text_token_price_long_context=40000,
            completion_token_price_long_context=120000,
        )
    )
    assert info.input_per_million == 2.0
    assert info.output_per_million == 6.0
    assert info.cached_input_per_million == 0.5
    assert info.image_token_per_million == 2.0
    assert info.input_long_per_million == 4.0
    assert info.output_long_per_million == 12.0


def test_image_proto_media_scale_is_per_image() -> None:
    info = model_info_from_image_proto(
        SimpleNamespace(
            name="grok-imagine-image-quality",
            aliases=[],
            version=None,
            image_price=500_000_000,
            created=None,
            max_prompt_length=None,
        )
    )
    assert info.input_per_million is None
    assert info.per_image_usd == 0.05


def test_chat_version_sort_ranks_double_digit_minor_and_major_5() -> None:
    ids = [
        "grok-4.20-0309-reasoning",
        "grok-4.3",
        "grok-4.5",
        "grok-4.6",
        "grok-4.7",
        "grok-4.8",
        "grok-4.9",
        "grok-4.10",
        "grok-5",
        "grok-4.20-multi-agent-0309",
    ]
    cat = [ModelInfo(id=mid, capabilities=["chat"]) for mid in ids]
    assert prefer_latest_model(cat) == "grok-5"
    order = []
    remaining = list(cat)
    while remaining:
        newest = prefer_latest_model(remaining)
        assert newest
        order.append(newest)
        remaining = [row for row in remaining if row.id != newest]
    assert order == [
        "grok-5",
        "grok-4.10",
        "grok-4.9",
        "grok-4.8",
        "grok-4.7",
        "grok-4.6",
        "grok-4.5",
        "grok-4.3",
        "grok-4.20-multi-agent-0309",
        "grok-4.20-0309-reasoning",
    ]


def test_sdk_failure_with_key_bootstraps_and_does_not_retry_within_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import xai_sdk

    calls = {"n": 0}

    class _Counting:
        def __init__(self, api_key: str, timeout: float | None = None, **kwargs: object) -> None:
            del timeout, kwargs
            calls["n"] += 1
            self.models = self

        def list_language_models(self) -> list[object]:
            raise RuntimeError("language list down")

        def list_image_generation_models(self) -> list[object]:
            raise RuntimeError("image list down")

        def close(self) -> None:
            pass

    inject_catalog(None)
    clear_catalog_cache()
    monkeypatch.setattr(xai_sdk, "Client", _Counting)
    first = list_models(api_key="test-key", force_refresh=True)
    assert [m.id for m in first] == [BOOTSTRAP_MODEL, "grok-4.3"]
    assert catalog_source() == "sdk-error"
    second = list_models(api_key="test-key")
    assert [m.id for m in second] == [BOOTSTRAP_MODEL, "grok-4.3"]
    assert calls["n"] == 1
    clear_catalog_cache()


def test_list_models_offline_bootstrap_has_two_current_chat_bands() -> None:
    inject_catalog(None)
    clear_catalog_cache()
    models = list_models(force_refresh=True, allow_fixture_fallback=True)
    ids = [m.id for m in models]
    assert ids == [BOOTSTRAP_MODEL, "grok-4.3"]
    by_id = {m.id: m for m in models}
    assert by_id[BOOTSTRAP_MODEL].input_per_million == 2.0
    assert by_id[BOOTSTRAP_MODEL].output_per_million == 6.0
    assert by_id["grok-4.3"].input_per_million == 1.25
    assert by_id["grok-4.3"].output_per_million == 2.5
    assert resolve_model_selection(intent="cheapest", catalog=models).model_id == "grok-4.3"
    assert resolve_model_selection(intent="economy", catalog=models).model_id == "grok-4.3"
    assert resolve_model_selection(intent="best", catalog=models).model_id == BOOTSTRAP_MODEL
    clear_catalog_cache()


def test_default_price_table_current_chat_rates() -> None:
    from xaikit.pricing import default_price_table

    table = default_price_table()
    flagship = table.price_for("grok-4.7")
    assert flagship.input_per_million == 2.0
    assert flagship.output_per_million == 6.0
    # Exact row, not the grok-4 prefix ($3 / $15).
    assert table.price_for("grok-4").input_per_million == 3.0
    previous = table.price_for("grok-4.6")
    assert previous.input_per_million == 2.0
    assert previous.output_per_million == 6.0
    mid = table.price_for("grok-4.5")
    assert mid.input_per_million == 2.0
    assert mid.output_per_million == 6.0
    cheap = table.price_for("grok-4.3")
    assert cheap.input_per_million == 1.25
    assert cheap.output_per_million == 2.5
    # Retired slugs stay for old event estimates
    mini = table.price_for("grok-3-mini")
    assert mini.input_per_million == 0.3
    assert mini.output_per_million == 0.5


def test_save_catalog_snapshot_roundtrip(tmp_path) -> None:
    path = tmp_path / "nested" / "cat.json"
    models = [
        ModelInfo(id="grok-4.6", capabilities=["chat"], input_per_million=2.0),
        ModelInfo(id="grok-4.3", capabilities=["chat"], input_per_million=1.25),
    ]
    out = save_catalog_snapshot(path, models)
    assert out == path
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert "models" in payload
    loaded = load_fixture_catalog(path)
    assert [m.id for m in loaded] == ["grok-4.6", "grok-4.3"]
    assert loaded[0].input_per_million == 2.0
    empty = tmp_path / "empty.json"
    save_catalog_snapshot(empty, [])
    assert json.loads(empty.read_text(encoding="utf-8")) == {"models": []}
    assert load_fixture_catalog(empty) == []


def test_save_catalog_snapshot_failed_write_keeps_existing(tmp_path, monkeypatch) -> None:
    path = tmp_path / "cat.json"
    save_catalog_snapshot(path, [ModelInfo(id="keep-me", capabilities=["chat"])])
    original = path.read_text(encoding="utf-8")

    def _boom(self, *_a, **_k):  # noqa: ANN001
        raise OSError("disk full")

    monkeypatch.setattr("pathlib.Path.write_text", _boom)
    with pytest.raises(RuntimeError, match="Cannot write catalog snapshot"):
        save_catalog_snapshot(path, [ModelInfo(id="new", capabilities=["chat"])])
    assert path.read_text(encoding="utf-8") == original
    assert load_fixture_catalog(path)[0].id == "keep-me"


def test_list_models_sdk_success_writes_persist(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import xai_sdk

    inject_catalog(None)
    clear_catalog_cache()
    persist = tmp_path / "snap" / "catalog.json"
    monkeypatch.setattr(
        xai_sdk,
        "Client",
        _fake_sdk_client(
            language=[_lm(name="from-sdk")],
            images=[],
        ),
    )
    models = list_models(
        api_key="test-key",
        persist_path=persist,
        force_refresh=True,
        allow_fixture_fallback=False,
    )
    assert [m.id for m in models] == ["from-sdk"]
    assert persist.is_file()
    assert [m.id for m in load_fixture_catalog(persist)] == ["from-sdk"]
    assert catalog_source() == "sdk"
    clear_catalog_cache()
    offline = list_models(persist_path=persist, force_refresh=True)
    assert [m.id for m in offline] == ["from-sdk"]
    assert catalog_source() == "persist"
    clear_catalog_cache()


def test_list_models_persist_beats_bootstrap_when_no_key(tmp_path) -> None:
    inject_catalog(None)
    clear_catalog_cache()
    persist = tmp_path / "catalog.json"
    save_catalog_snapshot(
        persist,
        [ModelInfo(id="from-persist", capabilities=["chat"])],
    )
    models = list_models(persist_path=persist, force_refresh=True)
    assert [m.id for m in models] == ["from-persist"]
    assert catalog_source() == "persist"
    # cache drop does not delete the file
    clear_catalog_cache()
    assert persist.is_file()
    again = list_models(persist_path=persist, force_refresh=True)
    assert [m.id for m in again] == ["from-persist"]
    clear_catalog_cache()


def test_list_models_memory_cache_wins_over_persist(tmp_path) -> None:
    inject_catalog(None)
    clear_catalog_cache()
    persist = tmp_path / "catalog.json"
    save_catalog_snapshot(
        persist,
        [ModelInfo(id="cached-row", capabilities=["chat"])],
    )
    first = list_models(persist_path=persist, force_refresh=True)
    assert [m.id for m in first] == ["cached-row"]
    save_catalog_snapshot(
        persist,
        [ModelInfo(id="newer-on-disk", capabilities=["chat"])],
    )
    second = list_models(persist_path=persist)
    assert [m.id for m in second] == ["cached-row"]
    clear_catalog_cache()
    third = list_models(persist_path=persist, force_refresh=True)
    assert [m.id for m in third] == ["newer-on-disk"]
    clear_catalog_cache()


def test_list_models_persist_write_failure_still_returns(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import xai_sdk

    inject_catalog(None)
    clear_catalog_cache()
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    persist = blocker / "catalog.json"
    monkeypatch.setattr(
        xai_sdk,
        "Client",
        _fake_sdk_client(
            language=[_lm(name="live-ok")],
            images=[],
        ),
    )
    models = list_models(
        api_key="test-key",
        persist_path=persist,
        force_refresh=True,
        allow_fixture_fallback=False,
    )
    assert [m.id for m in models] == ["live-ok"]
    assert catalog_source() == "sdk"
    clear_catalog_cache()
