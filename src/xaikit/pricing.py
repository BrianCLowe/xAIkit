"""Model price table for XaiKit usage cost estimates.

Prices are **estimates** for product accounting — not a billing authority.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_DEFAULT_MODELS: dict[str, dict[str, float]] = {
    "grok-4.5": {"input_per_million": 3.0, "output_per_million": 15.0},
    "grok-4": {"input_per_million": 3.0, "output_per_million": 15.0},
    "grok-3": {"input_per_million": 3.0, "output_per_million": 15.0},
    "grok-3-mini": {"input_per_million": 0.3, "output_per_million": 0.5},
    "grok-2": {"input_per_million": 2.0, "output_per_million": 10.0},
    "default": {"input_per_million": 3.0, "output_per_million": 15.0},
}

# Public Imagine video list rates (USD / second). Estimates, not a billing authority.
# 480p is the per_second_usd default when resolution is omitted.
_DEFAULT_VIDEO_MODELS: dict[str, dict[str, Any]] = {
    "grok-imagine-video-1.5": {
        "input_per_million": 0.0,
        "output_per_million": 0.0,
        "per_second_usd": 0.08,
        "per_second_usd_by_resolution": {
            "480p": 0.08,
            "720p": 0.14,
            "1080p": 0.25,
        },
    },
    "grok-imagine-video": {
        "input_per_million": 0.0,
        "output_per_million": 0.0,
        "per_second_usd": 0.05,
        "per_second_usd_by_resolution": {
            "480p": 0.05,
            "720p": 0.07,
        },
    },
}


class ModelPrice(BaseModel):
    """Per-model pricing (token rates and/or per-second video rates)."""

    input_per_million: float = Field(ge=0.0)
    output_per_million: float = Field(ge=0.0)
    per_call_usd: float | None = Field(default=None, ge=0.0)
    per_second_usd: float | None = Field(
        default=None,
        ge=0.0,
        description="USD per second (video 480p default when resolution omitted)",
    )
    per_second_usd_by_resolution: dict[str, float] | None = Field(
        default=None,
        description="Optional USD/second map keyed by resolution (480p, 720p, 1080p)",
    )


class PriceTable(BaseModel):
    """Full price table loaded from config or defaults."""

    version: int = 1
    currency: str = "USD"
    models: dict[str, ModelPrice] = Field(default_factory=dict)

    def price_for(self, model: str) -> ModelPrice:
        """Resolve price for a model id; fall back to ``default`` then bootstrap."""
        key = (model or "").strip()
        if key and key in self.models:
            return self.models[key]
        if key:
            candidates = sorted(
                (k for k in self.models if k != "default" and key.startswith(k)),
                key=len,
                reverse=True,
            )
            if candidates:
                return self.models[candidates[0]]
        if "default" in self.models:
            return self.models["default"]
        return ModelPrice(
            input_per_million=_DEFAULT_MODELS["default"]["input_per_million"],
            output_per_million=_DEFAULT_MODELS["default"]["output_per_million"],
        )

    def estimate_usd(
        self,
        model: str,
        *,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        duration_seconds: float | None = None,
        resolution: str | None = None,
    ) -> float | None:
        """Estimate USD from video duration, token counts, or per-call fallback."""
        price = self.price_for(model)
        if duration_seconds is not None:
            rate = None
            res_map = price.per_second_usd_by_resolution or {}
            res_key = (resolution or "").strip()
            if res_key and res_key in res_map:
                rate = res_map[res_key]
            elif price.per_second_usd is not None:
                rate = price.per_second_usd
            if rate is not None:
                return round(float(duration_seconds) * float(rate), 8)
        pt = prompt_tokens if prompt_tokens is not None else 0
        ct = completion_tokens if completion_tokens is not None else 0
        if prompt_tokens is not None or completion_tokens is not None:
            cost = (pt / 1_000_000.0) * price.input_per_million + (
                ct / 1_000_000.0
            ) * price.output_per_million
            return round(cost, 8)
        if price.per_call_usd is not None:
            return float(price.per_call_usd)
        return None


def default_price_table() -> PriceTable:
    """Built-in bootstrap table (no file required)."""
    models = {mid: ModelPrice(**vals) for mid, vals in _DEFAULT_MODELS.items()}
    for mid, vals in _DEFAULT_VIDEO_MODELS.items():
        models[mid] = ModelPrice(**vals)
    return PriceTable(version=1, currency="USD", models=models)


def load_price_table(path: str | Path | None = None) -> PriceTable:
    """Load price table from JSON path, or return defaults if missing/empty."""
    base = default_price_table()
    if path is None or not str(path).strip():
        return base
    p = Path(path)
    if not p.is_file():
        logger.warning("XAI pricing file not found at %s; using defaults", p)
        return base
    try:
        raw: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to load pricing from %s: %s; using defaults", p, exc)
        return base
    try:
        file_table = PriceTable.model_validate(raw)
        merged = dict(base.models)
        merged.update(file_table.models)
        return PriceTable(
            version=file_table.version,
            currency=file_table.currency or base.currency,
            models=merged,
        )
    except Exception as exc:
        logger.warning("Invalid pricing schema in %s: %s; using defaults", p, exc)
        return base


def save_price_table_template(path: str | Path) -> Path:
    """Write the default table to *path* for operators to edit (no secrets)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    table = default_price_table()
    p.write_text(
        json.dumps(table.model_dump(), indent=2) + "\n",
        encoding="utf-8",
    )
    return p
