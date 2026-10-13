"""CAT-AC-LITE-ALL and CAT-AC-EXTRAS-1 (offline).

Lite ranks last for best in every role. Quality video extras stay on the
unversioned Imagine id. Watch-id feature_options stay on the 8ef89b3 baseline
(62 slugs).
"""

from __future__ import annotations

import json
from pathlib import Path

from xaikit import AsyncXaiClient, MockChatProvider, XaiClient
from xaikit.catalog import (
    BOOTSTRAP_MODEL,
    DEFAULT_IMAGE_MODEL,
    DEFAULT_VIDEO_MODEL,
    DEFAULT_VOICE_MODEL,
    ModelInfo,
    best_model,
    cheapest_model,
    clear_catalog_cache,
    contract_model_for_need,
    economy_model,
    feature_options,
    inject_catalog,
    prefer_latest_model,
    resolve_model,
    resolve_model_selection,
)
from xaikit.pricing import default_price_table

_WATCH_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "data" / "xai_models_watch.json"
)
_CATALOG_DOC = Path(__file__).resolve().parents[1] / "docs" / "features" / "Catalog.md"
_STT_DEFAULT = "grok-voice-transcribe-2.0"
_QUALITY = ["video_extend", "video_edit", "r2v"]
_CHAT_EXTRAS = [
    "web_search",
    "x_search",
    "code_execution",
    "file_attachments",
    "collections_search",
    "image_understanding",
    "x_video_understanding",
    "mcp",
]
_WATCH_CHAT_46 = frozenset({"grok-4-6", "grok-4-7", "grok-4.6", "grok-4.7"})
_WATCH_BATCH = frozenset({"grok-4.3", "grok-4.3-latest"})
_WATCH_QUALITY = frozenset({"grok-imagine-video"})
_WATCH_15 = frozenset(
    {
        "grok-imagine-video-1.5",
        "grok-imagine-video-1.5-2026-05-30",
        "grok-imagine-video-1.5-preview",
    }
)
_WATCH_15_LITE = frozenset({"grok-imagine-video-1.5-lite"})
_ROLE_CAPS = {
    "chat": ["chat"],
    "image": ["image"],
    "video": ["video"],
    "voice": ["voice"],
    "speech-to-text": ["speech-to-text"],
}


def _row(model_id: str, role: str, created: int, **kwargs: object) -> ModelInfo:
    return ModelInfo(
        id=model_id,
        capabilities=list(_ROLE_CAPS[role]),
        created=created,
        **kwargs,
    )


def _assert_best(catalog: list[ModelInfo], role: str, want: str) -> None:
    assert best_model(catalog, role=role) == want
    assert prefer_latest_model(catalog, role=role) == want
    assert resolve_model(intent="best", role=role, catalog=catalog) == want
    selected = resolve_model_selection(intent="best", role=role, catalog=catalog)
    assert selected.model_id == want
    assert selected.source == "intent:best"


def _watch_slugs() -> list[str]:
    payload = json.loads(_WATCH_PATH.read_text(encoding="utf-8"))
    slugs = [str(slug) for slug in payload["slugs"]]
    assert len(slugs) == 62
    assert len(set(slugs)) == 62
    return slugs


def _expected_watch_options(slug: str) -> list[str]:
    """8ef89b3 feature_options for one watch slug. Not derived from the function."""
    if slug in _WATCH_CHAT_46:
        return list(_CHAT_EXTRAS)
    if slug in _WATCH_BATCH:
        return ["batch"]
    if slug in _WATCH_QUALITY:
        return list(_QUALITY)
    if slug in _WATCH_15_LITE:
        return ["1080p"]
    if slug in _WATCH_15:
        return ["1080p", "r2v"]
    return []


def test_l1_chat_newer_or_higher_lite_loses_best() -> None:
    """CAT-AC-LITE-ALL L-1. Kills a chat key that omits lite or ranks it late."""
    minor = [
        _row("grok-4.7", "chat", 100),
        _row("grok-4.8-lite", "chat", 200),
    ]
    _assert_best(minor, "chat", "grok-4.7")

    major = [
        _row("grok-4.7", "chat", 100),
        _row("grok-5-lite", "chat", 900),
    ]
    _assert_best(major, "chat", "grok-4.7")
    assert resolve_model(intent="best", role="chat", catalog=major) != "grok-5-lite"


