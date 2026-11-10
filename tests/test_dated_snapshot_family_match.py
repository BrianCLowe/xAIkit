"""CUT-2026-10-21-xk-dated-snapshot-family-match.

DS-AC-1 and DS-AC-2. Offline only. Loopback host fixture from
test_regional_endpoint. No live calls and no API key.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from xaikit import AsyncXaiClient, RoleUnavailableOnHost, UsageMeter, XaiClient
from xaikit.catalog import (
    DEFAULT_IMAGE_MODEL,
    _date_match_families,
    _dated_image_or_video_family,
    _dated_only_rank,
    _shipped_role_map,
    best_model,
    clear_catalog_cache,
    describe_listed_id,
    inject_catalog,
    prefer_latest_model,
    static_role_for_id,
)
from xaikit.pricing import _DEFAULT_IMAGE_MODELS, default_price_table
from xaikit.provider import MockChatProvider
from xaikit.types import ModelInfo


def _load_regional_endpoint():
    """Load the existing loopback host helpers without editing that file."""
    path = Path(__file__).resolve().with_name("test_regional_endpoint.py")
    spec = importlib.util.spec_from_file_location(
        "xaikit_ds_dated_snapshot_regional_fixture", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load loopback host fixture from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_regional = _load_regional_endpoint()
_start_host = _regional._start_host
_stop = _regional._stop
_apply_loopback_only = _regional._loopback_only.__wrapped__

KEY = "xai-test-FAKE"
QUALITY = "grok-imagine-image-quality"
PLAIN = "grok-imagine-image"
PRO = "grok-imagine-image-pro"
VIDEO_15 = "grok-imagine-video-1.5"
VIDEO_LITE = "grok-imagine-video-1.5-lite"
IMAGE_COMPACT = "grok-imagine-image-quality-20990101"
IMAGE_DASHED = "grok-imagine-image-2099-01-01"
IMAGE_DASHED_TWIN = "grok-imagine-image-quality-2026-04-03"
VIDEO_DASHED = "grok-imagine-video-1.5-2099-01-01"
VIDEO_COMPACT = "grok-imagine-video-1.5-20260530"
VIDEO_LITE_DATED = "grok-imagine-video-1.5-lite-20990101"
PRO_DATED = "grok-imagine-image-pro-2099-01-01"
DAY_31 = "grok-imagine-image-20260231"
PREVIEW = "grok-imagine-video-1.5-preview"
PREVIEW_DATED = "grok-imagine-video-1.5-preview-20990101"
VIDEO_QUALITY = "grok-imagine-video"
VIDEO_QUALITY_DATED = "grok-imagine-video-2099-01-01"
NOT_A_FAMILY = (
    "grok-imagine-image-quality-latest-2026-07-01",
    "grok-imagine-image-2026-03-02-20260101",
    "grok-imagine-image-quality-20260403-20260101",
    "grok-imagine-video-1.5-2026-05-30-2026-07-01",
)
PREFIX_VIDEO = "grok-imagine-video-2.0-preview"
PREFIX_LATEST_X = "grok-imagine-image-quality-latest-x"
EXACT_IMAGE = (
    "grok-imagine-image-quality-latest",
    "grok-imagine-image-2026-03-02",
    "grok-imagine-image-quality-20260403",
)
EXACT_VIDEO = (
    "grok-imagine-video-1.5-2026-05-30",
    "grok-imagine-video-1.5-preview",
)


@pytest.fixture(autouse=True)
def _no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XAI_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def _clean_catalog():
    inject_catalog(None)
    clear_catalog_cache()
    yield
    inject_catalog(None)
    clear_catalog_cache()


@pytest.fixture(autouse=True)
def _loopback_only(monkeypatch: pytest.MonkeyPatch):
    """Same socket guard as tests/test_regional_endpoint.py."""
    _apply_loopback_only(monkeypatch)


def _host(ids: tuple[str, ...] | list[str]):
    return _start_host(list(ids))


def _client(cls: type, host: dict[str, Any], **kwargs: Any) -> Any:
    params: dict[str, Any] = {
        "api_key": KEY,
        "base_url": host["base"],
        "intent": "best",
        "provider": MockChatProvider("ok"),
    }
    params.update(kwargs)
    return cls(**params)


def _call(client: Any, name: str, *args: Any, **kwargs: Any) -> Any:
    out = getattr(client, name)(*args, **kwargs)
    if asyncio.iscoroutine(out):
        return asyncio.run(out)
    return out


def _posted_models(records: list[dict[str, Any]], suffix: str) -> list[str]:
    found: list[str] = []
    for row in records:
        if row["method"] != "POST" or not row["path"].endswith(suffix):
            continue
        found.append(str(json.loads(row["body"].decode()).get("model")))
    return found


def _assert_loopback_only(records: list[dict[str, Any]]) -> None:
    for row in records:
        assert "api.x.ai" not in row["path"]
        assert KEY not in row["path"]


def test_ds_ac_1_dated_snapshots_take_the_family_role() -> None:
    """Unknown dated image and video ids resolve. Exact keys stay exact."""
    table = default_price_table()
    roles = _shipped_role_map()
    assert set(_date_match_families(roles)) == {
        PLAIN,
        "grok-imagine-image-2.0",
        VIDEO_QUALITY,
        VIDEO_15,
        VIDEO_LITE,
        PREVIEW,
        QUALITY,
        PRO,
    }
    dated = (
        (IMAGE_DASHED, "image", PLAIN),
        (VIDEO_DASHED, "video", VIDEO_15),
        (VIDEO_COMPACT, "video", VIDEO_15),
        (VIDEO_LITE_DATED, "video", VIDEO_LITE),
        (PREVIEW_DATED, "video", PREVIEW),
        (VIDEO_QUALITY_DATED, "video", VIDEO_QUALITY),
        (DAY_31, "image", PLAIN),
        (f" {IMAGE_DASHED} ", "image", PLAIN),
    )
    retired = (
        (IMAGE_COMPACT, QUALITY),
        (IMAGE_DASHED_TWIN, QUALITY),
        (PRO_DATED, PRO),
    )
    for mid, family in retired:
        assert mid not in roles
        assert _dated_image_or_video_family(mid, roles) == family
        assert static_role_for_id(mid) == "image"
        info, got = describe_listed_id(mid)
        assert got == "image"
        assert info.capabilities == ["image"]
        assert table.price_for(mid) is None
    for mid, role, family in dated:
        assert mid.strip() not in roles
        assert _dated_image_or_video_family(mid.strip(), roles) == family
        assert static_role_for_id(mid) == role
        assert static_role_for_id(mid) == static_role_for_id(family)
        info, got = describe_listed_id(mid.strip())
        assert got == role
        assert info.id == mid.strip()
        assert info.capabilities == [role]
        assert table.price_for(mid.strip()) is table.price_for(family)
    assert table.price_for(IMAGE_COMPACT) is None
    assert table.price_for(VIDEO_LITE_DATED) is not table.price_for(VIDEO_15)
    assert table.price_for(PRO_DATED) is None
    assert table.price_for(QUALITY) is None
    assert table.price_for(PRO) is None
    assert QUALITY not in table.models
    assert PRO not in table.models
    assert table.price_for(PLAIN).per_call_usd == 0.02
    assert table.price_for(VIDEO_15).per_second_usd == 0.08
    assert table.price_for(VIDEO_LITE).per_second_usd == 0.02
    for mid in EXACT_IMAGE:
        assert mid in roles
        assert static_role_for_id(mid) == "image"
    for mid in EXACT_VIDEO:
        assert mid in roles
        assert static_role_for_id(mid) == "video"
    assert static_role_for_id("grok-imagine-image-quality-latest") == "image"


def test_ds_ac_2_prefix_without_a_date_stays_chat() -> None:
    """A shared prefix is not a match. -latest is not a date."""
    stay_chat = (
        PREFIX_VIDEO,
        PREFIX_LATEST_X,
        "grok-imagine-video-latest",
        "grok-imagine-image-latest",
        "grok-imagine-image-",
        "grok-imagine-image-2026-13-01",
        "grok-imagine-image-quality-20261301",
        "grok-imagine-image-1999-01-01",
        "grok-imagine-image-2100-01-01",
        "grok-imagine-image-2026-00-01",
        "grok-imagine-image-2026-01-00",
        "grok-imagine-image-quality-0309",
        "grok-imagine-image-2099-01-01-extra",
        "grok-imagine-image-quality-20990101x",
        "GROK-IMAGINE-IMAGE-2099-01-01",
        "grok_imagine_image_2099-01-01",
        "grok-4-2099-01-01",
        "grok-voice-latest-20990101",
        "grok-voice-transcribe-2.0-2099-01-01",
        *NOT_A_FAMILY,
        "",
        "   ",
    )
    roles = _shipped_role_map()
    for mid in NOT_A_FAMILY:
        assert _dated_image_or_video_family(mid, roles) is None
    for mid in stay_chat:
        assert static_role_for_id(mid) == "chat"
        info, got = describe_listed_id(mid.strip() or mid)
        assert got == "chat"
        assert info.capabilities == ["chat"]
    assert static_role_for_id("grok-voice-latest") == "voice"
    assert static_role_for_id("grok-voice-transcribe-2.0") == "speech-to-text"


@pytest.mark.parametrize("cls", [XaiClient, AsyncXaiClient])
def test_ds_ac_1_sync_and_async_resolve_the_dated_snapshot(cls) -> None:
    """Video dated snapshots still resolve. A retired quality snapshot does not.

    The quality id is image for role and is not selected, so image and chat
    are unavailable on a host that lists only that id plus a video snapshot.
    """
    host = _host((IMAGE_COMPACT, VIDEO_DASHED))
    try:
        client = _client(cls, host)
        with pytest.raises(RoleUnavailableOnHost) as image_caught:
            _call(client, "generate_image", "cat")
        assert image_caught.value.role == "image"
        assert image_caught.value.host == host["host"]
        _call(client, "generate_video", "clip", into=[], wait=False)
        assert client.video_model == VIDEO_DASHED
        with pytest.raises(RoleUnavailableOnHost) as chat_caught:
            _ = client.model
        assert chat_caught.value.role == "chat"
        assert chat_caught.value.host == host["host"]
        assert _posted_models(host["records"], "/images/generations") == []
        assert _posted_models(host["records"], "/videos/generations") == [VIDEO_DASHED]
        _assert_loopback_only(host["records"])
    finally:
        _stop(host)


@pytest.mark.parametrize("cls", [XaiClient, AsyncXaiClient])
def test_ds_ac_2_sync_and_async_prefix_does_not_match(cls) -> None:
    """Prefix-only ids stay chat on both clients and are not image or video."""
    host = _host((PREFIX_VIDEO, PREFIX_LATEST_X))
    try:
        client = _client(cls, host)
        for name, args, kwargs, role in (
            ("generate_image", ("cat",), {}, "image"),
            ("generate_video", ("clip",), {"into": [], "wait": False}, "video"),
        ):
            with pytest.raises(RoleUnavailableOnHost) as caught:
                _call(client, name, *args, **kwargs)
            assert caught.value.role == role
            assert caught.value.host == host["host"]
        assert client.model in {PREFIX_VIDEO, PREFIX_LATEST_X}
        assert _posted_models(host["records"], "/images/generations") == []
        assert _posted_models(host["records"], "/videos/generations") == []
        _assert_loopback_only(host["records"])
    finally:
        _stop(host)


def _extension_models(records: list[dict[str, Any]]) -> list[str]:
    found: list[str] = []
    for row in records:
        if row["method"] != "POST" or not row["path"].endswith("/videos/extensions"):
            continue
        found.append(str(json.loads(row["body"].decode()).get("model")))
    return found


def test_ds_best_model_ranking_unchanged() -> None:
    """Family role matching does not change best_model."""
    image = [
        ModelInfo(
            id="grok-imagine-image-quality-latest",
            capabilities=["image"],
            created=100,
        ),
        ModelInfo(id="grok-imagine-image-2026-03-02", capabilities=["image"], created=200),
        ModelInfo(
            id="grok-imagine-image-quality-20260403",
            capabilities=["image"],
            created=300,
        ),
    ]
    assert best_model(image, role="image") == "grok-imagine-image-2026-03-02"
    dated_only = [
        ModelInfo(id="grok-imagine-image-2026-03-02", capabilities=["image"], created=200),
        ModelInfo(
            id="grok-imagine-image-quality-20260403",
            capabilities=["image"],
            created=300,
        ),
    ]
    assert best_model(dated_only, role="image") == "grok-imagine-image-2026-03-02"
    retired = ModelInfo(
        id="grok-imagine-image-quality-20260601",
        capabilities=["image"],
        created=1,
    )
    exact = ModelInfo(
        id="grok-imagine-image-quality-20260403",
        capabilities=["image"],
        created=1,
    )
    assert _dated_only_rank(retired) > _dated_only_rank(exact)
    video = [
        ModelInfo(id=VIDEO_15, capabilities=["video"], created=10),
        ModelInfo(id="grok-imagine-video-1.5-2026-05-30", capabilities=["video"], created=999),
        ModelInfo(id=PREVIEW, capabilities=["video"], created=999),
    ]
    assert best_model(video, role="video") == VIDEO_15
    chat = [
        ModelInfo(id="grok-4.7", capabilities=["chat"], created=1),
        ModelInfo(id="grok-4-20260530", capabilities=["chat"], created=9),
    ]
    assert best_model(chat, role="chat") == "grok-4.7"


@pytest.mark.parametrize("cls", [XaiClient, AsyncXaiClient])
def test_ds_c10_extend_video_posts_the_dated_quality_snapshot(cls) -> None:
    """A dated snapshot of unversioned grok-imagine-video can extend."""
    host = _host((VIDEO_QUALITY_DATED,))
    try:
        client = _client(cls, host)
        with pytest.raises(RuntimeError) as caught:
            _call(
                client,
                "extend_video",
                "more",
                video_url="http://127.0.0.1/v.mp4",
                into=[],
                wait=False,
            )
        assert "request_id" in str(caught.value)
        assert _extension_models(host["records"]) == [VIDEO_QUALITY_DATED]
        _assert_loopback_only(host["records"])
    finally:
        _stop(host)


@pytest.mark.parametrize("cls", [XaiClient, AsyncXaiClient])
def test_ds_c12_dated_plain_image_usage_is_two_cents(cls) -> None:
    """A dated snapshot of plain grok-imagine-image meters at 0.02 per image."""
    host = _host((IMAGE_DASHED,))
    meter = UsageMeter()
    try:
        client = _client(cls, host, usage_meter=meter)
        _call(client, "generate_image", "cat", purpose="image")
        events = meter.events(purpose="image")
        assert len(events) == 1
        assert events[0].success is True
        assert events[0].model == IMAGE_DASHED
        assert events[0].estimated_usd == 0.02
        _assert_loopback_only(host["records"])
    finally:
        _stop(host)


PRO_COMPACT = "grok-imagine-image-pro-20260501"
QUALITY_DATED = "grok-imagine-image-quality-20260601"
EXACT_QUALITY_SNAP = "grok-imagine-image-quality-20260403"
EXACT_QUALITY_LATEST = "grok-imagine-image-quality-latest"


def _image_row(model_id: str, created: int = 1) -> ModelInfo:
    return ModelInfo(id=model_id, capabilities=["image"], created=created)


def _tier_rows(price: Any) -> list[tuple[str, str | None, float]]:
    return [
        (tier.resolution, tier.quality, tier.per_call_usd)
        for tier in (price.image_tiers or [])
    ]


def test_retired_pro_dated_snapshot_is_image() -> None:
    """DSR-C01. Unlisted pro dated snapshots resolve as image."""
    for mid in (PRO_COMPACT, PRO_DATED, f" {PRO_COMPACT} "):
        assert static_role_for_id(mid) == "image"
        info, role = describe_listed_id(mid.strip())
        assert role == "image"
        assert info.id == mid.strip()
        assert info.capabilities == ["image"]


def test_retired_quality_dated_snapshot_is_image() -> None:
    """DSR-C02. Unlisted quality dated snapshots resolve as image."""
    for mid in (QUALITY_DATED, IMAGE_COMPACT, IMAGE_DASHED_TWIN):
        assert static_role_for_id(mid) == "image"
        info, role = describe_listed_id(mid)
        assert role == "image"
        assert info.capabilities == ["image"]


def test_retired_dated_snapshots_have_no_price() -> None:
    """DSR-C03. Retired ids have no price, exact aliases included (RQBQ-3)."""
    table = default_price_table()
    for mid in (
        PRO_COMPACT,
        QUALITY_DATED,
        IMAGE_COMPACT,
        IMAGE_DASHED_TWIN,
        PRO_DATED,
        f" {QUALITY_DATED} ",
    ):
        assert table.price_for(mid) is None
        assert mid.strip() not in table.models
    assert QUALITY not in table.models
    assert PRO not in table.models
    assert QUALITY not in _DEFAULT_IMAGE_MODELS
    assert PRO not in _DEFAULT_IMAGE_MODELS
    plain = table.price_for(PLAIN)
    assert table.price_for(QUALITY) is None
    assert table.price_for(PRO) is None
    assert table.price_for(EXACT_QUALITY_SNAP) is None
    assert table.price_for(f" {EXACT_QUALITY_SNAP} ") is None
    assert table.price_for(EXACT_QUALITY_LATEST) is None
    assert plain is not None
    assert plain.media_input_per_image_usd == 0.002
    assert _tier_rows(plain) == [
        ("1k", None, 0.02),
        ("2k", None, 0.02),
    ]
    image_2 = table.price_for("grok-imagine-image-2.0")
    assert image_2 is not None
    assert image_2.per_call_usd == 0.04
    assert image_2.media_input_per_image_usd == 0.01
    assert _tier_rows(image_2) == [
        ("1k", "low", 0.04),
        ("1.5k", "low", 0.05),
        ("2k", "low", 0.06),
        ("1k", "medium", 0.06),
        ("1.5k", "medium", 0.07),
        ("2k", "medium", 0.08),
    ]


def test_retired_dated_snapshots_not_best_image() -> None:
    """DSR-C04. Image selection skips unlisted retired dated ids."""
    retired_ids = {PRO_COMPACT, QUALITY_DATED}
    only = [_image_row(PRO_COMPACT, 1), _image_row(QUALITY_DATED, 1)]
    assert best_model(only, role="image") is None
    assert prefer_latest_model(only, role="image") is None
    mixed = [
        _image_row(PLAIN, 1),
        _image_row(EXACT_QUALITY_LATEST, 50),
        _image_row(EXACT_QUALITY_SNAP, 10),
        _image_row(PRO_COMPACT, 999),
        _image_row(QUALITY_DATED, 998),
    ]
    assert best_model(mixed, role="image") not in retired_ids
    sibling = [
        _image_row(EXACT_QUALITY_SNAP, 900),
        _image_row(QUALITY_DATED, 1),
    ]
    assert best_model(sibling, role="image") == EXACT_QUALITY_SNAP
    for cls in (XaiClient, AsyncXaiClient):
        host = _host((PRO_COMPACT, QUALITY_DATED))
        try:
            client = _client(cls, host)
            with pytest.raises(RoleUnavailableOnHost) as caught:
                _call(client, "generate_image", "cat")
            assert caught.value.role == "image"
            assert caught.value.host == host["host"]
            assert _posted_models(host["records"], "/images/generations") == []
        finally:
            _stop(host)
        mixed_host = _host((EXACT_QUALITY_LATEST, QUALITY_DATED))
        try:
            client = _client(cls, mixed_host)
            assert client.image_model == EXACT_QUALITY_LATEST
            assert client.image_model != QUALITY_DATED
        finally:
            _stop(mixed_host)


def test_exact_quality_aliases_stay_image() -> None:
    """DSR-C05. Exact quality aliases stay image and eligible; unpriced (RQBQ-3)."""
    roles = _shipped_role_map()
    table = default_price_table()
    for mid in (EXACT_QUALITY_SNAP, EXACT_QUALITY_LATEST):
        assert mid in roles
        assert roles[mid] == "image"
        assert static_role_for_id(mid) == "image"
        info, role = describe_listed_id(mid)
        assert role == "image"
        assert info.capabilities == ["image"]
    assert table.price_for(EXACT_QUALITY_SNAP) is None
    assert table.price_for(EXACT_QUALITY_LATEST) is None
    assert best_model([_image_row(EXACT_QUALITY_SNAP)], role="image") == EXACT_QUALITY_SNAP
    assert best_model([_image_row(EXACT_QUALITY_LATEST)], role="image") == EXACT_QUALITY_LATEST


def test_unknown_non_image_id_stays_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    """DSR-C06. Unknown ids and invalid near ids stay chat.

    Static role does not read the REST model list.
    """

    def _rest_forbidden(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("static role consulted REST")

    monkeypatch.setattr("httpx.get", _rest_forbidden)
    stay_chat = (
        "not-a-model",
        "grok-imagine-image-quality",
        "grok-imagine-image-pro",
        "grok-imagine-video-2.0-preview",
        "grok-imagine-image-quality-latest-x",
        "grok-imagine-image-quality-latest-2026-07-01",
        "grok-imagine-image-2026-13-01",
        "grok-imagine-image-quality-20261301",
        "grok-imagine-image-quality-0309",
        "grok-imagine-image-quality-20990101x",
        "grok-imagine-image-2099-01-01-extra",
        "GROK-IMAGINE-IMAGE-QUALITY-20260601",
        "grok_imagine_image_quality_20260601",
        "grok-imagine-image-pro-latest",
        "grok-4-2099-01-01",
        "",
        "   ",
    )
    for mid in stay_chat:
        assert static_role_for_id(mid) == "chat"
        info, role = describe_listed_id(mid.strip() or mid)
        assert role == "chat"
        assert info.capabilities == ["chat"]


def test_retired_set_is_role_only_and_exact() -> None:
    """DSR-C07. Date matching adds exactly the two retired image families."""
    roles = _shipped_role_map()
    families = _date_match_families(roles)
    assert set(families) == {
        PLAIN,
        "grok-imagine-image-2.0",
        VIDEO_QUALITY,
        VIDEO_15,
        VIDEO_LITE,
        PREVIEW,
        QUALITY,
        PRO,
    }
    assert families[QUALITY] == "image"
    assert families[PRO] == "image"
    assert QUALITY not in roles
    assert PRO not in roles
    assert static_role_for_id(QUALITY) == "chat"
    assert static_role_for_id(PRO) == "chat"
    table = default_price_table()
    assert QUALITY not in table.models
    assert PRO not in table.models
    assert QUALITY not in _DEFAULT_IMAGE_MODELS
    assert PRO not in _DEFAULT_IMAGE_MODELS
    assert DEFAULT_IMAGE_MODEL == "grok-imagine-image-2.0"
    assert "grok-imagine-video-2.0" not in families
    assert static_role_for_id("grok-imagine-video-2099-01-01") == "video"
    assert static_role_for_id(IMAGE_DASHED) == "image"
