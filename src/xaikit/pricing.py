"""Model price table for XaiKit usage cost estimates.

Prices are **estimates** for product accounting — not a billing authority.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Public list prices the bootstrap table was last copied from. Estimates, not billing.
# Refresh: re-read those pages, update the `_DEFAULT_*` dicts below, set PRICE_TABLE_FETCHED.
PRICE_TABLE_SOURCE_URL = "https://docs.x.ai/developers/pricing"
PRICE_TABLE_MODELS_URL = "https://docs.x.ai/docs/models"
PRICE_TABLE_FETCHED = "2026-09-23"
# Daily watch commits this file on master. Installed kits fetch it only to
# fill a price the response and the in-process catalog did not already have.
PUBLIC_PRICES_URL = (
    "https://raw.githubusercontent.com/BrianCLowe/xAIkit/master/scripts/data/xai_public_prices.json"
)
_PUBLIC_PRICE_TTL_SECONDS = 24 * 60 * 60
# Public chat long-context tier starts at 200k prompt tokens.
LONG_CONTEXT_PROMPT_TOKENS = 200_000

# Chat token rates: public under-200k list prices (USD / 1M). Estimates, not billing.
# grok-3 / grok-3-mini kept for old event estimates (off the public table).
# grok-4.7 is an exact key on purpose: price_for prefix-matches, and "grok-4.7"
# startswith "grok-4" ($3 / $15) when this row is missing.
_DEFAULT_MODELS: dict[str, dict[str, float]] = {
    "grok-4.7": {"input_per_million": 2.0, "output_per_million": 6.0},
    "grok-4.6": {"input_per_million": 2.0, "output_per_million": 6.0},
    "grok-4.5": {"input_per_million": 2.0, "output_per_million": 6.0},
    "grok-4.3": {"input_per_million": 1.25, "output_per_million": 2.5},
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

# Public Imagine image list rates (USD / image). Estimates, not a billing authority.
# grok-imagine-image-pro is the documented alias for grok-imagine-image-quality.
_DEFAULT_IMAGE_MODELS: dict[str, dict[str, Any]] = {
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
    "grok-imagine-image-quality": {
        "input_per_million": 0.0,
        "output_per_million": 0.0,
        "per_call_usd": 0.05,
    },
    "grok-imagine-image-pro": {
        "input_per_million": 0.0,
        "output_per_million": 0.0,
        "per_call_usd": 0.05,
    },
}

# Public streaming STT list rate (USD / audio minute from $0.20/hour). Estimates, not billing.
# REST unary STT is $0.10/hour on the public table — not estimated here (no duration on REST calls).
# https://docs.x.ai/developers/pricing (Voice: Speech to Text Streaming $0.20 / hr)
_DEFAULT_STT_MODELS: dict[str, dict[str, Any]] = {
    "stt": {
        "input_per_million": 0.0,
        "output_per_million": 0.0,
        "per_minute_usd": 0.20 / 60.0,
    },
}

# Public Voice / speech-to-speech list rates (USD / audio minute). Estimates, not a billing authority.
# grok-voice-latest is the documented alias for grok-voice-think-fast-2.0.
# Text-input $0.004 on the public table has no documented unit — not estimated here.
_DEFAULT_VOICE_MODELS: dict[str, dict[str, Any]] = {
    "grok-voice-latest": {
        "input_per_million": 0.0,
        "output_per_million": 0.0,
        "per_minute_usd": 0.08,
    },
    "grok-voice-think-fast-2.0": {
        "input_per_million": 0.0,
        "output_per_million": 0.0,
        "per_minute_usd": 0.08,
    },
    "grok-voice-think-fast-1.0": {
        "input_per_million": 0.0,
        "output_per_million": 0.0,
        "per_minute_usd": 0.05,
    },
}


class ModelPrice(BaseModel):
    """Per-model pricing (token, per-second video, and/or per-minute voice rates)."""

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
    per_minute_usd: float | None = Field(
        default=None,
        ge=0.0,
        description="USD per audio minute (realtime voice; estimates, not billing)",
    )
    cached_input_per_million: float | None = Field(default=None, ge=0.0)
    image_token_per_million: float | None = Field(default=None, ge=0.0)
    input_long_per_million: float | None = Field(default=None, ge=0.0)
    output_long_per_million: float | None = Field(default=None, ge=0.0)
    cached_input_long_per_million: float | None = Field(default=None, ge=0.0)


class PriceTable(BaseModel):
    """Full price table loaded from config or defaults."""

    version: int = 1
    currency: str = "USD"
    source_url: str = PRICE_TABLE_SOURCE_URL
    fetched: str = Field(
        default=PRICE_TABLE_FETCHED,
        description="YYYY-MM-DD the bootstrap (or overlay) rates were last copied from source_url",
    )
    models: dict[str, ModelPrice] = Field(default_factory=dict)

    def price_for(self, model: str) -> ModelPrice | None:
        """Exact row, or a prefix whose remainder is empty or starts with ``-``.

        ``grok-4.7-latest`` follows ``grok-4.7``. ``grok-4.8`` does not follow
        ``grok-4``. Unknown ids return None — the ``default`` row is only an
        exact match for the id ``default``.
        """
        key = (model or "").strip()
        if not key:
            return None
        if key in self.models:
            return self.models[key]
        candidates = [
            name
            for name in self.models
            if name != "default" and _prefix_remainder_ok(key, name)
        ]
        if not candidates:
            return None
        return self.models[max(candidates, key=len)]

    def estimate_usd(
        self,
        model: str,
        *,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        duration_seconds: float | None = None,
        resolution: str | None = None,
        usage: dict[str, Any] | None = None,
    ) -> float | None:
        """Estimate USD from video duration, voice minutes, token counts, or per-call fallback."""
        price = self.price_for(model)
        if price is None:
            return None
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
            if price.per_minute_usd is not None:
                return round(
                    (float(duration_seconds) / 60.0) * float(price.per_minute_usd),
                    8,
                )
        if prompt_tokens is not None or completion_tokens is not None:
            return _token_estimate_usd(
                price,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                usage=usage,
            )
        if price.per_call_usd is not None:
            return float(price.per_call_usd)
        return None


def _prefix_remainder_ok(model_id: str, prefix: str) -> bool:
    if not prefix or not model_id.startswith(prefix):
        return False
    rest = model_id[len(prefix) :]
    return rest == "" or rest.startswith("-")


def _usage_int(usage: dict[str, Any] | None, *keys: str) -> int | None:
    if not usage:
        return None
    for key in keys:
        raw = usage.get(key)
        if raw is None:
            continue
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None
    return None


def _token_estimate_usd(
    price: ModelPrice,
    *,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    usage: dict[str, Any] | None,
) -> float | None:
    """Token USD. Long-context rates apply at 200k prompt tokens when present."""
    pt = prompt_tokens if prompt_tokens is not None else 0
    ct = completion_tokens if completion_tokens is not None else 0
    long = pt >= LONG_CONTEXT_PROMPT_TOKENS
    input_rate = price.input_per_million
    output_rate = price.output_per_million
    cached_rate = price.cached_input_per_million
    if long and price.input_long_per_million is not None:
        input_rate = price.input_long_per_million
    if long and price.output_long_per_million is not None:
        output_rate = price.output_long_per_million
    if long and price.cached_input_long_per_million is not None:
        cached_rate = price.cached_input_long_per_million
    cached = _usage_int(usage, "cached_tokens", "cached_prompt_tokens")
    image_tokens = _usage_int(usage, "prompt_image_tokens", "image_tokens")
    uncached = pt
    cached_cost = 0.0
    if cached is not None and cached_rate is not None:
        used = min(max(cached, 0), pt)
        uncached = pt - used
        cached_cost = (used / 1_000_000.0) * float(cached_rate)
    cost = (uncached / 1_000_000.0) * float(input_rate) + (
        ct / 1_000_000.0
    ) * float(output_rate)
    cost += cached_cost
    if image_tokens and price.image_token_per_million is not None:
        cost += (image_tokens / 1_000_000.0) * float(price.image_token_per_million)
    return round(cost, 8)


def default_price_table() -> PriceTable:
    """Built-in bootstrap table (no file required)."""
    models = {mid: ModelPrice(**vals) for mid, vals in _DEFAULT_MODELS.items()}
    for mid, vals in _DEFAULT_IMAGE_MODELS.items():
        models[mid] = ModelPrice(**vals)
    for mid, vals in _DEFAULT_VIDEO_MODELS.items():
        models[mid] = ModelPrice(**vals)
    for mid, vals in _DEFAULT_VOICE_MODELS.items():
        models[mid] = ModelPrice(**vals)
    for mid, vals in _DEFAULT_STT_MODELS.items():
        models[mid] = ModelPrice(**vals)
    return PriceTable(
        version=1,
        currency="USD",
        source_url=PRICE_TABLE_SOURCE_URL,
        fetched=PRICE_TABLE_FETCHED,
        models=models,
    )


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
            source_url=(file_table.source_url or "").strip() or base.source_url,
            fetched=(file_table.fetched or "").strip() or base.fetched,
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


def price_table_from_public_payload(payload: dict[str, Any] | None) -> PriceTable | None:
    """Build a table from the committed gap-file JSON. None when the shape is wrong."""
    if not isinstance(payload, dict):
        return None
    models = payload.get("models")
    if not isinstance(models, dict) or not models:
        return None
    parsed: dict[str, ModelPrice] = {}
    for key, row in models.items():
        if not isinstance(row, dict):
            continue
        try:
            parsed[str(key)] = ModelPrice.model_validate(row)
        except Exception:
            logger.warning("Skipping invalid public price row %s", key, exc_info=True)
    if not parsed:
        return None
    fetched = str(payload.get("fetched") or "").strip() or PRICE_TABLE_FETCHED
    source = str(payload.get("source_url") or "").strip() or PRICE_TABLE_MODELS_URL
    return PriceTable(
        version=1,
        currency="USD",
        source_url=source,
        fetched=fetched,
        models=parsed,
    )


class _PublicPriceCache:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.fetched_at: float | None = None
        self.table: PriceTable | None = None


_public_prices = _PublicPriceCache()


def clear_public_price_cache() -> None:
    """Drop the in-process gap-file cache (tests)."""
    with _public_prices.lock:
        _public_prices.fetched_at = None
        _public_prices.table = None


def fetch_public_price_payload(
    url: str = PUBLIC_PRICES_URL,
    *,
    timeout: float = 10.0,
) -> dict[str, Any] | None:
    """GET the gap file. Never raises. Not called on import."""
    try:
        import httpx

        response = httpx.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "xaikit-price-gap", "Accept": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        logger.warning("Public price gap fetch failed", exc_info=True)
        return None
    return payload if isinstance(payload, dict) else None


def public_price_table(
    *,
    now: float | None = None,
    ttl_seconds: int = _PUBLIC_PRICE_TTL_SECONDS,
) -> PriceTable | None:
    """Gap file, at most once per process per 24 hours.

    A failed refresh keeps the previous table. A later failure cannot replace
    a successful fetch that finished first.
    """
    stamp = time.monotonic() if now is None else now
    with _public_prices.lock:
        fetched_at = _public_prices.fetched_at
        if fetched_at is not None and stamp - fetched_at < ttl_seconds:
            return _public_prices.table
    payload = fetch_public_price_payload()
    table = price_table_from_public_payload(payload)
    with _public_prices.lock:
        if table is None and _public_prices.table is not None:
            _public_prices.fetched_at = stamp
            return _public_prices.table
        _public_prices.fetched_at = stamp
        _public_prices.table = table
    return table
