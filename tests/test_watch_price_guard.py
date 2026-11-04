"""Offline shipped-image price guard. Fixtures only: no network, git, or gh."""

from __future__ import annotations

import importlib.util
import inspect
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "watch_xai_models.py"
WATCH = ROOT / "scripts" / "data" / "xai_public_prices.json"


def _load():
    spec = importlib.util.spec_from_file_location("watch_xai_models_guard", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _watch_models() -> dict:
    payload = json.loads(WATCH.read_text(encoding="utf-8"))
    models = payload.get("models")
    assert isinstance(models, dict)
    return models


def test_every_shipped_image_id_has_watch_row() -> None:
    from xaikit.pricing import default_price_table

    models = _watch_models()
    shipped = {
        model_id: price.per_call_usd
        for model_id, price in default_price_table().models.items()
        if str(model_id).startswith("grok-imagine-image") and price.per_call_usd is not None
    }
    assert shipped
    for model_id, rate in shipped.items():
        assert models[model_id]["per_call_usd"] == rate


def test_removed_ids_not_in_defaults() -> None:
    from xaikit.pricing import _DEFAULT_IMAGE_MODELS, default_price_table

    assert "grok-imagine-image-quality" not in _DEFAULT_IMAGE_MODELS
    assert "grok-imagine-image-pro" not in _DEFAULT_IMAGE_MODELS
    models = default_price_table().models
    assert "grok-imagine-image-quality" not in models
    assert "grok-imagine-image-pro" not in models


def test_kept_image_rates_unchanged() -> None:
    from xaikit.pricing import PRICE_TABLE_FETCHED, default_price_table

    table = default_price_table()
    models = _watch_models()
    assert table.fetched == PRICE_TABLE_FETCHED == "2026-10-04"
    assert table.price_for("grok-imagine-image").per_call_usd == 0.02
    assert table.price_for("grok-imagine-image-2.0").per_call_usd == 0.06
    assert models["grok-imagine-image-2.0"]["per_call_usd"] == 0.06
    assert table.price_for("grok-imagine-image-2.0").per_call_usd == (
        models["grok-imagine-image-2.0"]["per_call_usd"]
    )
    assert table.price_for("grok-imagine-image-2026-03-02").per_call_usd == 0.02
    assert models["grok-imagine-image"]["per_call_usd"] == 0.02
    assert models["grok-imagine-image-2026-03-02"]["per_call_usd"] == 0.02
    assert table.price_for("grok-imagine-video").per_second_usd == 0.05
    assert table.price_for("grok-imagine-video-1.5").per_second_usd == 0.08
    assert table.price_for("grok-imagine-video-1.5-lite").per_second_usd == 0.02
    assert table.price_for("grok-voice-latest").per_minute_usd == 0.08
    assert table.price_for("grok-voice-think-fast-1.0").per_minute_usd == 0.05
    assert table.price_for("stt").per_minute_usd == 0.20 / 60.0
    assert table.price_for("grok-4.7").input_per_million == 2.0
    assert table.price_for("grok-4.7").output_per_million == 6.0


def test_default_image_model_has_price() -> None:
    from xaikit import DEFAULT_IMAGE_MODEL
    from xaikit.pricing import default_price_table

    price = default_price_table().price_for(DEFAULT_IMAGE_MODEL)
    assert price is not None
    assert price.per_call_usd is not None
    assert price.per_call_usd > 0


def test_default_image_model_is_2_0() -> None:
    from xaikit import DEFAULT_IMAGE_MODEL

    assert DEFAULT_IMAGE_MODEL == "grok-imagine-image-2.0"


def test_guard_blocks_missing_shipped_id() -> None:
    watch = _load()
    extract = {"models": {"grok-imagine-image": {"per_call_usd": 0.02}}}
    shipped = {"grok-imagine-image": 0.02, "grok-imagine-image-2.0": 0.06}
    result = watch.check_shipped_image_prices(extract, shipped)
    assert result.ok is False
    assert result.ids == ("grok-imagine-image-2.0",)
    title, body = watch.guard_issue_text(result)
    assert "grok-imagine-image-2.0" in title
    assert "grok-imagine-image-2.0" in body
    source = "\n".join(
        inspect.getsource(fn)
        for fn in (
            watch.check_shipped_image_prices,
            watch.guard_issue_text,
            watch._run_price_guard,
        )
    )
    assert "subprocess" not in source
    assert "os.system" not in source
    assert "git " not in source
    assert "gh " not in source


def test_guard_passes_clean_extract() -> None:
    from xaikit.pricing import default_price_table

    watch = _load()
    shipped = {
        model_id: float(price.per_call_usd)
        for model_id, price in default_price_table().models.items()
        if str(model_id).startswith("grok-imagine-image") and price.per_call_usd is not None
    }
    extract = {
        "models": {
            model_id: {"per_call_usd": rate} for model_id, rate in shipped.items()
        }
    }
    result = watch.check_shipped_image_prices(extract, shipped)
    assert result.ok is True
    assert result.ids == ()
    _title, body = watch.guard_issue_text(result)
    for model_id in shipped:
        assert model_id not in body


def test_guard_ignores_non_shipped_drop() -> None:
    from xaikit.pricing import default_price_table

    watch = _load()
    shipped = {
        model_id: float(price.per_call_usd)
        for model_id, price in default_price_table().models.items()
        if str(model_id).startswith("grok-imagine-image") and price.per_call_usd is not None
    }
    assert "grok-imagine-image-2026-03-02" not in shipped
    extract = {
        "models": {
            model_id: {"per_call_usd": rate} for model_id, rate in shipped.items()
        }
    }
    result = watch.check_shipped_image_prices(extract, shipped)
    assert result.ok is True
    assert result.ids == ()
    assert "grok-imagine-image-2026-03-02" not in result.ids
