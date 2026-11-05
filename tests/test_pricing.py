"""Price table provenance, overlay, and no-invented-USD rows."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from xaikit import (
    PRICE_TABLE_FETCHED,
    PRICE_TABLE_SOURCE_URL,
    default_price_table,
    load_price_table,
    save_price_table_template,
)


def test_default_price_table_records_source_and_fetch_date() -> None:
    table = default_price_table()
    assert table.source_url == PRICE_TABLE_SOURCE_URL
    assert table.fetched == PRICE_TABLE_FETCHED
    assert table.currency == "USD"
    assert PRICE_TABLE_SOURCE_URL.startswith("https://docs.x.ai/")


def test_save_price_table_template_includes_provenance(tmp_path) -> None:
    path = tmp_path / "prices.json"
    out = save_price_table_template(path)
    assert out == path
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["source_url"] == PRICE_TABLE_SOURCE_URL
    assert raw["fetched"] == PRICE_TABLE_FETCHED
    assert "grok-4.7" in raw["models"]
    assert "grok-4.6" in raw["models"]


def test_load_price_table_overlay_keeps_or_overrides_fetched(tmp_path) -> None:
    path = tmp_path / "overlay.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "fetched": "2026-09-01",
                "models": {"grok-4.6": {"input_per_million": 9.0, "output_per_million": 9.0}},
            }
        ),
        encoding="utf-8",
    )
    table = load_price_table(path)
    assert table.fetched == "2026-09-01"
    assert table.source_url == PRICE_TABLE_SOURCE_URL
    assert table.price_for("grok-4.6").input_per_million == 9.0
    assert table.price_for("grok-4.3").input_per_million == 1.25


def test_missing_modality_rates_do_not_invent_usd() -> None:
    table = default_price_table()
    assert "embed" not in table.models
    assert "collections" not in table.models
    assert "tokenize" not in table.models
    # No tokens / duration / per-call → None. Unknown slugs do not fall
    # back to the chat ``default`` row (``grok-4.8`` must not bill as ``grok-4``).
    assert table.estimate_usd("not-a-public-sku") is None
    assert table.price_for("grok-4.8") is None
    assert table.estimate_usd(
        "grok-4.8", prompt_tokens=1_000_000, completion_tokens=0
    ) is None
    latest = table.price_for("grok-4.7-latest")
    assert latest is not None
    assert latest.input_per_million == 2.0
    assert latest.output_per_million == 6.0


def test_grok_imagine_image_2_0_per_call_usd_is_public_rate() -> None:
    price = default_price_table().price_for("grok-imagine-image-2.0")
    assert price is not None
    # IPT-C06: image-2.0 base pin is the 1K Low rate.
    assert price.per_call_usd == 0.04


def _watch_image_per_call(model_id: str) -> float:
    watch = Path(__file__).resolve().parents[1] / "scripts" / "data" / "xai_public_prices.json"
    payload = json.loads(watch.read_text(encoding="utf-8"))
    return float(payload["models"][model_id]["per_call_usd"])


@pytest.mark.parametrize(
    "model_id",
    (
        "grok-imagine-image",
        "grok-imagine-image-2.0",
    ),
)
def test_shipped_ranked_image_rates_match_public_watch(model_id: str) -> None:
    shipped = default_price_table().price_for(model_id)
    assert shipped is not None
    assert shipped.per_call_usd == _watch_image_per_call(model_id)


def _shipped_image_ids_with_watch_per_call() -> tuple[str, ...]:
    payload = json.loads(
        (Path(__file__).resolve().parents[1] / "scripts" / "data" / "xai_public_prices.json").read_text(
            encoding="utf-8"
        )
    )
    watch_models = payload.get("models") or {}
    ids: list[str] = []
    for model_id, price in default_price_table().models.items():
        if not str(model_id).startswith("grok-imagine-image"):
            continue
        if price.per_call_usd is None:
            continue
        row = watch_models.get(model_id)
        if isinstance(row, dict) and row.get("per_call_usd") is not None:
            ids.append(model_id)
    return tuple(ids)


@pytest.mark.parametrize("model_id", _shipped_image_ids_with_watch_per_call())
def test_every_shipped_image_per_call_matches_watch_file(model_id: str) -> None:
    shipped_ids = {
        model_id
        for model_id, price in default_price_table().models.items()
        if str(model_id).startswith("grok-imagine-image") and price.per_call_usd is not None
    }
    assert shipped_ids <= set(_shipped_image_ids_with_watch_per_call())
    shipped = default_price_table().models[model_id].per_call_usd
    assert shipped == _watch_image_per_call(model_id)


def test_image_2_0_base_rate_is_0_04() -> None:
    """IPT-C01: no tier args bills the 1K Low base, and the watch file agrees."""
    table = default_price_table()
    assert table.estimate_usd("grok-imagine-image-2.0") == 0.04
    price = table.price_for("grok-imagine-image-2.0")
    assert price is not None
    assert price.per_call_usd == 0.04
    assert _watch_image_per_call("grok-imagine-image-2.0") == 0.04
    low_1k = [
        tier
        for tier in (price.image_tiers or [])
        if tier.resolution == "1k" and tier.quality == "low"
    ]
    assert len(low_1k) == 1
    assert low_1k[0].per_call_usd == 0.04


def test_image_tier_match_and_base_fallback() -> None:
    """IPT-C02: exact resolution and quality match, otherwise the base rate."""
    from xaikit.pricing import ImagePriceTier, ModelPrice, PriceTable

    # synthetic test rate
    table = PriceTable(
        models={
            "synthetic-image": ModelPrice(
                input_per_million=0.0,
                output_per_million=0.0,
                per_call_usd=0.11,
                image_tiers=[
                    ImagePriceTier(resolution="2k", quality="high", per_call_usd=0.33),
                ],
            )
        }
    )
    assert table.estimate_usd("synthetic-image", resolution="2k", quality="high") == 0.33
    assert table.estimate_usd("synthetic-image", resolution=" 2K ", quality="High") == 0.33
    assert table.estimate_usd("synthetic-image", resolution="1k", quality="high") == 0.11
    assert table.estimate_usd("synthetic-image", resolution="2k", quality="low") == 0.11
    assert table.estimate_usd("synthetic-image") == 0.11
    assert (
        table.estimate_usd("synthetic-image", resolution="1024x1024", quality="high")
        == 0.11
    )

    # synthetic test rate: quality None is an exact key, not a wildcard
    plain = PriceTable(
        models={
            "synthetic-plain": ModelPrice(
                input_per_million=0.0,
                output_per_million=0.0,
                per_call_usd=0.11,
                image_tiers=[
                    ImagePriceTier(resolution="2k", quality=None, per_call_usd=0.33),
                ],
            )
        }
    )
    assert plain.estimate_usd("synthetic-plain", resolution="2k") == 0.33
    assert plain.estimate_usd("synthetic-plain", resolution="2k", quality=None) == 0.33
    assert plain.estimate_usd("synthetic-plain", resolution="2k", quality="low") == 0.11
    assert plain.estimate_usd("synthetic-plain", resolution="2k", quality="") == 0.11

    shipped = default_price_table()
    shipped_rows = {
        "grok-imagine-image-2.0": (
            ("1k", "low", 0.04),
            ("1.5k", "low", 0.05),
            ("2k", "low", 0.06),
            ("1k", "medium", 0.06),
            ("1.5k", "medium", 0.07),
            ("2k", "medium", 0.08),
        ),
        "grok-imagine-image": (
            ("1k", None, 0.02),
            ("2k", None, 0.02),
        ),
    }
    for model_id, rows in shipped_rows.items():
        for resolution, quality, rate in rows:
            assert (
                shipped.estimate_usd(model_id, resolution=resolution, quality=quality)
                == rate
            )
    assert (
        shipped.estimate_usd(
            "grok-imagine-image-2.0", resolution=" 1.5K ", quality=" Medium "
        )
        == 0.07
    )
    assert shipped.estimate_usd("grok-imagine-image", resolution="2K") == 0.02
    assert (
        shipped.estimate_usd("grok-imagine-image", resolution="1k", quality="low")
        == 0.02
    )


def test_image_media_input_added_per_input_image() -> None:
    """IPT-C03: media input is added per input image and does not replace output."""
    from xaikit.pricing import ImagePriceTier, ModelPrice, PriceTable

    # synthetic test rate
    table = PriceTable(
        models={
            "synthetic-image": ModelPrice(
                input_per_million=0.0,
                output_per_million=0.0,
                per_call_usd=0.11,
                media_input_per_image_usd=0.007,
                image_tiers=[
                    ImagePriceTier(resolution="2k", quality="high", per_call_usd=0.33),
                ],
            )
        }
    )
    assert table.estimate_usd("synthetic-image", input_images=1) == 0.117
    assert table.estimate_usd("synthetic-image", input_images=3) == 0.131
    assert table.estimate_usd("synthetic-image", input_images=0) == 0.11
    assert table.estimate_usd("synthetic-image", input_images=None) == 0.11
    assert table.estimate_usd("synthetic-image", input_images=-4) == 0.11
    assert (
        table.estimate_usd(
            "synthetic-image", resolution="2k", quality="high", input_images=2
        )
        == 0.344
    )
    with pytest.raises(TypeError):
        table.estimate_usd("synthetic-image", 1)

    shipped = default_price_table()
    assert shipped.estimate_usd("grok-imagine-image-2.0", input_images=2) == 0.06
    assert shipped.estimate_usd("grok-imagine-image", input_images=1) == 0.022


# Non-null rates at 547e99b. image-2.0 per_call_usd is the shipped 1K Low base.
_BASE_RATE_SNAPSHOT: dict[str, dict[str, object]] = {
    "default": {"input_per_million": 3.0, "output_per_million": 15.0},
    "grok-2": {"input_per_million": 2.0, "output_per_million": 10.0},
    "grok-3": {"input_per_million": 3.0, "output_per_million": 15.0},
    "grok-3-mini": {"input_per_million": 0.3, "output_per_million": 0.5},
    "grok-4": {"input_per_million": 3.0, "output_per_million": 15.0},
    "grok-4.20-0309-non-reasoning": {
        "cached_input_long_per_million": 0.4,
        "cached_input_per_million": 0.2,
        "input_long_per_million": 2.5,
        "input_per_million": 1.25,
        "output_long_per_million": 5.0,
        "output_per_million": 2.5,
    },
    "grok-4.20-0309-reasoning": {
        "cached_input_long_per_million": 0.4,
        "cached_input_per_million": 0.2,
        "input_long_per_million": 2.5,
        "input_per_million": 1.25,
        "output_long_per_million": 5.0,
        "output_per_million": 2.5,
    },
    "grok-4.20-multi-agent-0309": {
        "cached_input_long_per_million": 0.4,
        "cached_input_per_million": 0.2,
        "input_long_per_million": 2.5,
        "input_per_million": 1.25,
        "output_long_per_million": 5.0,
        "output_per_million": 2.5,
    },
    "grok-4.3": {
        "cached_input_long_per_million": 0.4,
        "cached_input_per_million": 0.2,
        "input_long_per_million": 2.5,
        "input_per_million": 1.25,
        "output_long_per_million": 5.0,
        "output_per_million": 2.5,
    },
    "grok-4.5": {
        "cached_input_long_per_million": 0.6,
        "cached_input_per_million": 0.3,
        "input_long_per_million": 4.0,
        "input_per_million": 2.0,
        "output_long_per_million": 12.0,
        "output_per_million": 6.0,
    },
    "grok-4.6": {
        "cached_input_long_per_million": 1.0,
        "cached_input_per_million": 0.5,
        "input_long_per_million": 4.0,
        "input_per_million": 2.0,
        "output_long_per_million": 12.0,
        "output_per_million": 6.0,
    },
    "grok-4.7": {
        "cached_input_long_per_million": 1.0,
        "cached_input_per_million": 0.5,
        "input_long_per_million": 4.0,
        "input_per_million": 2.0,
        "output_long_per_million": 12.0,
        "output_per_million": 6.0,
    },
    "grok-build-0.1": {
        "cached_input_long_per_million": 0.4,
        "cached_input_per_million": 0.2,
        "input_long_per_million": 2.0,
        "input_per_million": 1.0,
        "output_long_per_million": 4.0,
        "output_per_million": 2.0,
    },
    "grok-imagine-image": {
        "input_per_million": 0.0,
        "output_per_million": 0.0,
        "per_call_usd": 0.02,
    },
    "grok-imagine-image-2.0": {
        "input_per_million": 0.0,
        "output_per_million": 0.0,
        "per_call_usd": 0.04,
    },
    "grok-imagine-video": {
        "input_per_million": 0.0,
        "output_per_million": 0.0,
        "per_second_usd": 0.05,
        "per_second_usd_by_resolution": {"480p": 0.05, "720p": 0.07},
    },
    "grok-imagine-video-1.5": {
        "input_per_million": 0.0,
        "output_per_million": 0.0,
        "per_second_usd": 0.08,
        "per_second_usd_by_resolution": {"1080p": 0.25, "480p": 0.08, "720p": 0.14},
    },
    "grok-imagine-video-1.5-lite": {
        "input_per_million": 0.0,
        "output_per_million": 0.0,
        "per_second_usd": 0.02,
        "per_second_usd_by_resolution": {"1080p": 0.14, "480p": 0.02, "720p": 0.03},
    },
    "grok-voice-latest": {
        "input_per_million": 0.0,
        "output_per_million": 0.0,
        "per_minute_usd": 0.08,
    },
    "grok-voice-think-fast-1.0": {
        "input_per_million": 0.0,
        "output_per_million": 0.0,
        "per_minute_usd": 0.05,
    },
    "grok-voice-think-fast-2.0": {
        "input_per_million": 0.0,
        "output_per_million": 0.0,
        "per_minute_usd": 0.08,
    },
    "stt": {
        "input_per_million": 0.0,
        "output_per_million": 0.0,
        "per_minute_usd": 0.20 / 60.0,
    },
}

_RATE_FIELDS = (
    "input_per_million",
    "output_per_million",
    "cached_input_per_million",
    "image_token_per_million",
    "input_long_per_million",
    "output_long_per_million",
    "cached_input_long_per_million",
    "per_call_usd",
    "per_second_usd",
    "per_second_usd_by_resolution",
    "per_minute_usd",
)

_IMAGE_2_TIERS = {
    ("1k", "low", 0.04),
    ("1.5k", "low", 0.05),
    ("2k", "low", 0.06),
    ("1k", "medium", 0.06),
    ("1.5k", "medium", 0.07),
    ("2k", "medium", 0.08),
}
_IMAGE_TIERS = {
    ("1k", None, 0.02),
    ("2k", None, 0.02),
}


def _tier_set(price: object) -> set[tuple[str, str | None, float]]:
    tiers = getattr(price, "image_tiers", None)
    assert tiers is not None
    return {(tier.resolution, tier.quality, tier.per_call_usd) for tier in tiers}


def _present_rates(price: object) -> dict[str, object]:
    dumped = getattr(price, "model_dump")()
    return {key: dumped[key] for key in _RATE_FIELDS if dumped.get(key) is not None}


def test_shipped_image_defaults_match_listed_html_tiers() -> None:
    """IPT-C04: shipped image tiers and media charges match the live HTML record."""
    from xaikit.pricing import ImagePriceTier

    table = default_price_table()
    image_2 = table.price_for("grok-imagine-image-2.0")
    image = table.price_for("grok-imagine-image")
    assert image_2 is not None
    assert image is not None
    assert _tier_set(image_2) == _IMAGE_2_TIERS
    assert all(isinstance(tier, ImagePriceTier) for tier in image_2.image_tiers or [])
    assert image_2.media_input_per_image_usd == 0.01
    assert image_2.per_call_usd == 0.04
    assert _tier_set(image) == _IMAGE_TIERS
    assert all(isinstance(tier, ImagePriceTier) for tier in image.image_tiers or [])
    assert image.media_input_per_image_usd == 0.002
    assert image.per_call_usd == 0.02
    for model_id, price in table.models.items():
        if model_id in {"grok-imagine-image", "grok-imagine-image-2.0"}:
            continue
        assert price.image_tiers is None
        assert price.media_input_per_image_usd is None
        assert "grok-imagine-video" not in str(model_id) or price.per_call_usd is None
    assert {
        model_id: _present_rates(price) for model_id, price in table.models.items()
    } == _BASE_RATE_SNAPSHOT
