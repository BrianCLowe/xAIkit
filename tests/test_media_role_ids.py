"""CUT-2026-10-15-xk-media-role-ids.

MR-AC-1 and MR-AC-2. Offline only: inject_catalog, and the loopback host
fixture from test_regional_endpoint (_start_host, _loopback_only).
No live calls and no API key.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from xaikit import AsyncXaiClient, RoleUnavailableOnHost, XaiClient
from xaikit.catalog import (
    KNOWN_ROLES,
    _ROLE_BOOTSTRAP,
    _shipped_role_map,
    best_model,
    clear_catalog_cache,
    describe_listed_id,
    inject_catalog,
    normalize_role,
    static_role_for_id,
)
from xaikit.pricing import (
    _DEFAULT_IMAGE_MODELS,
    _DEFAULT_MODELS,
    _DEFAULT_STT_MODELS,
    _DEFAULT_VIDEO_MODELS,
    _DEFAULT_VOICE_MODELS,
    default_price_table,
)
from xaikit.provider import MockChatProvider
from xaikit.types import ModelInfo


def _load_regional_endpoint():
    """Load the existing loopback host helpers without editing that file."""
    path = Path(__file__).resolve().with_name("test_regional_endpoint.py")
    spec = importlib.util.spec_from_file_location("xaikit_regional_endpoint_fixture", path)
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
IMAGE_LATEST = "grok-imagine-image-quality-latest"
IMAGE_MARCH = "grok-imagine-image-2026-03-02"
IMAGE_QUALITY_SNAP = "grok-imagine-image-quality-20260403"
VIDEO_STABLE = "grok-imagine-video-1.5-2026-05-30"
VIDEO_PREVIEW = "grok-imagine-video-1.5-preview"
IMAGE_IDS = (IMAGE_LATEST, IMAGE_MARCH, IMAGE_QUALITY_SNAP)
VIDEO_IDS = (VIDEO_STABLE, VIDEO_PREVIEW)
MEDIA_IDS = IMAGE_IDS + VIDEO_IDS
IMAGE_ROLE = {
    IMAGE_LATEST: "image",
    IMAGE_MARCH: "image",
    IMAGE_QUALITY_SNAP: "image",
    VIDEO_STABLE: "video",
    VIDEO_PREVIEW: "video",
}
NEAR_IDS = (
    ("grok-imagine-image-quality-20990101", "image"),
    ("grok-imagine-image-2099-01-01", "image"),
    ("grok-imagine-video-1.5-2099-01-01", "video"),
    ("grok-imagine-video-2.0-preview", "chat"),
    ("grok-imagine-image-quality-latest-x", "chat"),
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


def _host(ids: tuple[str, ...] | list[str], *, created: dict[str, int] | None = None):
    body = None
    if created is not None:
        body = {
            "data": [
                {
                    "id": mid,
                    "object": "model",
                    "role": "chat",
                    "capabilities": ["chat"],
                    "created": created[mid],
                }
                for mid in ids
            ]
        }
    return _start_host(list(ids), body=body)


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


def _base_role_map() -> dict[str, str]:
    """Role map as built before the five exact Imagine ids."""
    roles: dict[str, str] = {}
    for mid in _DEFAULT_MODELS:
        if mid != "default":
            roles[mid] = "chat"
    for mid in _DEFAULT_IMAGE_MODELS:
        roles[mid] = "image"
    for mid in _DEFAULT_VIDEO_MODELS:
        roles[mid] = "video"
    for mid in _DEFAULT_VOICE_MODELS:
        roles[mid] = "voice"
    for mid in _DEFAULT_STT_MODELS:
        roles[mid] = "speech-to-text"
    roles["grok-voice-transcribe-1.0"] = "speech-to-text"
    roles["grok-voice-transcribe-2.0"] = "speech-to-text"
    return roles


def test_mr_c01_image_quality_latest_is_image() -> None:
    assert static_role_for_id(IMAGE_LATEST) == "image"


def test_mr_c02_image_march_snapshot_is_image() -> None:
    assert static_role_for_id(IMAGE_MARCH) == "image"


def test_mr_c03_image_quality_compact_snapshot_is_image() -> None:
    assert static_role_for_id(IMAGE_QUALITY_SNAP) == "image"


def test_mr_c04_video_stable_snapshot_is_video() -> None:
    assert static_role_for_id(VIDEO_STABLE) == "video"


def test_mr_c05_video_preview_is_video() -> None:
    assert static_role_for_id(VIDEO_PREVIEW) == "video"


def test_mr_c06_describe_listed_id_role_and_capabilities() -> None:
    for mid, role in IMAGE_ROLE.items():
        info, got = describe_listed_id(mid)
        assert got == role
        assert info.id == mid
        assert info.capabilities == [role]


def test_mr_c07_near_ids_stay_chat_and_strip_is_exact() -> None:
    for mid, role in NEAR_IDS:
        assert static_role_for_id(mid) == role
    padded = " grok-imagine-image-quality-latest"
    assert static_role_for_id(padded) == "image"
    assert static_role_for_id(padded) == static_role_for_id(padded.strip())


def test_mr_c08_case_and_underscore_stay_chat() -> None:
    assert static_role_for_id("GROK-IMAGINE-IMAGE-QUALITY-LATEST") == "chat"
    assert static_role_for_id("grok_imagine_video_1.5_preview") == "chat"


def test_mr_c09_existing_role_map_entries_keep_their_roles() -> None:
    base = _base_role_map()
    current = _shipped_role_map()
    assert set(current) - set(base) == set(MEDIA_IDS)
    for mid, role in base.items():
        assert current[mid] == role
        assert static_role_for_id(mid) == role
    assert static_role_for_id("stt") == "speech-to-text"
    assert static_role_for_id("grok-voice-transcribe-1.0") == "speech-to-text"
    assert static_role_for_id("grok-voice-transcribe-2.0") == "speech-to-text"
    assert static_role_for_id("grok-voice-latest") == "voice"


def test_mr_c10_known_roles_and_bootstrap_unchanged() -> None:
    assert KNOWN_ROLES == ("chat", "image", "video", "voice", "speech-to-text")
    assert len(KNOWN_ROLES) == 5
    assert _ROLE_BOOTSTRAP == {
        "chat": "grok-4.7",
        "image": "grok-imagine-image-quality",
        "video": "grok-imagine-video-1.5",
        "voice": "grok-voice-latest",
        "speech-to-text": "grok-voice-transcribe-2.0",
    }
    assert normalize_role(None) == "chat"
    assert normalize_role("") == "chat"
    assert normalize_role("image") == "image"
    assert normalize_role("video") == "video"
    assert normalize_role("voice") == "voice"
    assert normalize_role("speech-to-text") == "speech-to-text"
    assert normalize_role("no-such-role") == "chat"


def test_mr_c11_price_for_matches_base_prefix_rows() -> None:
    table = default_price_table()
    quality = table.price_for("grok-imagine-image-quality")
    plain = table.price_for("grok-imagine-image")
    video = table.price_for("grok-imagine-video-1.5")
    assert quality is not None and plain is not None and video is not None
    assert table.price_for(IMAGE_LATEST) is quality
    assert table.price_for(IMAGE_QUALITY_SNAP) is quality
    assert quality.per_call_usd == 0.05
    assert table.price_for(IMAGE_MARCH) is plain
    assert plain.per_call_usd == 0.02
    assert table.price_for(VIDEO_STABLE) is video
    assert table.price_for(VIDEO_PREVIEW) is video
    assert video.per_second_usd == 0.08
    assert video.per_second_usd_by_resolution == {
        "480p": 0.08,
        "720p": 0.14,
        "1080p": 0.25,
    }
    for mid in MEDIA_IDS:
        assert mid not in table.models


def test_mr_c15_best_model_on_static_role_pools() -> None:
    rows = []
    for mid in MEDIA_IDS:
        info, _role = describe_listed_id(mid)
        rows.append(info)
    inject_catalog(rows)
    image_pool = [row for row in rows if static_role_for_id(row.id) == "image"]
    video_pool = [row for row in rows if static_role_for_id(row.id) == "video"]
    assert [row.id for row in image_pool] == list(IMAGE_IDS)
    assert [row.id for row in video_pool] == list(VIDEO_IDS)
    assert best_model(image_pool, role="image") == IMAGE_LATEST
    assert best_model(video_pool, role="video") == VIDEO_STABLE


def test_mr_c20_best_follows_unchanged_ranking() -> None:
    """Created dates do not add a latest rule. The alias is a listed or pinned id."""
    created = {
        IMAGE_LATEST: 100,
        IMAGE_MARCH: 200,
        IMAGE_QUALITY_SNAP: 300,
    }
    rows = [
        ModelInfo(id=mid, capabilities=["image"], created=created[mid]) for mid in IMAGE_IDS
    ]
    assert best_model(rows, role="image") == IMAGE_LATEST

    dated_only = [
        ModelInfo(id=IMAGE_MARCH, capabilities=["image"], created=200),
        ModelInfo(id=IMAGE_QUALITY_SNAP, capabilities=["image"], created=300),
    ]
    assert best_model(dated_only, role="image") == IMAGE_QUALITY_SNAP
    assert IMAGE_LATEST not in {row.id for row in dated_only}

    no_dates = [ModelInfo(id=mid, capabilities=["image"]) for mid in IMAGE_IDS]
    assert best_model(no_dates, role="image") == IMAGE_LATEST

    video_rows = [
        ModelInfo(id=VIDEO_STABLE, capabilities=["video"], created=10),
        ModelInfo(id=VIDEO_PREVIEW, capabilities=["video"], created=999),
    ]
    assert best_model(video_rows, role="video") == VIDEO_STABLE

    host = _host(IMAGE_IDS, created=created)
    try:
        client = _client(XaiClient, host)
        assert client.image_model == best_model(rows, role="image")
        assert client.image_model == IMAGE_LATEST
        pinned = _client(XaiClient, host, image_model=IMAGE_LATEST)
        pinned.generate_image("cat")
        assert _posted_models(host["records"], "/images/generations") == [IMAGE_LATEST]
        _assert_loopback_only(host["records"])
    finally:
        _stop(host)

    dated_created = {IMAGE_MARCH: 200, IMAGE_QUALITY_SNAP: 300}
    dated_host = _host((IMAGE_MARCH, IMAGE_QUALITY_SNAP), created=dated_created)
    try:
        client = _client(XaiClient, dated_host)
        assert client.image_model == IMAGE_QUALITY_SNAP
        assert client.image_model != IMAGE_LATEST
        _assert_loopback_only(dated_host["records"])
    finally:
        _stop(dated_host)


@pytest.mark.parametrize("cls", [XaiClient, AsyncXaiClient])
def test_mr_c12_c13_c14_five_id_host_resolves_image_and_video(cls) -> None:
    host = _host(MEDIA_IDS)
    try:
        client = _client(cls, host)

        async def _both() -> None:
            await client.generate_image("cat")
            await client.generate_video("clip", into=[], wait=False)

        if cls is AsyncXaiClient:
            asyncio.run(_both())
        else:
            client.generate_image("cat")
            client.generate_video("clip", into=[], wait=False)
        assert _posted_models(host["records"], "/images/generations") == [IMAGE_LATEST]
        assert _posted_models(host["records"], "/videos/generations") == [VIDEO_STABLE]
        _assert_loopback_only(host["records"])
    finally:
        _stop(host)


@pytest.mark.parametrize("cls", [XaiClient, AsyncXaiClient])
def test_mr_c16_image_ids_only_leave_other_roles_unavailable(cls) -> None:
    host = _host(IMAGE_IDS)
    try:
        client = _client(cls, host)
        _call(client, "generate_image", "cat")
        assert _posted_models(host["records"], "/images/generations") == [IMAGE_LATEST]
        for name, args, kwargs, role in (
            ("generate_video", ("clip",), {"into": [], "wait": False}, "video"),
            ("synthesize_speech", ("hi",), {}, "voice"),
            ("transcribe", (b"abc",), {}, "speech-to-text"),
        ):
            with pytest.raises(RoleUnavailableOnHost) as caught:
                _call(client, name, *args, **kwargs)
            assert caught.value.role == role
            assert caught.value.host == host["host"]
            assert role in str(caught.value)
            assert host["host"] in str(caught.value)
        assert _posted_models(host["records"], "/videos/generations") == []
        assert _posted_models(host["records"], "/tts") == []
        assert [row for row in host["records"] if row["path"].endswith("/stt")] == []
        _assert_loopback_only(host["records"])
    finally:
        _stop(host)


@pytest.mark.parametrize("cls", [XaiClient, AsyncXaiClient])
def test_mr_c17_video_ids_only_leave_image_unavailable(cls) -> None:
    host = _host(VIDEO_IDS)
    try:
        client = _client(cls, host)
        _call(client, "generate_video", "clip", into=[], wait=False)
        assert _posted_models(host["records"], "/videos/generations") == [VIDEO_STABLE]
        with pytest.raises(RoleUnavailableOnHost) as caught:
            _call(client, "generate_image", "cat")
        assert caught.value.role == "image"
        assert caught.value.host == host["host"]
        assert _posted_models(host["records"], "/images/generations") == []
        _assert_loopback_only(host["records"])
    finally:
        _stop(host)


@pytest.mark.parametrize("cls", [XaiClient, AsyncXaiClient])
def test_mr_c18_voice_and_stt_stay_unavailable_on_media_host(cls) -> None:
    host = _host(MEDIA_IDS)
    try:
        client = _client(cls, host)
        expected = {
            "synthesize_speech": ("voice", ("hi",), {}),
            "open_tts_session": ("voice", (), {}),
            "open_realtime_session": ("voice", (), {}),
            "transcribe": ("speech-to-text", (b"abc",), {}),
            "open_stt_session": ("speech-to-text", (), {}),
        }
        for name, (role, args, kwargs) in expected.items():
            with pytest.raises(RoleUnavailableOnHost) as caught:
                _call(client, name, *args, **kwargs)
            err = caught.value
            assert err.role == role
            assert err.host == host["host"]
            assert role in str(err)
            assert host["host"] in str(err)
            for mid in MEDIA_IDS:
                assert mid not in str(err)
        assert _posted_models(host["records"], "/tts") == []
        assert [row for row in host["records"] if row["path"].endswith("/stt")] == []
        _assert_loopback_only(host["records"])
    finally:
        _stop(host)


@pytest.mark.parametrize("cls", [XaiClient, AsyncXaiClient])
def test_mr_c19_chat_pool_excludes_the_media_ids(cls) -> None:
    host = _host(MEDIA_IDS)
    try:
        client = _client(cls, host)
        with pytest.raises(RoleUnavailableOnHost) as caught:
            _ = client.model
        assert caught.value.role == "chat"
        assert caught.value.host == host["host"]
        loaded = client._load_regional_models()
        assert loaded is not None
        assert [role for _info, role in loaded].count("chat") == 0
        assert {info.id for info, _role in loaded} == set(MEDIA_IDS)
        chats = [
            row
            for row in host["records"]
            if row["path"].endswith("/chat/completions")
        ]
        assert chats == []
        _assert_loopback_only(host["records"])
    finally:
        _stop(host)