def test_l2_image_newer_lite_loses_best() -> None:
    """CAT-AC-LITE-ALL L-2. Kills a generic key that omits lite or ranks it after created."""
    catalog = [
        _row("grok-imagine-image", "image", 100),
        _row("grok-imagine-image-3.0-lite", "image", 900),
    ]
    _assert_best(catalog, "image", "grok-imagine-image")


def test_l3_video_newer_lite_loses_best() -> None:
    """CAT-AC-LITE-ALL L-3. Control: video already ranked lite last."""
    catalog = [
        _row("grok-imagine-video-1.5", "video", 100),
        _row("grok-imagine-video-3.0-lite", "video", 900),
    ]
    _assert_best(catalog, "video", "grok-imagine-video-1.5")


def test_l4_voice_newer_lite_loses_best_and_unpinned_client() -> None:
    """CAT-AC-LITE-ALL L-4. Sync and async unpinned voice_model stay off lite."""
    stable = "grok-voice-think-fast-2.0"
    lite = "grok-voice-think-fast-3.0-lite"
    catalog = [
        _row(stable, "voice", 100),
        _row(lite, "voice", 900),
        _row("grok-4.7", "chat", 1),
    ]
    _assert_best(catalog, "voice", stable)

    inject_catalog(catalog)
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
        assert sync_client.voice_model == stable
        assert async_client.voice_model == stable
        assert sync_client.voice_model != lite
        assert async_client.voice_model != lite
        assert sync_client.voice_model != DEFAULT_VOICE_MODEL
    finally:
        inject_catalog(None)
        clear_catalog_cache()


def test_l5_stt_newer_lite_loses_best() -> None:
    """CAT-AC-LITE-ALL L-5."""
    catalog = [
        _row("grok-voice-transcribe-2.0", "speech-to-text", 100),
        _row("grok-voice-transcribe-3.0-lite", "speech-to-text", 900),
    ]
    _assert_best(catalog, "speech-to-text", "grok-voice-transcribe-2.0")


def test_l6_lite_alone_is_newest_lite_not_the_role_default() -> None:
    """CAT-AC-LITE-ALL L-6. Alone means the pool after need filtering.

    Kills a lite-only pool that returns None or the role default.
    """
    cases = [
        (
            "chat",
            [
                _row("grok-4.8-lite", "chat", 900),
                _row("grok-5-lite", "chat", 100),
            ],
            "grok-5-lite",
            BOOTSTRAP_MODEL,
        ),
        (
            "image",
            [
                _row("grok-imagine-image-lite", "image", 10),
                _row("grok-imagine-image-3.0-lite", "image", 50),
            ],
            "grok-imagine-image-3.0-lite",
            DEFAULT_IMAGE_MODEL,
        ),
        (
            "video",
            [
                _row("grok-imagine-video-1.5-lite", "video", 900),
                _row("grok-imagine-video-3.0-lite", "video", 10),
            ],
            "grok-imagine-video-3.0-lite",
            DEFAULT_VIDEO_MODEL,
        ),
        (
            "voice",
            [
                _row("grok-voice-lite-1.0", "voice", 10),
                _row("grok-voice-think-fast-3.0-lite", "voice", 50),
            ],
            "grok-voice-think-fast-3.0-lite",
            DEFAULT_VOICE_MODEL,
        ),
        (
            "speech-to-text",
            [
                _row("grok-voice-transcribe-1.0-lite", "speech-to-text", 10),
                _row("grok-voice-transcribe-3.0-lite", "speech-to-text", 50),
            ],
            "grok-voice-transcribe-3.0-lite",
            _STT_DEFAULT,
        ),
    ]
    for role, catalog, want, role_default in cases:
        assert want != role_default
        assert best_model(catalog, role=role) == want
        assert prefer_latest_model(catalog, role=role) == want
        assert resolve_model(intent="best", role=role, catalog=catalog) == want
        selected = resolve_model_selection(intent="best", role=role, catalog=catalog)
        assert selected.model_id == want
        assert selected.model_id != role_default
        assert selected.source == "intent:best"

    filtered = [
        _row("grok-4.5", "chat", 900),
        _row("grok-4.8-lite", "chat", 100),
        _row("grok-5-lite", "chat", 200),
    ]
    assert feature_options("grok-4.5") == []
    assert "web_search" in feature_options("grok-5-lite")
    selected = resolve_model_selection(
        intent="best",
        role="chat",
        need="web_search",
        catalog=filtered,
    )
    assert selected.model_id == "grok-5-lite"
    assert selected.model_id != BOOTSTRAP_MODEL
    assert selected.source == "intent:best"


