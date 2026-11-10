"""CUT-2026-11-06-xk-retired-quality-best.

RQB-AC-1a: the seven public image ids resolve, and retired ids do not win
image best or economy. RQB-AC-1b: price_for(quality-latest) does not inherit
the grok-imagine-image row. Offline only: no API key, catalog SDK fetch and
public price fetch raise, and any non-loopback socket connect fails.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
from pathlib import Path
from typing import Any

import pytest

from xaikit import AsyncXaiClient, XaiClient
from xaikit.catalog import (
    best_model,
    cheapest_model,
    economy_model,
    resolve_model,
    resolve_model_selection,
    static_role_for_id,
)
from xaikit.pricing import default_price_table
from xaikit.provider import MockChatProvider
from xaikit.types import ModelInfo


def _load_regional_endpoint():
    """Load the existing loopback host helpers without editing that file."""
    path = Path(__file__).resolve().with_name("test_regional_endpoint.py")
    spec = importlib.util.spec_from_file_location(
        "xaikit_regional_endpoint_fixture_rqb", path
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
PLAIN = "grok-imagine-image"
IMAGE_2 = "grok-imagine-image-2.0"
MARCH = "grok-imagine-image-2026-03-02"
PRO = "grok-imagine-image-pro"
QUALITY = "grok-imagine-image-quality"
QUALITY_SNAP = "grok-imagine-image-quality-20260403"
QUALITY_LATEST = "grok-imagine-image-quality-latest"
SEVEN = (PLAIN, IMAGE_2, MARCH, PRO, QUALITY, QUALITY_SNAP, QUALITY_LATEST)
SIX = tuple(mid for mid in SEVEN if mid != QUALITY_LATEST)
RETIRED_FAMILIES = (QUALITY, PRO)


def _is_retired(model_id: str | None) -> bool:
    key = (model_id or "").strip()
    return any(key == f or key.startswith(f + "-") for f in RETIRED_FAMILIES)


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch):
    for name in ("XAI_API_KEY", "XAI_BASE_URL", "XAI_MANAGEMENT_KEY", "XAITKIT_LIVE"):
        monkeypatch.delenv(name, raising=False)

    def _no_network(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("network fetch attempted in an offline test")

    monkeypatch.setattr("xaikit.pricing.fetch_public_price_payload", _no_network)
    monkeypatch.setattr("xaikit.catalog.fetch_models_from_sdk", _no_network)
    _apply_loopback_only(monkeypatch)


# Six created variants. Each runs with and without the -latest alias. With no
# alias, the "latest newest" variant makes the undated quality id newest.
def _created(variant: str, ids: tuple[str, ...]) -> dict[str, int]:
    newest = {
        "tied": None,
        "march_newest": MARCH,
        "quality_snap_newest": QUALITY_SNAP,
        "image_2_newest": IMAGE_2,
        "pro_newest": PRO,
        "latest_newest": QUALITY_LATEST if QUALITY_LATEST in ids else QUALITY,
    }[variant]
    return {mid: (900 if mid == newest else 10) for mid in ids}


VARIANTS = (
    "tied",
    "march_newest",
    "quality_snap_newest",
    "image_2_newest",
    "pro_newest",
    "latest_newest",
)
POOLS = {"with_latest": SEVEN, "without_latest": SIX}


def _rows(ids: tuple[str, ...], created: dict[str, int] | None) -> list[ModelInfo]:
    return [
        ModelInfo(
            id=mid,
            capabilities=["image"],
            created=None if created is None else created[mid],
        )
        for mid in ids
    ]


@pytest.mark.parametrize("pool", sorted(POOLS))
@pytest.mark.parametrize("variant", VARIANTS)
def test_rqb_c01_best_is_not_retired_on_the_seven_ids(variant: str, pool: str) -> None:
    """RQB-C01. Best is 2.0 in every created variant, with and without -latest."""
    ids = POOLS[pool]
    rows = _rows(ids, _created(variant, ids))
    got = best_model(rows, role="image")
    assert not _is_retired(got), got
    assert got == IMAGE_2
    assert resolve_model(intent="best", role="image", catalog=rows) == IMAGE_2
    selected = resolve_model_selection(intent="best", role="image", catalog=rows)
    assert selected.model_id == IMAGE_2


@pytest.mark.parametrize("pool", sorted(POOLS))
@pytest.mark.parametrize("variant", VARIANTS)
def test_rqb_c02_economy_is_base_image_not_best(variant: str, pool: str) -> None:
    """RQB-C02. Economy is grok-imagine-image, not retired, and not best."""
    ids = POOLS[pool]
    rows = _rows(ids, _created(variant, ids))
    got = economy_model(rows, role="image")
    assert not _is_retired(got), got
    assert got == PLAIN
    assert got != best_model(rows, role="image")
    assert resolve_model(intent="economy", role="image", catalog=rows) == PLAIN


def test_rqb_c02_sdk_token_priced_retired_rows_do_not_take_economy() -> None:
    """RQB-C02. A retired row with SDK token units is not a cheaper economy band.

    Unpriced retired ids fall back to input_per_million for ranking, so this
    checks that economy itself skips them, not only the price table.
    """
    rows = [
        ModelInfo(id=IMAGE_2, capabilities=["image"], created=10),
        ModelInfo(
            id=QUALITY_LATEST, capabilities=["image"], created=10, input_per_million=0.001
        ),
    ]
    assert economy_model(rows, role="image") == IMAGE_2
    assert best_model(rows, role="image") == IMAGE_2
    seven = [
        ModelInfo(
            id=mid,
            capabilities=["image"],
            created=10,
            input_per_million=0.001 if _is_retired(mid) else None,
        )
        for mid in SEVEN
    ]
    assert economy_model(seven, role="image") == PLAIN
    assert best_model(seven, role="image") == IMAGE_2


def _host(ids: tuple[str, ...], created: dict[str, int]) -> dict[str, Any]:
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
        "provider": MockChatProvider("ok"),
    }
    params.update(kwargs)
    return cls(**params)


def _call(client: Any, name: str, *args: Any, **kwargs: Any) -> Any:
    out = getattr(client, name)(*args, **kwargs)
    if asyncio.iscoroutine(out):
        return asyncio.run(out)
    return out


def _image_posts(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in records
        if row["method"] == "POST" and row["path"].endswith("/images/generations")
    ]


def _assert_loopback_only(records: list[dict[str, Any]]) -> None:
    for row in records:
        assert "api.x.ai" not in row["path"]


@pytest.mark.parametrize("cls", [XaiClient, AsyncXaiClient])
@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("intent", ["best", "economy"])
def test_rqb_c03_client_unpinned_image_intent_skips_retired(
    cls: type, variant: str, intent: str
) -> None:
    """RQB-C03. Sync and async clients on a non-default host listing the seven ids."""
    created = _created(variant, SEVEN)
    host = _host(SEVEN, created)
    try:
        client = _client(cls, host, intent=intent)
        assert client.base_url.startswith("http://127.0.0.1")
        assert not _is_retired(client.image_model), client.image_model
        _call(client, "generate_image", "cat")
        posts = _image_posts(host["records"])
        assert len(posts) == 1
        posted = json.loads(posts[0]["body"].decode())["model"]
        assert not _is_retired(posted), posted
        assert posted == client.image_model
        _assert_loopback_only(host["records"])
    finally:
        _stop(host)


@pytest.mark.parametrize("model_id", [QUALITY_LATEST, QUALITY, PRO, QUALITY_SNAP])
def test_rqb_c04_retired_ids_do_not_inherit_the_base_row(model_id: str) -> None:
    """RQB-C04. No prefix row for retired ids (RQBQ-3: quality-20260403 too)."""
    table = default_price_table()
    base_row = table.price_for(PLAIN)
    assert base_row is not None and base_row.per_call_usd == 0.02
    got = table.price_for(model_id)
    assert got is not base_row
    assert got is None
    assert model_id not in table.models


@pytest.mark.parametrize("cls", [XaiClient, AsyncXaiClient])
@pytest.mark.parametrize("pin", [QUALITY_LATEST, PRO])
def test_rqb_c05_retired_pins_are_sent_unchanged(
    cls: type, pin: str, caplog: pytest.LogCaptureFixture
) -> None:
    """RQB-C05. image_model= and per-call model= pins go out exactly, no warning."""
    created = _created("tied", SEVEN)
    host = _host(SEVEN, created)
    try:
        with caplog.at_level(logging.WARNING, logger="xaikit"):
            pinned = _client(cls, host, intent="best", image_model=pin)
            assert pinned.image_model == pin
            _call(pinned, "generate_image", "cat")
            unpinned = _client(cls, host, intent="best")
            _call(unpinned, "generate_image", "cat", model=pin)
        posts = _image_posts(host["records"])
        assert [json.loads(row["body"].decode())["model"] for row in posts] == [pin, pin]
        assert [r for r in caplog.records if pin in r.getMessage()] == []
        _assert_loopback_only(host["records"])
    finally:
        _stop(host)


def test_rqb_c06_best_latest_distinction_kept_for_non_retired_families() -> None:
    """RQB-C06. -latest still beats a newer snapshot; a snapshot trails its plain id."""
    alias = [
        ModelInfo(id="grok-imagine-image-2.0-latest", capabilities=["image"], created=10),
        ModelInfo(id="grok-imagine-image-2.0-20261001", capabilities=["image"], created=900),
    ]
    assert best_model(alias, role="image") == "grok-imagine-image-2.0-latest"
    plain = [
        ModelInfo(id=PLAIN, capabilities=["image"], created=10),
        ModelInfo(id=MARCH, capabilities=["image"], created=900),
    ]
    assert best_model(plain, role="image") == PLAIN
    assert economy_model(plain, role="image") == PLAIN
    chat = [
        ModelInfo(id="grok-4.7-latest", capabilities=["chat"], created=10),
        ModelInfo(id="grok-4.7-20261001", capabilities=["chat"], created=900),
    ]
    assert best_model(chat, role="chat") == "grok-4.7-latest"
    video = [
        ModelInfo(id="grok-imagine-video-1.5", capabilities=["video"], created=10),
        ModelInfo(id="grok-imagine-video-1.5-2026-05-30", capabilities=["video"], created=999),
        ModelInfo(id="grok-imagine-video-1.5-preview", capabilities=["video"], created=999),
        ModelInfo(id="grok-imagine-video", capabilities=["video"], created=1),
    ]
    assert best_model(video, role="video") == "grok-imagine-video-1.5"
    assert economy_model(video, role="video") == "grok-imagine-video"
    mixed_chat = [
        ModelInfo(id="grok-4.7", capabilities=["chat"], created=10, input_per_million=2.0),
        ModelInfo(id="grok-4.3", capabilities=["chat"], created=5, input_per_million=1.25),
    ]
    assert best_model(mixed_chat, role="chat") == "grok-4.7"
    assert economy_model(mixed_chat, role="chat") == "grok-4.3"


def test_rqb_c07_static_roles_unchanged() -> None:
    """RQB-C07. Retired ids keep their base static role; unknown ids stay chat."""
    for mid in (
        QUALITY_LATEST,
        QUALITY_SNAP,
        "grok-imagine-image-quality-2026-04-03",
        "grok-imagine-image-quality-20990101",
        "grok-imagine-image-pro-2099-01-01",
        "grok-imagine-image-pro-20260501",
    ):
        assert static_role_for_id(mid) == "image", mid
    # Base behavior, unchanged by this cut (plan question RQB-PQ-1): the
    # undated quality and pro ids are not exact role-map keys.
    assert static_role_for_id(QUALITY) == "chat"
    assert static_role_for_id(PRO) == "chat"
    assert static_role_for_id("grok-unknown-model") == "chat"
    assert static_role_for_id("grok-imagine-image-professional") == "chat"


def test_rqb_c08_non_retired_prices_and_cheapest_unchanged() -> None:
    """RQB-C08. Shipped rows and the base-family prefix rows are unchanged."""
    table = default_price_table()
    plain = table.price_for(PLAIN)
    assert plain is table.models[PLAIN]
    assert plain.per_call_usd == 0.02
    two = table.price_for(IMAGE_2)
    assert two is table.models[IMAGE_2]
    assert two.per_call_usd == 0.04
    assert two.image_tiers is not None and len(two.image_tiers) == 6
    assert two.media_input_per_image_usd == 0.01
    assert table.price_for(MARCH) is plain
    assert table.price_for("grok-imagine-image-2099-01-01") is plain
    # Near prefixes that are not a retired family keep the base row.
    for near in (
        "grok-imagine-image-professional",
        "grok-imagine-image-qualityplus",
        "grok-imagine-image-3.0-lite",
    ):
        assert table.price_for(near) is plain, near
    assert table.price_for("grok-imagine-image-2.0-20261001") is two
    for variant in VARIANTS:
        for ids in POOLS.values():
            rows = _rows(ids, _created(variant, ids))
            assert cheapest_model(rows, role="image") == PLAIN


@pytest.mark.parametrize(
    "ids, want",
    [
        ((QUALITY_LATEST,), QUALITY_LATEST),
        ((QUALITY_SNAP,), QUALITY_SNAP),
        ((QUALITY, PRO, QUALITY_LATEST), PRO),
    ],
)
def test_rqb_c09_all_retired_pool_falls_back_to_normal_ranking(
    ids: tuple[str, ...], want: str
) -> None:
    """RQB-C09 per RQBQ-4(a): an all-retired pool still ranks; no None, no new error."""
    created = {QUALITY: 10, PRO: 20, QUALITY_LATEST: 5, QUALITY_SNAP: 5}
    rows = _rows(ids, {mid: created[mid] for mid in ids})
    assert best_model(rows, role="image") == want
    assert economy_model(rows, role="image") == want
    assert cheapest_model(rows, role="image") == want


@pytest.mark.parametrize("cls", [XaiClient, AsyncXaiClient])
def test_rqb_c09_all_retired_host_still_resolves(cls: type) -> None:
    """RQB-C09 per RQBQ-4(a): a host listing only quality-latest still resolves it."""
    host = _host((QUALITY_LATEST,), {QUALITY_LATEST: 10})
    try:
        client = _client(cls, host, intent="best")
        assert client.image_model == QUALITY_LATEST
        _call(client, "generate_image", "cat")
        posts = _image_posts(host["records"])
        assert [json.loads(row["body"].decode())["model"] for row in posts] == [
            QUALITY_LATEST
        ]
        _assert_loopback_only(host["records"])
    finally:
        _stop(host)
