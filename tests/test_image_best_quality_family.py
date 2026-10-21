"""CUT-2026-10-21-xk-image-best-quality-family.

IB-AC-1. Offline only: inject_catalog, and the loopback host fixture from
test_regional_endpoint. No live calls and no API key.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from xaikit import AsyncXaiClient, XaiClient
from xaikit.catalog import (
    _is_snapshot_id,
    _snapshot_family,
    best_model,
    cheapest_model,
    economy_model,
    resolve_model,
)
from xaikit.pricing import default_price_table
from xaikit.provider import MockChatProvider
from xaikit.types import ModelInfo


def _load_regional_endpoint():
    """Load the existing loopback host helpers without editing that file."""
    path = Path(__file__).resolve().with_name("test_regional_endpoint.py")
    spec = importlib.util.spec_from_file_location(
        "xaikit_regional_endpoint_fixture_ib", path
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
IMAGE_LATEST = "grok-imagine-image-quality-latest"
IMAGE_MARCH = "grok-imagine-image-2026-03-02"
IMAGE_QUALITY_SNAP = "grok-imagine-image-quality-20260403"
IMAGE_QUALITY = "grok-imagine-image-quality"
IMAGE_PLAIN = "grok-imagine-image"
IMAGE_DATED_2099 = "grok-imagine-image-2099-01-01"
IMAGE_2 = "grok-imagine-image-2.0"
VIDEO_STABLE = "grok-imagine-video-1.5-2026-05-30"
VIDEO_PREVIEW = "grok-imagine-video-1.5-preview"
IMAGE_IDS = (IMAGE_LATEST, IMAGE_MARCH, IMAGE_QUALITY_SNAP)
C20_CREATED = {
    IMAGE_LATEST: 100,
    IMAGE_MARCH: 200,
    IMAGE_QUALITY_SNAP: 300,
}
PUBLIC_IMAGE_IDS = (
    IMAGE_PLAIN,
    IMAGE_2,
    IMAGE_MARCH,
    "grok-imagine-image-pro",
    IMAGE_QUALITY,
    IMAGE_QUALITY_SNAP,
    IMAGE_LATEST,
)


@pytest.fixture(autouse=True)
def _no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XAI_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def _loopback_only(monkeypatch: pytest.MonkeyPatch):
    """Same socket guard as tests/test_regional_endpoint.py."""
    _apply_loopback_only(monkeypatch)


def _rows(
    ids: tuple[str, ...] | list[str],
    created: dict[str, int] | None,
    role: str,
) -> list[ModelInfo]:
    if created is None:
        return [ModelInfo(id=mid, capabilities=[role]) for mid in ids]
    return [
        ModelInfo(id=mid, capabilities=[role], created=created[mid]) for mid in ids
    ]


def _c20_rows() -> list[ModelInfo]:
    return _rows(IMAGE_IDS, C20_CREATED, "image")


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


def _assert_loopback_only(records: list[dict[str, Any]]) -> None:
    for row in records:
        assert "api.x.ai" not in row["path"]
        assert KEY not in row["path"]


def _image_posts(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in records
        if row["method"] == "POST" and row["path"].endswith("/images/generations")
    ]


def test_ib_c01_c02_c03_c20_rows_resolve_to_quality_latest() -> None:
    """IB-C01, IB-C02, IB-C03. Created does not let March win any image intent."""
    rows = _c20_rows()
    for picker in (best_model, economy_model, cheapest_model):
        assert picker(rows, role="image") == IMAGE_LATEST
        assert picker(rows, role="image") != IMAGE_MARCH
    for intent in ("best", "economy", "cheapest"):
        assert resolve_model(intent=intent, role="image", catalog=rows) == IMAGE_LATEST


def test_ib_c11_same_ids_without_created_resolve_to_quality_latest() -> None:
    """IB-C11. With no created stamps, every intent is still the quality alias."""
    rows = _rows(IMAGE_IDS, None, "image")
    assert all(row.created is None for row in rows)
    assert best_model(rows, role="image") == IMAGE_LATEST
    assert economy_model(rows, role="image") == IMAGE_LATEST
    assert cheapest_model(rows, role="image") == IMAGE_LATEST


def test_ib_c09_c10_quality_plain_stays_ahead_of_cheaper_dated_only() -> None:
    """IB-C09, IB-C10. The rule is the family, not one excluded snapshot id."""
    rows = [
        ModelInfo(id=IMAGE_QUALITY, capabilities=["image"], created=1),
        ModelInfo(id=IMAGE_DATED_2099, capabilities=["image"], created=9),
    ]
    assert _snapshot_family(IMAGE_DATED_2099) == IMAGE_PLAIN
    assert _snapshot_family(IMAGE_DATED_2099) != _snapshot_family(IMAGE_QUALITY)
    for picker in (best_model, economy_model, cheapest_model):
        assert picker(rows, role="image") == IMAGE_QUALITY
        assert picker(rows, role="image") != IMAGE_DATED_2099


def test_ib_c12_dated_only_pool_keeps_normal_ranking() -> None:
    """IB-C12. No plain or -latest family: newest created snapshot still wins best."""
    rows = [
        ModelInfo(id=IMAGE_MARCH, capabilities=["image"], created=200),
        ModelInfo(id=IMAGE_QUALITY_SNAP, capabilities=["image"], created=300),
    ]
    assert best_model(rows, role="image") == IMAGE_QUALITY_SNAP
    assert economy_model(rows, role="image") == IMAGE_MARCH
    assert cheapest_model(rows, role="image") == IMAGE_MARCH


def test_ib_guard_costlier_dated_only_still_beats_older_plain() -> None:
    """A dated-only family that is not cheaper still beats an older plain id."""
    rows = [
        ModelInfo(id=IMAGE_PLAIN, capabilities=["image"], created=100),
        ModelInfo(id=IMAGE_QUALITY_SNAP, capabilities=["image"], created=200),
    ]
    assert best_model(rows, role="image") == IMAGE_QUALITY_SNAP
    assert economy_model(rows, role="image") == IMAGE_PLAIN
    assert cheapest_model(rows, role="image") == IMAGE_PLAIN


def test_ib_c15_public_lineup_unchanged_when_march_created_is_newest() -> None:
    """IB-C15. Plain base family stays economy and cheapest on the public ids."""
    created = {mid: (900 if mid == IMAGE_MARCH else 10) for mid in PUBLIC_IMAGE_IDS}
    rows = _rows(PUBLIC_IMAGE_IDS, created, "image")
    assert best_model(rows, role="image") == IMAGE_LATEST
    assert economy_model(rows, role="image") == IMAGE_PLAIN
    assert cheapest_model(rows, role="image") == IMAGE_PLAIN
    assert economy_model(rows, role="image") != IMAGE_MARCH


def test_ib_c16_video_and_chat_ranking_unchanged() -> None:
    """IB-C16. Video stable snapshot still beats preview. Chat version still wins."""
    video = [
        ModelInfo(id=VIDEO_STABLE, capabilities=["video"], created=10),
        ModelInfo(id=VIDEO_PREVIEW, capabilities=["video"], created=999),
    ]
    assert best_model(video, role="video") == VIDEO_STABLE
    chat = [
        ModelInfo(id="grok-4.7", capabilities=["chat"], created=10),
        ModelInfo(id="grok-4.6", capabilities=["chat"], created=900),
    ]
    assert best_model(chat, role="chat") == "grok-4.7"


def test_ib_guard_created_still_beats_latest_flag_for_image_and_voice() -> None:
    """Created stays ahead of the -latest flag when both families are anchored."""
    image = [
        ModelInfo(id=IMAGE_LATEST, capabilities=["image"], created=100),
        ModelInfo(id=IMAGE_2, capabilities=["image"], created=200),
    ]
    assert best_model(image, role="image") == IMAGE_2
    voice = [
        ModelInfo(id="grok-voice-latest", capabilities=["voice"], created=100),
        ModelInfo(id="grok-voice-think-fast-2.0", capabilities=["voice"], created=200),
    ]
    assert best_model(voice, role="voice") == "grok-voice-think-fast-2.0"


def test_ib_c17_prices_of_the_three_ids_stay_on_the_shipped_rows() -> None:
    """IB-C17. quality alias and quality snapshot are 0.05. March is 0.02."""
    table = default_price_table()
    latest = table.price_for(IMAGE_LATEST)
    march = table.price_for(IMAGE_MARCH)
    snap = table.price_for(IMAGE_QUALITY_SNAP)
    assert latest is not None and march is not None and snap is not None
    assert latest.per_call_usd == 0.05
    assert snap.per_call_usd == 0.05
    assert march.per_call_usd == 0.02
    assert table.price_for(IMAGE_LATEST) is table.price_for(IMAGE_QUALITY)
    assert table.price_for(IMAGE_MARCH) is table.price_for(IMAGE_PLAIN)


def test_ib_c18_march_stays_in_the_base_image_family() -> None:
    """IB-C18. March is not a snapshot of the quality family."""
    assert _snapshot_family(IMAGE_LATEST) == IMAGE_QUALITY
    assert _snapshot_family(IMAGE_QUALITY_SNAP) == IMAGE_QUALITY
    assert _snapshot_family(IMAGE_MARCH) == IMAGE_PLAIN
    assert _snapshot_family(IMAGE_DATED_2099) == IMAGE_PLAIN
    assert _is_snapshot_id(IMAGE_MARCH) is True
    assert _is_snapshot_id(IMAGE_QUALITY_SNAP) is True
    assert _is_snapshot_id(IMAGE_LATEST) is False
    assert _is_snapshot_id(IMAGE_QUALITY) is False


@pytest.mark.parametrize("cls", [XaiClient, AsyncXaiClient])
@pytest.mark.parametrize("intent", ["best", "economy", "cheapest"])
def test_ib_c04_c05_c06_host_intents_resolve_to_quality_latest(cls, intent: str) -> None:
    """IB-C04, IB-C05, IB-C06. Sync and async clients on the C20 host."""
    host = _host(IMAGE_IDS, created=C20_CREATED)
    try:
        client = _client(cls, host, intent=intent)
        assert client.base_url.startswith("http://127.0.0.1")
        assert client.image_model == IMAGE_LATEST
        assert client.image_model != IMAGE_MARCH
        _assert_loopback_only(host["records"])
    finally:
        _stop(host)


@pytest.mark.parametrize("cls", [XaiClient, AsyncXaiClient])
def test_ib_c07_c08_unpinned_generate_image_posts_quality_alias(cls) -> None:
    """IB-C07, IB-C08. One loopback POST, model is the quality alias."""
    host = _host(IMAGE_IDS, created=C20_CREATED)
    try:
        client = _client(cls, host, intent="best")
        _call(client, "generate_image", "cat")
        posts = _image_posts(host["records"])
        assert len(posts) == 1
        assert [row for row in host["records"] if row["method"] == "POST"] == posts
        body = json.loads(posts[0]["body"].decode())
        assert body["model"] == IMAGE_LATEST
        _assert_loopback_only(host["records"])
    finally:
        _stop(host)


@pytest.mark.parametrize("cls", [XaiClient, AsyncXaiClient])
def test_ib_c13_pinned_march_posts_march(cls) -> None:
    """IB-C13. An explicit image_model pin wins over the quality alias."""
    host = _host(IMAGE_IDS, created=C20_CREATED)
    try:
        client = _client(cls, host, intent="best", image_model=IMAGE_MARCH)
        assert client.image_model == IMAGE_MARCH
        _call(client, "generate_image", "cat")
        posts = _image_posts(host["records"])
        assert len(posts) == 1
        assert json.loads(posts[0]["body"].decode())["model"] == IMAGE_MARCH
        _assert_loopback_only(host["records"])
    finally:
        _stop(host)


@pytest.mark.parametrize("cls", [XaiClient, AsyncXaiClient])
def test_ib_c14_pinned_quality_latest_posts_quality_alias(cls) -> None:
    """IB-C14. A pin of the quality alias posts that id."""
    host = _host(IMAGE_IDS, created=C20_CREATED)
    try:
        client = _client(cls, host, intent="best", image_model=IMAGE_LATEST)
        _call(client, "generate_image", "cat")
        posts = _image_posts(host["records"])
        assert len(posts) == 1
        assert json.loads(posts[0]["body"].decode())["model"] == IMAGE_LATEST
        _assert_loopback_only(host["records"])
    finally:
        _stop(host)