def test_l7_video_preview_beats_stable_lite() -> None:
    """CAT-AC-LITE-ALL L-7 video control. Matches XK-AC-RANK-4."""
    catalog = [
        _row("grok-imagine-video-2.0-preview", "video", 10),
        _row("grok-imagine-video-3.0-lite", "video", 900),
    ]
    _assert_best(catalog, "video", "grok-imagine-video-2.0-preview")


def test_l7_nonvideo_preview_beats_stable_lite() -> None:
    """CAT-AC-LITE-ALL L-7. Lite ranks before stable, so preview beats stable lite."""
    cases = {
        "chat": (
            "grok-2.0-preview",
            "grok-3.0-lite",
        ),
        "image": (
            "grok-imagine-image-2.0-preview",
            "grok-imagine-image-3.0-lite",
        ),
        "voice": (
            "grok-voice-think-fast-2.0-preview",
            "grok-voice-think-fast-3.0-lite",
        ),
        "speech-to-text": (
            "grok-voice-transcribe-2.0-preview",
            "grok-voice-transcribe-3.0-lite",
        ),
    }
    for role, (preview, lite) in cases.items():
        catalog = [_row(preview, role, 10), _row(lite, role, 900)]
        _assert_best(catalog, role, preview)


def test_l8_lite_wins_economy_and_cheapest_below_flagship() -> None:
    """CAT-AC-LITE-ALL L-8. Best stays non-lite. Economy and cheapest can be lite.

    Kills a lite rule that also drops lite from economy.
    """
    table = default_price_table()
    assert table.price_for("grok-imagine-image-quality").per_call_usd == 0.05
    assert table.price_for("grok-imagine-image-3.0-lite").per_call_usd == 0.02
    assert table.price_for("grok-imagine-video-1.5").per_second_usd == 0.08
    assert table.price_for("grok-imagine-video-1.5-lite").per_second_usd == 0.02
    assert table.price_for("grok-voice-think-fast-2.0").per_minute_usd == 0.08
    assert table.price_for("grok-voice-think-fast-3.0-lite") is None

    image = [
        _row("grok-imagine-image-quality", "image", 10),
        _row("grok-imagine-image-3.0-lite", "image", 900),
    ]
    chat = [
        _row("grok-4.7", "chat", 10, input_per_million=5.0),
        _row("grok-4.8-lite", "chat", 900, input_per_million=1.0),
    ]
    video = [
        _row("grok-imagine-video-1.5", "video", 10),
        _row("grok-imagine-video-1.5-lite", "video", 900),
    ]
    voice = [
        _row("grok-voice-think-fast-2.0", "voice", 10),
        _row("grok-voice-think-fast-3.0-lite", "voice", 900, input_per_million=0.01),
    ]
    stt = [
        _row("grok-voice-transcribe-2.0", "speech-to-text", 10, input_per_million=5.0),
        _row(
            "grok-voice-transcribe-3.0-lite",
            "speech-to-text",
            900,
            input_per_million=1.0,
        ),
    ]
    expected = {
        "image": (image, "grok-imagine-image-quality", "grok-imagine-image-3.0-lite"),
        "chat": (chat, "grok-4.7", "grok-4.8-lite"),
        "video": (video, "grok-imagine-video-1.5", "grok-imagine-video-1.5-lite"),
        "voice": (voice, "grok-voice-think-fast-2.0", "grok-voice-think-fast-3.0-lite"),
        "speech-to-text": (
            stt,
            "grok-voice-transcribe-2.0",
            "grok-voice-transcribe-3.0-lite",
        ),
    }
    for role, (catalog, flagship, lite) in expected.items():
        _assert_best(catalog, role, flagship)
        assert economy_model(catalog, role=role) == lite
        assert cheapest_model(catalog, role=role) == lite
        assert resolve_model(intent="economy", role=role, catalog=catalog) == lite
        assert resolve_model(intent="cheapest", role=role, catalog=catalog) == lite


