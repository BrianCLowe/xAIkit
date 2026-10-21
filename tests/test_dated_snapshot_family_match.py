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
    _date_match_families,
    _dated_image_or_video_family,
    _shipped_role_map,
    best_model,
    clear_catalog_cache,
    describe_listed_id,
    inject_catalog,
    static_role_for_id,
)
from xaikit.pricing import default_price_table
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
        QUALITY,
        PRO,
        VIDEO_QUALITY,
        VIDEO_15,
        VIDEO_LITE,
        PREVIEW,
    }
    dated = (
        (IMAGE_COMPACT, "image", QUALITY),
        (IMAGE_DASHED, "image", PLAIN),
        (IMAGE_DASHED_TWIN, "image", QUALITY),
        (VIDEO_DASHED, "video", VIDEO_15),
        (VIDEO_COMPACT, "video", VIDEO_15),
        (VIDEO_LITE_DATED, "video", VIDEO_LITE),
        (PRO_DATED, "image", PRO),
        (PREVIEW_DATED, "video", PREVIEW),
        (VIDEO_QUALITY_DATED, "video", VIDEO_QUALITY),
        (DAY_31, "image", PLAIN),
        (f" {IMAGE_DASHED} ", "image", PLAIN),
    )
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
    assert table.price_for(IMAGE_COMPACT) is not table.price_for(PLAIN)
    assert table.price_for(VIDEO_LITE_DATED) is not table.price_for(VIDEO_15)
    assert table.price_for(PRO_DATED) is not table.price_for(PLAIN)
    assert table.price_for(QUALITY).per_call_usd == 0.05
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
    """A host that lists only unknown dated snapshots uses them for that role."""
    host = _host((IMAGE_COMPACT, VIDEO_DASHED))
    try:
        client = _client(cls, host)
        _call(client, "generate_image", "cat")
        _call(client, "generate_video", "clip", into=[], wait=False)
        assert client.image_model == IMAGE_COMPACT
        assert client.video_model == VIDEO_DASHED
        with pytest.raises(RoleUnavailableOnHost) as caught:
            _ = client.model
        assert caught.value.role == "chat"
        assert caught.value.host == host["host"]
        assert _posted_models(host["records"], "/images/generations") == [IMAGE_COMPACT]
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
    assert best_model(image, role="image") == "grok-imagine-image-quality-latest"
    dated_only = [
        ModelInfo(id="grok-imagine-image-2026-03-02", capabilities=["image"], created=200),
        ModelInfo(
            id="grok-imagine-image-quality-20260403",
            capabilities=["image"],
            created=300,
        ),
    ]
    assert best_model(dated_only, role="image") == "grok-imagine-image-quality-20260403"
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
