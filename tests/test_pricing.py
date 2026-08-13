"""Price table provenance, overlay, and no-invented-USD rows."""

from __future__ import annotations

import json

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
    # No tokens / duration / per-call → None. (Token estimates on unknown
    # slugs still fall back to the chat ``default`` row — the meter skips
    # the table for modalities with no public rate.)
    assert table.estimate_usd("not-a-public-sku") is None