def test_l9_lite_segment_does_not_match_latest_elite_or_lites() -> None:
    """CAT-AC-LITE-ALL L-9. Kills a substring search for lite."""
    latest = [
        _row("grok-4.7-latest", "chat", 100),
        _row("grok-4.8-lite", "chat", 900),
    ]
    _assert_best(latest, "chat", "grok-4.7-latest")

    elite = [
        _row("grok-elite", "chat", 100),
        _row("grok-4.8-lite", "chat", 900),
    ]
    _assert_best(elite, "chat", "grok-elite")

    lites = [
        _row("grok-4-lites", "chat", 100),
        _row("grok-4.8-lite", "chat", 900),
    ]
    _assert_best(lites, "chat", "grok-4-lites")

    image = [
        _row("grok-imagine-image-elite", "image", 10),
        _row("grok-imagine-image-3.0-lite", "image", 900),
    ]
    _assert_best(image, "image", "grok-imagine-image-elite")


def test_l10_catalog_documents_lite_rule_for_every_role() -> None:
    """CAT-AC-LITE-ALL L-10."""
    text = _CATALOG_DOC.read_text(encoding="utf-8")
    assert "CAT-AC-LITE-ALL" in text
    assert "every role" in text
    assert "`-lite` segment" in text
    assert "2026-10-13" in text
    assert "`latest`, `elite`, and `lites` are not lite" in text


def test_e1_unversioned_quality_extras_unchanged() -> None:
    """CAT-AC-EXTRAS-1 E-1."""
    assert feature_options("grok-imagine-video") == _QUALITY


def test_e2_versioned_unknown_ids_have_empty_extras() -> None:
    """CAT-AC-EXTRAS-1 E-2.

    Kills prefix extras, extras for any non-lite version, and extras that
    exclude only preview or only lite.
    """
    assert feature_options("grok-imagine-video-2.0-preview") == []
    assert feature_options("grok-imagine-video-3.0-lite") == []
    assert feature_options("grok-imagine-video-2.0") == []
    assert feature_options("grok-imagine-video-1.5-preview") == ["1080p", "r2v"]
    assert feature_options("grok-imagine-video-1.5-lite") == ["1080p"]


def test_e3_watch_slug_feature_options_match_8ef89b3() -> None:
    """CAT-AC-EXTRAS-1 E-3. 62 watch slugs, including the 1.5 family."""
    slugs = _watch_slugs()
    assert "grok-imagine-video-1.5" in slugs
    assert "grok-imagine-video-1.5-lite" in slugs
    assert "grok-imagine-video-1.5-preview" in slugs
    assert "grok-imagine-video-1.5-2026-05-30" in slugs
    for slug in slugs:
        assert feature_options(slug) == _expected_watch_options(slug), slug


