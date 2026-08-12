"""Model catalog + resolution for XaiKit.

Resolve chain: pin → intent (cheapest|best_value|best) → task hook → prefer_latest → bootstrap.
No settings import; callers pass knobs / inject fixtures.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from xaikit.types import ModelInfo, ModelSelection

logger = logging.getLogger(__name__)

BOOTSTRAP_MODEL = "grok-4.5"

INTENT_CHEAPEST = "cheapest"
INTENT_BEST_VALUE = "best_value"
INTENT_BEST = "best"
# Canonical three; aliases normalize in. Overlap is allowed when the lineup is thin.
_INTENT_ALIASES = {
    "cheapest": INTENT_CHEAPEST,
    "best_value": INTENT_BEST_VALUE,
    "best-value": INTENT_BEST_VALUE,
    "value": INTENT_BEST_VALUE,
    "best": INTENT_BEST,
}
KNOWN_INTENTS = frozenset(_INTENT_ALIASES.keys())

# xAI SDK reasoning_effort currently accepts only low | high.
THOUGHT_LEVELS_API = frozenset({"low", "high"})
EFFORT_OPTIONS = ("low", "high")

_FetchFn = Callable[[str], list[ModelInfo]]
_TaskAssignFn = Callable[[str], str | None]


class CatalogSnapshot(BaseModel):
    """Cached catalog with fetch metadata."""

    models: list[ModelInfo] = Field(default_factory=list)
    fetched_at: float = Field(default_factory=time.time)
    source: str = "unknown"  # sdk | fixture | inject

    def age_seconds(self) -> float:
        return max(0.0, time.time() - self.fetched_at)

    def is_fresh(self, ttl_seconds: int) -> bool:
        if ttl_seconds <= 0:
            return False
        return self.age_seconds() < ttl_seconds


@dataclass
class _CatalogState:
    snapshot: CatalogSnapshot | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


_state = _CatalogState()
_test_fetch: _FetchFn | None = None
_task_assignment: _TaskAssignFn | None = None
_injected_models: list[ModelInfo] | None = None


def clear_catalog_cache() -> None:
    """Drop in-process catalog cache."""
    with _state.lock:
        _state.snapshot = None


def set_test_fetch(fn: _FetchFn | None) -> None:
    """Inject or clear a test fetch function (bypasses SDK)."""
    global _test_fetch
    _test_fetch = fn


def set_task_assignment(fn: _TaskAssignFn | None) -> None:
    """Optional inject: ``task → model_id`` (apps own role/task names)."""
    global _task_assignment
    _task_assignment = fn


def inject_catalog(models: Sequence[ModelInfo] | None) -> None:
    """Inject offline fixture models (tests / smoke). Clears cache."""
    global _injected_models
    _injected_models = list(models) if models is not None else None
    clear_catalog_cache()


def effort_options() -> list[str]:
    """UI-queryable effort / thought_level options (xAI: low|high)."""
    return list(EFFORT_OPTIONS)


def intent_options() -> list[str]:
    """UI-queryable catalog intents (canonical names, cheapest → best)."""
    return [INTENT_CHEAPEST, INTENT_BEST_VALUE, INTENT_BEST]


def normalize_intent(intent: str | None) -> str | None:
    """Map product intent strings to canonical cheapest | best_value | best."""
    if intent is None:
        return None
    raw = str(intent).strip().lower().replace(" ", "_")
    if not raw:
        return None
    return _INTENT_ALIASES.get(raw)


def normalize_thought_level(level: str | None) -> str | None:
    """Map product thought/effort levels to xAI ``reasoning_effort`` values.

    API supports ``low`` | ``high`` only. ``med`` / ``medium`` map to ``low``.
    Empty → None (omit knob).
    """
    if level is None:
        return None
    raw = str(level).strip().lower()
    if not raw:
        return None
    if raw in ("med", "medium", "mid"):
        return "low"
    if raw in ("effort", "thought_level", "reasoning_effort"):
        return None
    if raw in THOUGHT_LEVELS_API:
        return raw
    logger.warning("Unknown thought_level %r — ignoring", level)
    return None


def load_fixture_catalog(path: Path | str) -> list[ModelInfo]:
    """Load offline catalog fixture (JSON list or {models: [...]})."""
    p = Path(path)
    raw = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        rows = raw.get("models", [])
    elif isinstance(raw, list):
        rows = raw
    else:
        raise ValueError(f"Invalid model catalog fixture shape in {p}")
    return [ModelInfo.model_validate(row) for row in rows]


def _modality_name(value: Any) -> str:
    try:
        from xai_sdk.proto import models_pb2

        name = models_pb2.Modality.Name(int(value))
        return name.lower().removeprefix("modality_").lower()
    except Exception:
        return str(value).lower()


def _price_from_sdk_units(raw: int | None) -> float | None:
    if raw is None or raw == 0:
        return None
    if abs(raw) >= 100:
        return float(raw) / 1000.0
    return float(raw)


def model_info_from_language_proto(lm: Any) -> ModelInfo:
    """Map xAI SDK LanguageModel proto (or duck-typed object) → ModelInfo."""
    name = (getattr(lm, "name", None) or "").strip()
    aliases = list(getattr(lm, "aliases", None) or [])
    version = (getattr(lm, "version", None) or None) or None
    if version is not None:
        version = str(version).strip() or None

    caps: list[str] = ["chat"]
    out_mods = list(getattr(lm, "output_modalities", None) or [])
    in_mods = list(getattr(lm, "input_modalities", None) or [])
    for m in out_mods + in_mods:
        tag = _modality_name(m)
        if tag and tag not in ("invalid", "invalid_modality", "0"):
            if tag not in caps:
                caps.append(tag)
    if _slug_implies_reasoning(name, *[str(a) for a in aliases if a]):
        if "reasoning" not in caps:
            caps.append("reasoning")

    created_raw = getattr(lm, "created", None)
    created: int | None = None
    if created_raw is not None:
        if hasattr(created_raw, "seconds"):
            created = int(created_raw.seconds) or None
        else:
            try:
                created = int(created_raw) or None
            except (TypeError, ValueError):
                created = None

    max_prompt = getattr(lm, "max_prompt_length", None)
    context_length = int(max_prompt) if max_prompt else None

    return ModelInfo(
        id=name,
        display_name=name or None,
        aliases=[str(a) for a in aliases if a],
        version=version,
        capabilities=caps,
        context_length=context_length,
        input_per_million=_price_from_sdk_units(
            getattr(lm, "prompt_text_token_price", None)
        ),
        output_per_million=_price_from_sdk_units(
            getattr(lm, "completion_text_token_price", None)
        ),
        created=created,
    )


def fetch_models_from_sdk(api_key: str) -> list[ModelInfo]:
    """Live fetch language models via xAI SDK (requires network + key)."""
    from xai_sdk import Client

    client = Client(api_key=api_key)
    try:
        language = client.models.list_language_models()
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    models = [model_info_from_language_proto(m) for m in language]
    return [m for m in models if m.id]


def list_models(
    *,
    force_refresh: bool = False,
    api_key: str | None = None,
    ttl_seconds: int = 3600,
    fixture_path: Path | str | None = None,
    allow_fixture_fallback: bool = True,
) -> list[ModelInfo]:
    """Return the model catalog (cached).

    Order: fresh cache → inject → test fetch → SDK → fixture path.
    """
    with _state.lock:
        if (
            not force_refresh
            and _state.snapshot is not None
            and _state.snapshot.is_fresh(ttl_seconds)
        ):
            return list(_state.snapshot.models)

    models: list[ModelInfo]
    source: str
    key = (api_key or "").strip() or None

    if _injected_models is not None:
        models = list(_injected_models)
        source = "inject"
    elif _test_fetch is not None:
        models = list(_test_fetch(key or ""))
        source = "inject"
    elif key:
        try:
            models = fetch_models_from_sdk(key)
            source = "sdk"
        except Exception as exc:
            logger.warning(
                "Model catalog SDK fetch failed (%s); falling back if allowed",
                type(exc).__name__,
            )
            if not allow_fixture_fallback or fixture_path is None:
                raise
            models = load_fixture_catalog(fixture_path)
            source = "fixture"
    elif fixture_path is not None and allow_fixture_fallback:
        models = load_fixture_catalog(fixture_path)
        source = "fixture"
    elif _injected_models is None and allow_fixture_fallback:
        # Empty offline catalog rather than hard-fail when no key/fixture
        models = [
            ModelInfo(id=BOOTSTRAP_MODEL, display_name=BOOTSTRAP_MODEL, capabilities=["chat"]),
            ModelInfo(
                id="grok-3-mini",
                display_name="grok-3-mini",
                capabilities=["chat"],
                input_per_million=0.3,
                output_per_million=0.5,
            ),
        ]
        source = "bootstrap"
    else:
        raise RuntimeError(
            "Cannot list models: no API key, inject, or fixture available"
        )

    snap = CatalogSnapshot(models=models, fetched_at=time.time(), source=source)
    with _state.lock:
        _state.snapshot = snap
    return list(models)


def chat_models(catalog: Sequence[ModelInfo] | None = None) -> list[ModelInfo]:
    """Filter to chat-capable text models."""
    rows = list(catalog) if catalog is not None else list_models()
    return [m for m in rows if m.is_chat and m.id]


def _is_coding_sku(model: ModelInfo) -> bool:
    """True for coding-specialized ids (grok-build-*, grok-code-*, *code-fast*)."""
    mid = (model.id or "").strip().lower().replace("_", "-")
    return bool(mid and _CODE_SKU_ID.search(mid))


def general_chat_models(catalog: Sequence[ModelInfo] | None = None) -> list[ModelInfo]:
    """Chat models minus coding SKUs; falls back to all chat if that would be empty."""
    chat = chat_models(catalog)
    general = [m for m in chat if not _is_coding_sku(m)]
    return general or chat


_GROK_NUM = re.compile(
    r"grok[-_]?(\d+(?:\.\d+)?)(?:[-_]|$)",
    re.IGNORECASE,
)
_NON_REASONING = re.compile(r"non[-_]?reasoning", re.IGNORECASE)
# Match **id** only — grok-4.5 currently aliases grok-build-latest.
_CODE_SKU_ID = re.compile(
    r"^(?:grok-build-|grok-code-)|code-fast",
    re.IGNORECASE,
)


def _slug_implies_reasoning(*parts: str) -> bool:
    """True when a slug names a reasoning model, not a ``non-reasoning`` variant."""
    for part in parts:
        if not part:
            continue
        stripped = _NON_REASONING.sub("", str(part).lower())
        if "reasoning" in stripped:
            return True
    return False


def _version_tuple(model: ModelInfo) -> tuple:
    mid = model.id.lower()
    is_latest_alias = mid.endswith("-latest") or mid.endswith("_latest")
    num = 0.0
    m = _GROK_NUM.search(mid)
    if m:
        try:
            num = float(m.group(1))
        except ValueError:
            num = 0.0
    is_mini = "mini" in mid
    is_fast = "fast" in mid and "non-reasoning" not in mid
    created = model.created or 0
    return (
        num,
        1 if is_latest_alias else 0,
        0 if is_mini else 1,
        0 if is_fast else 1,
        created,
        mid,
    )


def prefer_latest_model(catalog: Sequence[ModelInfo] | None = None) -> str | None:
    """Pick newest chat flagship from catalog (coding SKUs skipped when others exist)."""
    chat = general_chat_models(catalog)
    if not chat:
        return None
    best = max(chat, key=_version_tuple)
    return best.id


def _input_price(model: ModelInfo) -> float:
    if model.input_per_million is not None:
        return float(model.input_per_million)
    # Unknown price → treat as expensive so cheapest prefers priced minis
    return 1e9


def _cheapest_tie_key(model: ModelInfo) -> tuple:
    """Oldest, then non-reasoning, then not multi-agent — budget pick among a price tie."""
    mid = (model.id or "").lower().replace("_", "-")
    created = model.created or 0
    missing_created = 0 if model.created else 1
    is_multi_agent = 1 if "multi-agent" in mid else 0
    is_non_reasoning = 0 if "non-reasoning" in mid else 1
    return (missing_created, created, is_multi_agent, is_non_reasoning, mid)


def cheapest_model(catalog: Sequence[ModelInfo] | None = None) -> str | None:
    """Lowest input_per_million general-chat model (ties → oldest / non-reasoning)."""
    chat = general_chat_models(catalog)
    if not chat:
        return None
    priced = [m for m in chat if m.input_per_million is not None]
    pool = priced or chat
    min_price = min(_input_price(m) for m in pool)
    candidates = [m for m in pool if _input_price(m) == min_price]
    return min(candidates, key=_cheapest_tie_key).id


def best_model(catalog: Sequence[ModelInfo] | None = None) -> str | None:
    """Alias for prefer_latest (flagship / best quality heuristic)."""
    return prefer_latest_model(catalog)


def best_value_model(catalog: Sequence[ModelInfo] | None = None) -> str | None:
    """Newest general-chat model in the price band strictly below flagship.

    Overlaps ``cheapest`` when that band is a single price, and overlaps
    ``best`` when nothing is cheaper than the flagship.
    """
    chat = general_chat_models(catalog)
    if not chat:
        return None
    flagship_id = prefer_latest_model(chat)
    if not flagship_id:
        return cheapest_model(chat)
    flagship = next((m for m in chat if m.id == flagship_id), None)
    if flagship is None:
        return flagship_id
    cap = _input_price(flagship)
    cheaper = [m for m in chat if _input_price(m) < cap]
    if cheaper:
        return prefer_latest_model(cheaper) or cheaper[0].id
    return flagship_id


def resolve_model(
    *,
    pin: str | None = None,
    intent: str | None = None,
    task: str | None = None,
    thought_level: str | None = None,
    catalog: Sequence[ModelInfo] | None = None,
    bootstrap: str = BOOTSTRAP_MODEL,
    task_assignment: _TaskAssignFn | None = None,
) -> str:
    """Resolve a model id via the kit policy chain."""
    return resolve_model_selection(
        pin=pin,
        intent=intent,
        task=task,
        thought_level=thought_level,
        catalog=catalog,
        bootstrap=bootstrap,
        task_assignment=task_assignment,
    ).model_id


def resolve_model_selection(
    *,
    pin: str | None = None,
    intent: str | None = None,
    task: str | None = None,
    thought_level: str | None = None,
    catalog: Sequence[ModelInfo] | None = None,
    bootstrap: str = BOOTSTRAP_MODEL,
    task_assignment: _TaskAssignFn | None = None,
) -> ModelSelection:
    """pin → intent (cheapest|best_value|best) → task hook → prefer_latest → bootstrap."""
    level = normalize_thought_level(thought_level)

    explicit = (pin or "").strip()
    if explicit:
        return ModelSelection(model_id=explicit, thought_level=level, source="pin")

    cat: Sequence[ModelInfo] | None = catalog
    if cat is None:
        try:
            cat = list_models()
        except Exception as exc:
            logger.warning("Catalog unavailable (%s)", type(exc).__name__)
            cat = None

    canonical = normalize_intent(intent)
    if (intent or "").strip() and canonical is None:
        logger.warning("Unknown intent %r — skipping intent step", intent)
    elif canonical is not None and cat is not None:
        picker = {
            INTENT_CHEAPEST: cheapest_model,
            INTENT_BEST_VALUE: best_value_model,
            INTENT_BEST: best_model,
        }[canonical]
        mid = picker(cat)
        if mid:
            return ModelSelection(
                model_id=mid, thought_level=level, source=f"intent:{canonical}"
            )

    assign = task_assignment if task_assignment is not None else _task_assignment
    task_key = (task or "").strip()
    if task_key and assign is not None:
        try:
            assigned = assign(task_key)
        except Exception:
            logger.exception("task_assignment hook failed for %r", task_key)
            assigned = None
        if assigned and str(assigned).strip():
            return ModelSelection(
                model_id=str(assigned).strip(),
                thought_level=level,
                source="task",
            )

    if cat is not None:
        latest = prefer_latest_model(cat)
        if latest:
            return ModelSelection(
                model_id=latest, thought_level=level, source="prefer_latest"
            )

    return ModelSelection(
        model_id=(bootstrap or BOOTSTRAP_MODEL).strip() or BOOTSTRAP_MODEL,
        thought_level=level,
        source="bootstrap",
    )


def catalog_source() -> str | None:
    with _state.lock:
        snap = _state.snapshot
    return snap.source if snap else None
