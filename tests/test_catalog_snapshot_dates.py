"""CAT-AC-SNAP-1 and CAT-AC-SNAP-2: snapshot dates in best and economy.

Dashed YYYY-MM-DD and compact YYYYMMDD are snapshot markers in every role.
A snapshot ranks behind the plain id or -latest alias of the same family.
The date is not a version number. When a family has only dated ids, the
newest calendar date wins. The penalty stays inside that family.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from xaikit.catalog import (
    _chat_major_minor,
    _imagine_video_version_nums,
    best_model,
    cheapest_model,
    clear_catalog_cache,
    economy_model,
    inject_catalog,
    list_models,
    prefer_latest_model,
    prefer_latest_video_model,
    resolve_model,
    resolve_model_selection,
)
from xaikit.types import ModelInfo, ModelSelection

_CATALOG_SPEC = (
    Path(__file__).resolve().parents[1] / "docs" / "features" / "Catalog.md"
)

# Today's public image ids (watch file, 2026-10-13). Prices come from the
# shipped table: base and the March snapshot 0.02, quality / pro / latest /
# quality snapshot 0.05, 2.0 at 0.06.
_PUBLIC_IMAGE_IDS = (
    "grok-imagine-image",
    "grok-imagine-image-2.0",
    "grok-imagine-image-2026-03-02",
    "grok-imagine-image-pro",
    "grok-imagine-image-quality",
    "grok-imagine-image-quality-20260403",
    "grok-imagine-image-quality-latest",
)
_IMAGE_DATED = {
    "grok-imagine-image-2026-03-02",
    "grok-imagine-image-quality-20260403",
}
_IMAGE_NOT_BEST = _IMAGE_DATED | {
    "grok-imagine-image-2.0",
    "grok-imagine-image-pro",
}


def _rows(
    pairs: list[tuple[str, int]],
    role: str,
    *,
    input_per_million: dict[str, float] | None = None,
) -> list[ModelInfo]:
    caps: list[str] = [] if role == "speech-to-text" else [role]
    prices = input_per_million or {}
    return [
        ModelInfo(
            id=model_id,
            capabilities=list(caps),
            created=created,
            input_per_million=prices.get(model_id),
        )
        for model_id, created in pairs
    ]


def _video(pairs: list[tuple[str, int]]) -> list[ModelInfo]:
    return _rows(pairs, "video")


def _assert_best(catalog: list[ModelInfo], role: str, want: str) -> None:
    assert best_model(catalog, role=role) == want
    assert prefer_latest_model(catalog, role=role) == want
    assert resolve_model(intent="best", role=role, catalog=catalog) == want
    selected = resolve_model_selection(intent="best", role=role, catalog=catalog)
    assert selected == ModelSelection(
        model_id=want, thought_level=None, source="intent:best"
    )


def _assert_video_best(catalog: list[ModelInfo], want: str) -> None:
    _assert_best(catalog, "video", want)
    assert prefer_latest_video_model(catalog) == want


def _assert_economy(catalog: list[ModelInfo], role: str, want: str) -> None:
    assert economy_model(catalog, role=role) == want
    assert resolve_model(intent="economy", role=role, catalog=catalog) == want
    selected = resolve_model_selection(intent="economy", role=role, catalog=catalog)
    assert selected.model_id == want
    assert selected.source == "intent:economy"


def _image_catalog(
    created_for: Callable[[str], int],
    *,
    include_latest: bool = True,
) -> list[ModelInfo]:
    ids = [
        model_id
        for model_id in _PUBLIC_IMAGE_IDS
        if include_latest or not model_id.endswith("-latest")
    ]
    return [
        ModelInfo(id=model_id, capabilities=["image"], created=created_for(model_id))
        for model_id in ids
    ]


def test_s1_1_compact_video_plain_beats_snapshot_same_created() -> None:
    """S1-1. Compact date is not a higher version than the plain id."""
    plain = "grok-imagine-video-1.5"
    snapshot = "grok-imagine-video-1.5-20260530"
    catalog = _video([(plain, 10), (snapshot, 10)])
    _assert_video_best(catalog, plain)
    _assert_economy(catalog, "video", plain)


def test_s1_2_compact_video_plain_beats_newer_created_snapshot() -> None:
    """S1-2. A newer created stamp does not let the compact snapshot win."""
    plain = "grok-imagine-video-1.5"
    snapshot = "grok-imagine-video-1.5-20260530"
    catalog = _video([(plain, 10), (snapshot, 900)])
    assert next(row.created for row in catalog if row.id == snapshot) > next(
        row.created for row in catalog if row.id == plain
    )
    _assert_video_best(catalog, plain)
    _assert_economy(catalog, "video", plain)


def test_s1_3_dashed_video_plain_beats_snapshot() -> None:
    """S1-3. Dashed snapshot stays behind plain 1.5 on a tie and when newer."""
    plain = "grok-imagine-video-1.5"
    snapshot = "grok-imagine-video-1.5-2026-05-30"
    tied = _video([(plain, 42), (snapshot, 42)])
    _assert_video_best(tied, plain)
    newer = _video([(plain, 10), (snapshot, 900)])
    _assert_video_best(newer, plain)
    _assert_economy(newer, "video", plain)


def test_s1_4_compact_date_is_not_a_higher_version() -> None:
    """S1-4. 20260530 is not a version above 2.0."""
    snapshot = "grok-imagine-video-1.5-20260530"
    plain_2 = "grok-imagine-video-2.0"
    catalog = _video([(snapshot, 10), (plain_2, 10)])
    assert "grok-imagine-video-1.5" not in {row.id for row in catalog}
    # 20260530 is not a version component. A parser that keeps it, or that
    # treats the largest digit group as the version, picks the snapshot.
    assert _imagine_video_version_nums("1.5-20260530") == (1, 5)
    assert _imagine_video_version_nums("2.0") == (2, 0)
    _assert_video_best(catalog, plain_2)


def test_s1_5_snapshot_loses_to_plain_in_every_role() -> None:
    """S1-5. Compact and dashed snapshots lose to plain in every role."""
    cases = (
        ("chat", "grok-4.7", "grok-4.7-20261001", "grok-4.7-2026-10-01"),
        (
            "image",
            "grok-imagine-image-quality",
            "grok-imagine-image-quality-20260403",
            "grok-imagine-image-quality-2026-04-03",
        ),
        (
            "voice",
            "grok-voice-think-fast-2.0",
            "grok-voice-think-fast-2.0-20261001",
            "grok-voice-think-fast-2.0-2026-10-01",
        ),
        (
            "speech-to-text",
            "grok-voice-transcribe-2.0",
            "grok-voice-transcribe-2.0-20261001",
            "grok-voice-transcribe-2.0-2026-10-01",
        ),
        (
            "video",
            "grok-imagine-video-1.5",
            "grok-imagine-video-1.5-20261001",
            "grok-imagine-video-1.5-2026-10-01",
        ),
    )
    for role, plain, compact, dashed in cases:
        for snapshot in (compact, dashed):
            catalog = _rows([(plain, 10), (snapshot, 900)], role)
            assert catalog[1].created is not None
            assert catalog[1].created > (catalog[0].created or 0)
            if role == "speech-to-text":
                assert catalog[0].capabilities == []
                assert catalog[1].capabilities == []
            if role == "video":
                _assert_video_best(catalog, plain)
            else:
                _assert_best(catalog, role, plain)


def test_s1_6_latest_alias_beats_newer_snapshot() -> None:
    """S1-6. -latest beats a newer compact snapshot of the same family."""
    latest = "grok-imagine-image-quality-latest"
    snapshot = "grok-imagine-image-quality-20260403"
    catalog = _rows([(latest, 10), (snapshot, 900)], "image")
    _assert_best(catalog, "image", latest)


def test_s1_7_economy_picks_plain_in_the_cheap_band() -> None:
    """S1-7. Economy uses the snapshot-aware key inside the cheaper band."""
    chat = _rows(
        [
            ("grok-4.7", 10),
            ("grok-4.3", 10),
            ("grok-4.3-20261001", 900),
        ],
        "chat",
        input_per_million={
            "grok-4.7": 2.0,
            "grok-4.3": 1.25,
            "grok-4.3-20261001": 1.25,
        },
    )
    _assert_best(chat, "chat", "grok-4.7")
    _assert_economy(chat, "chat", "grok-4.3")

    voice = _rows(
        [
            ("grok-voice-think-fast-2.0", 10),
            ("grok-voice-think-fast-1.0", 10),
            ("grok-voice-think-fast-1.0-20261001", 900),
        ],
        "voice",
    )
    _assert_best(voice, "voice", "grok-voice-think-fast-2.0")
    _assert_economy(voice, "voice", "grok-voice-think-fast-1.0")

    speech = _rows(
        [
            ("grok-voice-transcribe-2.0", 10),
            ("grok-voice-transcribe-1.0", 10),
            ("grok-voice-transcribe-1.0-20261001", 900),
        ],
        "speech-to-text",
        input_per_million={
            "grok-voice-transcribe-2.0": 2.0,
            "grok-voice-transcribe-1.0": 1.0,
            "grok-voice-transcribe-1.0-20261001": 1.0,
        },
    )
    assert speech[0].capabilities == []
    _assert_best(speech, "speech-to-text", "grok-voice-transcribe-2.0")
    _assert_economy(speech, "speech-to-text", "grok-voice-transcribe-1.0")

    image = _image_catalog(lambda _model_id: 10)
    _assert_economy(image, "image", "grok-imagine-image")


def test_s1_8_short_suffixes_are_not_snapshots() -> None:
    """S1-8. Four-digit suffixes and the offline chat best stay as they are."""
    historical = _rows(
        [
            ("grok-4.20", 1),
            ("grok-4.20-0309", 50),
        ],
        "chat",
    )
    _assert_best(historical, "chat", "grok-4.20-0309")

    coding = _rows(
        [
            ("grok-code-fast-1", 1),
            ("grok-code-fast-1-0825", 50),
        ],
        "chat",
    )
    _assert_best(coding, "chat", "grok-code-fast-1-0825")

    lineup = _rows(
        [
            ("grok-4.7", 1),
            ("grok-4.3", 1),
            ("grok-4.20-0309", 50),
            ("grok-4.20-0309-reasoning", 50),
            ("grok-code-fast-1-0825", 90),
        ],
        "chat",
    )
    _assert_best(lineup, "chat", "grok-4.7")

    # Valid compact boundary is a snapshot. An out-of-range 8-digit run is not,
    # so it still counts as version digits and can outrank the plain id.
    plain = "grok-imagine-video-1.5"
    _assert_video_best(
        _video([(plain, 10), ("grok-imagine-video-1.5-20000101", 900)]),
        plain,
    )
    _assert_video_best(
        _video([(plain, 10), ("grok-imagine-video-1.5-19991231", 10)]),
        "grok-imagine-video-1.5-19991231",
    )
    _assert_video_best(
        _video([(plain, 10), ("grok-imagine-video-1.5-20261301", 10)]),
        "grok-imagine-video-1.5-20261301",
    )

    inject_catalog(None)
    clear_catalog_cache()
    try:
        models = list_models(force_refresh=True, allow_fixture_fallback=True)
        assert resolve_model(intent="best", catalog=models) == "grok-4.7"
        assert best_model(models) == "grok-4.7"
    finally:
        inject_catalog(None)
        clear_catalog_cache()


def test_s1_9_dated_only_newer_family_beats_older_plain() -> None:
    """S1-9. The snapshot penalty does not cross families."""
    older = "grok-imagine-video-1.5"
    newer = "grok-imagine-video-2.0-20261001"
    catalog = _video([(older, 100), (newer, 200)])
    assert [row.created for row in catalog] == [100, 200]
    _assert_video_best(catalog, newer)

    image = _rows(
        [
            ("grok-imagine-image", 100),
            ("grok-imagine-image-quality-20260403", 200),
        ],
        "image",
    )
    _assert_best(image, "image", "grok-imagine-image-quality-20260403")

    chat = _rows(
        [
            ("grok-4.7", 100),
            ("grok-5-20261001", 200),
        ],
        "chat",
    )
    _assert_best(chat, "chat", "grok-5-20261001")


def test_s2_1_image_best_is_quality_latest_not_a_dated_id() -> None:
    """S2-1. Quality -latest wins for equal created and for a newest snapshot."""
    march = "grok-imagine-image-2026-03-02"
    quality_snap = "grok-imagine-image-quality-20260403"
    variants = (
        lambda _model_id: 10,
        lambda model_id: 900 if model_id == march else 10,
        lambda model_id: 900 if model_id == quality_snap else 10,
    )
    for created_for in variants:
        catalog = _image_catalog(created_for)
        assert {row.id for row in catalog} == set(_PUBLIC_IMAGE_IDS)
        want = "grok-imagine-image-quality-latest"
        _assert_best(catalog, "image", want)
        assert want not in _IMAGE_NOT_BEST
        assert best_model(catalog, role="image") not in _IMAGE_NOT_BEST


def test_s2_2_image_economy_is_plain_base_not_march_snapshot() -> None:
    """S2-2. Economy is grok-imagine-image, never the March snapshot."""
    march = "grok-imagine-image-2026-03-02"
    quality_snap = "grok-imagine-image-quality-20260403"
    variants = (
        lambda _model_id: 10,
        lambda model_id: 900 if model_id == march else 10,
        lambda model_id: 900 if model_id == quality_snap else 10,
    )
    for created_for in variants:
        catalog = _image_catalog(created_for)
        _assert_economy(catalog, "image", "grok-imagine-image")
        assert economy_model(catalog, role="image") != march
        # Multi-band cheapest tie-break is unchanged (Q6 control).
        assert cheapest_model(catalog, role="image") == "grok-imagine-image"


def test_s2_3_image_best_without_latest_is_quality_plain() -> None:
    """S2-3. Without -latest, best is the plain quality id, not a snapshot."""
    march = "grok-imagine-image-2026-03-02"
    quality_snap = "grok-imagine-image-quality-20260403"
    variants = (
        lambda _model_id: 10,
        lambda model_id: 900 if model_id == march else 10,
        lambda model_id: 900 if model_id == quality_snap else 10,
    )
    for created_for in variants:
        catalog = _image_catalog(created_for, include_latest=False)
        assert "grok-imagine-image-quality-latest" not in {row.id for row in catalog}
        _assert_best(catalog, "image", "grok-imagine-image-quality")
        assert best_model(catalog, role="image") not in _IMAGE_NOT_BEST


def test_s2_4_compact_video_snapshot_never_beats_plain_1_5() -> None:
    """S2-4. Same contract as S1-1 and S1-2, including economy."""
    plain = "grok-imagine-video-1.5"
    snapshot = "grok-imagine-video-1.5-20260530"
    for created in (10, 900):
        catalog = _video([(plain, 10), (snapshot, created)])
        _assert_video_best(catalog, plain)
        _assert_economy(catalog, "video", plain)
        assert prefer_latest_video_model(catalog) != snapshot


def test_s2_5_only_dated_family_newest_calendar_date_wins() -> None:
    """S2-5. Newest date in the id wins, including over a newer created stamp."""
    older = "grok-imagine-image-quality-20260403"
    newer = "grok-imagine-image-quality-20260601"
    image = _rows([(older, 900), (newer, 1)], "image")
    assert image[0].created is not None and image[1].created is not None
    assert image[0].created > image[1].created
    _assert_best(image, "image", newer)

    tied_image = _rows([(older, 10), (newer, 10)], "image")
    _assert_best(tied_image, "image", newer)

    may = "grok-imagine-video-1.5-2026-05-30"
    july = "grok-imagine-video-1.5-2026-07-01"
    dashed = _video([(may, 900), (july, 1)])
    _assert_video_best(dashed, july)

    mixed = _video(
        [
            ("grok-imagine-video-1.5-2026-05-30", 900),
            ("grok-imagine-video-1.5-20260701", 1),
        ]
    )
    _assert_video_best(mixed, "grok-imagine-video-1.5-20260701")


def test_s2_6_catalog_spec_records_snapshot_acceptance() -> None:
    """S2-6. Acceptance rows and behavior wording live on the catalog spec."""
    text = _CATALOG_SPEC.read_text(encoding="utf-8")
    assert "CAT-AC-SNAP-1" in text
    assert "CAT-AC-SNAP-2" in text
    assert "2026-10-13" in text
    assert "snapshot markers in every role" in text
    assert "YYYY-MM-DD" in text
    assert "YYYYMMDD" in text
    assert "dashed" in text.lower()
    assert "compact" in text.lower()


def test_undotted_chat_snapshot_date_is_not_a_minor() -> None:
    """A trailing snapshot date is not the minor of grok-4 or grok-5.

    Chat best and economy compare (major, minor) before the plain-id flag.
    Parsing -20260530 or -2026-05-30 as that minor lets the dated id beat
    the plain id, and lets a grok-4 snapshot outrank grok-4.7.
    """
    assert _chat_major_minor("grok-4") == (4, 0)
    assert _chat_major_minor("grok-4-20260530") == (4, 0)
    assert _chat_major_minor("grok-4-2026-05-30") == (4, 0)
    assert _chat_major_minor("grok-5") == (5, 0)
    assert _chat_major_minor("grok-5-20260530") == (5, 0)
    assert _chat_major_minor("grok-5-2026-05-30") == (5, 0)
    assert _chat_major_minor("grok-4.7") == (4, 7)
    assert _chat_major_minor("grok-4.7-20261001") == (4, 7)
    assert _chat_major_minor("grok-4.7-2026-10-01") == (4, 7)
    assert _chat_major_minor("grok-4.20") == (4, 2)
    assert _chat_major_minor("grok-4.20-0309") == (4, 2)

    for plain, compact, dashed in (
        ("grok-4", "grok-4-20260530", "grok-4-2026-05-30"),
        ("grok-5", "grok-5-20260530", "grok-5-2026-05-30"),
    ):
        for snapshot in (compact, dashed):
            catalog = _rows([(plain, 10), (snapshot, 900)], "chat")
            _assert_best(catalog, "chat", plain)
            _assert_economy(catalog, "chat", plain)

    for snapshot in ("grok-4-20260530", "grok-4-2026-05-30"):
        catalog = _rows([("grok-4.7", 10), (snapshot, 900)], "chat")
        _assert_best(catalog, "chat", "grok-4.7")
        _assert_economy(catalog, "chat", "grok-4.7")

    priced = _rows(
        [
            ("grok-4.7", 10),
            ("grok-4", 10),
            ("grok-4-20260530", 900),
            ("grok-4-2026-05-30", 800),
        ],
        "chat",
        input_per_million={
            "grok-4.7": 2.0,
            "grok-4": 1.25,
            "grok-4-20260530": 1.25,
            "grok-4-2026-05-30": 1.25,
        },
    )
    _assert_best(priced, "chat", "grok-4.7")
    _assert_economy(priced, "chat", "grok-4")


def test_newer_lite_and_preview_do_not_become_video_best() -> None:
    """A newer lite id, including a compact date, stays below plain 1.5."""
    catalog = _video(
        [
            ("grok-imagine-video-1.5", 1),
            ("grok-imagine-video-1.5-lite-20261004", 500),
            ("grok-imagine-video-2.0-preview", 900),
        ]
    )
    _assert_video_best(catalog, "grok-imagine-video-1.5")