def test_e4_need_falls_back_instead_of_unknown_versioned_ids() -> None:
    """CAT-AC-EXTRAS-1 E-4. Kills a need filter that ignores feature_options."""
    preview = "grok-imagine-video-2.0-preview"
    lite = "grok-imagine-video-3.0-lite"
    one_five = "grok-imagine-video-1.5"
    extend_pools = [
        [_row(one_five, "video", 10), _row(preview, "video", 900)],
        [_row(one_five, "video", 10), _row(lite, "video", 900)],
        [_row(preview, "video", 100), _row(lite, "video", 900)],
    ]
    for need in ("video_extend", "video_edit"):
        for catalog in extend_pools:
            selected = resolve_model_selection(
                intent="best", role="video", need=need, catalog=catalog
            )
            assert selected.model_id == "grok-imagine-video"
            assert selected.source == "bootstrap"
            assert resolve_model(
                intent="best", role="video", need=need, catalog=catalog
            ) == "grok-imagine-video"
            assert preview not in {selected.model_id}
            assert lite not in {selected.model_id}

    unknown = [_row(preview, "video", 100), _row(lite, "video", 900)]
    r2v_unknown = resolve_model_selection(
        intent="best", role="video", need="r2v", catalog=unknown
    )
    assert r2v_unknown.model_id == "grok-imagine-video"
    assert r2v_unknown.source == "bootstrap"

    keeps_15 = resolve_model(
        intent="best",
        role="video",
        need="r2v",
        catalog=[_row(one_five, "video", 10), _row(preview, "video", 900)],
    )
    assert keeps_15 == one_five

    dated = "grok-imagine-video-1.5-2026-05-30"
    family_preview = "grok-imagine-video-1.5-preview"
    assert (
        resolve_model(
            intent="best",
            role="video",
            need="r2v",
            catalog=[_row(family_preview, "video", 10), _row(preview, "video", 900)],
        )
        == family_preview
    )
    assert (
        resolve_model(
            intent="best",
            role="video",
            need="r2v",
            catalog=[_row(dated, "video", 10), _row(lite, "video", 900)],
        )
        == dated
    )


def test_e5_quality_id_wins_extend_for_every_intent() -> None:
    """CAT-AC-EXTRAS-1 E-5."""
    catalog = [
        _row("grok-imagine-video", "video", 10),
        _row("grok-imagine-video-2.0-preview", "video", 800),
        _row("grok-imagine-video-3.0-lite", "video", 900),
    ]
    for intent in ("best", "economy", "cheapest"):
        assert (
            resolve_model(intent=intent, role="video", need="video_extend", catalog=catalog)
            == "grok-imagine-video"
        )


def test_e6_selection_matches_resolve_for_extend_pools() -> None:
    """CAT-AC-EXTRAS-1 E-6."""
    pools = [
        [
            _row("grok-imagine-video-1.5", "video", 10),
            _row("grok-imagine-video-2.0-preview", "video", 900),
        ],
        [
            _row("grok-imagine-video", "video", 10),
            _row("grok-imagine-video-2.0-preview", "video", 800),
            _row("grok-imagine-video-3.0-lite", "video", 900),
        ],
    ]
    for catalog in pools:
        for intent in ("best", "economy", "cheapest"):
            selected = resolve_model_selection(
                intent=intent,
                role="video",
                need="video_extend",
                catalog=catalog,
            )
            assert selected.model_id == resolve_model(
                intent=intent,
                role="video",
                need="video_extend",
                catalog=catalog,
            )
            assert selected.model_id == "grok-imagine-video"


def test_e7_catalog_documents_empty_extras_for_unknown_ids() -> None:
    """CAT-AC-EXTRAS-1 E-7."""
    text = _CATALOG_DOC.read_text(encoding="utf-8")
    assert "CAT-AC-EXTRAS-1" in text
    assert "has empty extras" in text
    assert "grok-imagine-video-2.0-preview" in text
    assert "2026-10-13" in text


def test_e8_pinned_unknown_id_stays_pinned() -> None:
    """CAT-AC-EXTRAS-1 E-8. Pin wins. Pool resolution still does not pick it."""
    pinned = "grok-imagine-video-2.0-preview"
    assert contract_model_for_need(pinned, "video_extend") == pinned
    catalog = [
        _row("grok-imagine-video-1.5", "video", 10),
        _row(pinned, "video", 900),
    ]
    assert (
        resolve_model(intent="best", role="video", need="video_extend", catalog=catalog)
        == "grok-imagine-video"
    )


def test_e9_quality_latest_and_dated_snapshot_keep_extras() -> None:
    """CAT-AC-EXTRAS-1 E-9."""
    assert feature_options("grok-imagine-video-latest") == _QUALITY
    assert feature_options("grok-imagine-video-2026-05-30") == _QUALITY
    assert feature_options("grok-imagine-video-20260530") == _QUALITY
