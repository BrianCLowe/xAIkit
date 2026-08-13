"""Model catalog + resolution for XaiKit.

Resolve chain: pin → intent (cheapest|economy|best) → task hook → prefer_latest → bootstrap.
``role=`` selects the pool (``chat`` default, or ``image`` / ``video`` / ``voice``).
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
DEFAULT_IMAGE_MODEL = "grok-imagine-image-quality"
DEFAULT_VIDEO_MODEL = "grok-imagine-video-1.5"
DEFAULT_VOICE_MODEL = "grok-voice-latest"

INTENT_CHEAPEST = "cheapest"
INTENT_ECONOMY = "economy"
INTENT_BEST = "best"

ROLE_CHAT = "chat"
ROLE_IMAGE = "image"
ROLE_VIDEO = "video"
ROLE_VOICE = "voice"
KNOWN_ROLES = (ROLE_CHAT, ROLE_IMAGE, ROLE_VIDEO, ROLE_VOICE)
_ROLE_BOOTSTRAP = {
    ROLE_CHAT: BOOTSTRAP_MODEL,
    ROLE_IMAGE: DEFAULT_IMAGE_MODEL,
    ROLE_VIDEO: DEFAULT_VIDEO_MODEL,
    ROLE_VOICE: DEFAULT_VOICE_MODEL,
}
# Canonical three; aliases normalize in. Overlap is allowed when the lineup is thin.
# "economy" = cheaper-than-flagship rung, not "best performance-per-dollar".
_INTENT_ALIASES = {
    "cheapest": INTENT_CHEAPEST,
    "economy": INTENT_ECONOMY,
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
    return [INTENT_CHEAPEST, INTENT_ECONOMY, INTENT_BEST]


def normalize_intent(intent: str | None) -> str | None:
    """Map product intent strings to canonical cheapest | economy | best."""
    if intent is None:
        return None
    raw = str(intent).strip().lower().replace(" ", "_")
    if not raw:
        return None
    return _INTENT_ALIASES.get(raw)


def normalize_role(role: str | None) -> str:
    """Map ``role=`` to ``chat`` | ``image`` | ``video`` | ``voice`` (default chat)."""
    if role is None:
        return ROLE_CHAT
    raw = str(role).strip().lower()
    if not raw:
        return ROLE_CHAT
    if raw in KNOWN_ROLES:
        return raw
    logger.warning("Unknown role %r — using chat", role)
    return ROLE_CHAT


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


def _slug_role(*parts: str) -> str | None:
    """Role implied by a model id / alias slug (video before image)."""
    for part in parts:
        mid = str(part or "").strip().lower().replace("_", "-")
        if not mid:
            continue
        if mid.startswith("grok-imagine-video") or "-imagine-video" in mid:
            return ROLE_VIDEO
        if mid.startswith("grok-voice"):
            return ROLE_VOICE
        if "imagine-image" in mid:
            return ROLE_IMAGE
    return None


def _created_unix(value: Any) -> int | None:
    if value is None:
        return None
    if hasattr(value, "seconds"):
        try:
            return int(value.seconds) or None
        except (TypeError, ValueError):
            return None
    try:
        return int(value) or None
    except (TypeError, ValueError):
        return None


def model_info_from_language_proto(lm: Any) -> ModelInfo:
    """Map xAI SDK LanguageModel proto (or duck-typed object) → ModelInfo."""
    name = (getattr(lm, "name", None) or "").strip()
    aliases = list(getattr(lm, "aliases", None) or [])
    version = (getattr(lm, "version", None) or None) or None
    if version is not None:
        version = str(version).strip() or None

    slug = _slug_role(name, *[str(a) for a in aliases if a])
    caps: list[str] = [] if slug in {ROLE_IMAGE, ROLE_VIDEO, ROLE_VOICE} else ["chat"]
    out_mods = list(getattr(lm, "output_modalities", None) or [])
    in_mods = list(getattr(lm, "input_modalities", None) or [])
    for m in out_mods + in_mods:
        tag = _modality_name(m)
        if tag and tag not in ("invalid", "invalid_modality", "0"):
            if slug in {ROLE_IMAGE, ROLE_VIDEO, ROLE_VOICE} and tag in {
                "text",
                "chat",
            }:
                continue
            if tag not in caps:
                caps.append(tag)
    if slug and slug not in caps:
        caps.append(slug)
    if _slug_implies_reasoning(name, *[str(a) for a in aliases if a]):
        if "reasoning" not in caps:
            caps.append("reasoning")

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
        created=_created_unix(getattr(lm, "created", None)),
    )


def model_info_from_image_proto(im: Any) -> ModelInfo:
    """Map xAI SDK ImageGenerationModel proto (or duck-typed object) → ModelInfo.

    Tags ``image`` (or ``video`` / ``voice`` when the slug says so). Maps
    ``image_price`` when present; otherwise leaves prices None so resolve can
    use public rates.
    """
    name = (getattr(im, "name", None) or "").strip()
    aliases = list(getattr(im, "aliases", None) or [])
    version = (getattr(im, "version", None) or None) or None
    if version is not None:
        version = str(version).strip() or None

    slug = _slug_role(name, *[str(a) for a in aliases if a]) or ROLE_IMAGE
    caps = [slug]
    max_prompt = getattr(im, "max_prompt_length", None)
    context_length = int(max_prompt) if max_prompt else None

    return ModelInfo(
        id=name,
        display_name=name or None,
        aliases=[str(a) for a in aliases if a],
        version=version,
        capabilities=caps,
        context_length=context_length,
        input_per_million=_price_from_sdk_units(getattr(im, "image_price", None)),
        created=_created_unix(getattr(im, "created", None)),
    )


def _merge_catalog_row(by_id: dict[str, ModelInfo], info: ModelInfo) -> None:
    if not info.id:
        return
    existing = by_id.get(info.id)
    if existing is None:
        by_id[info.id] = info
        return
    caps = list(existing.capabilities)
    for cap in info.capabilities:
        if cap not in caps:
            caps.append(cap)
    by_id[info.id] = existing.model_copy(
        update={
            "capabilities": caps,
            "aliases": existing.aliases or info.aliases,
            "version": existing.version or info.version,
            "context_length": existing.context_length or info.context_length,
            "input_per_million": (
                existing.input_per_million
                if existing.input_per_million is not None
                else info.input_per_million
            ),
            "output_per_million": (
                existing.output_per_million
                if existing.output_per_million is not None
                else info.output_per_million
            ),
            "created": existing.created if existing.created is not None else info.created,
        }
    )


def _sdk_list_models(
    client: Any,
    method_name: str,
    mapper: Callable[[Any], ModelInfo],
) -> list[ModelInfo]:
    fn = getattr(getattr(client, "models", None), method_name, None)
    if not callable(fn):
        return []
    try:
        rows = fn()
    except Exception as exc:
        logger.warning(
            "Model catalog %s failed (%s); keeping other lists",
            method_name,
            type(exc).__name__,
        )
        return []
    out: list[ModelInfo] = []
    for row in rows or []:
        try:
            info = mapper(row)
        except Exception:
            logger.warning("Skipping catalog row from %s", method_name, exc_info=True)
            continue
        if info.id:
            out.append(info)
    return out


def fetch_models_from_sdk(api_key: str) -> list[ModelInfo]:
    """Live fetch language + image-generation models via xAI SDK.

    Video/voice have no list APIs — those rows are tagged by slug when they
    appear on either list. One list failing does not wipe the others.
    """
    from xai_sdk import Client

    client = Client(api_key=api_key)
    by_id: dict[str, ModelInfo] = {}
    try:
        for method_name, mapper in (
            ("list_language_models", model_info_from_language_proto),
            ("list_image_generation_models", model_info_from_image_proto),
        ):
            for info in _sdk_list_models(client, method_name, mapper):
                _merge_catalog_row(by_id, info)
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    return list(by_id.values())


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


def _model_matches_role(model: ModelInfo, role: str) -> bool:
    if not (model.id or "").strip():
        return False
    slug = _slug_role(model.id, *model.aliases)
    caps = {c.lower() for c in model.capabilities}
    if role == ROLE_CHAT:
        return model.is_chat
    if role == ROLE_IMAGE:
        if slug == ROLE_IMAGE:
            return True
        if slug in {ROLE_VIDEO, ROLE_VOICE}:
            return False
        return ROLE_IMAGE in caps and not model.is_chat
    if role == ROLE_VIDEO:
        return slug == ROLE_VIDEO or ROLE_VIDEO in caps
    if role == ROLE_VOICE:
        return slug == ROLE_VOICE or ROLE_VOICE in caps
    return False


def models_for_role(
    catalog: Sequence[ModelInfo] | None = None,
    role: str | None = None,
) -> list[ModelInfo]:
    """Filter catalog to a role pool. Coding-SKU skip applies to chat only."""
    role_n = normalize_role(role)
    rows = list(catalog) if catalog is not None else list_models()
    matched = [m for m in rows if _model_matches_role(m, role_n)]
    if role_n == ROLE_CHAT:
        general = [m for m in matched if not _is_coding_sku(m)]
        return general or matched
    return matched


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


def _imagine_video_sort_key(model: ModelInfo) -> tuple:
    """Newest grok-imagine-video* id: numeric suffix, then created, then id."""
    mid = (model.id or "").strip().lower().replace("_", "-")
    rest = mid
    if rest.startswith("grok-imagine-video"):
        rest = rest[len("grok-imagine-video") :].lstrip("-")
    nums: list[int] = []
    for part in re.split(r"[^0-9]+", rest):
        if part.isdigit():
            nums.append(int(part))
    is_latest = 1 if rest.endswith("latest") or "-latest-" in f"-{rest}-" else 0
    created = model.created or 0
    return (tuple(nums) if nums else (0,), is_latest, created, mid)


def _newest_key(model: ModelInfo, role: str) -> tuple:
    """Sort key for ``best`` / prefer-latest within a role pool."""
    if role == ROLE_CHAT:
        return _version_tuple(model)
    if role == ROLE_VIDEO:
        return _imagine_video_sort_key(model)
    mid = (model.id or "").strip().lower().replace("_", "-")
    nums: list[int] = []
    for part in re.split(r"[^0-9]+", mid):
        if part.isdigit():
            nums.append(int(part))
    is_latest = 1 if mid.endswith("-latest") or "-latest-" in f"-{mid}-" else 0
    created = model.created or 0
    return (created, is_latest, tuple(nums) if nums else (0,), mid)


def prefer_latest_video_model(catalog: Sequence[ModelInfo] | None = None) -> str:
    """Pick the newest ``grok-imagine-video*`` id from *catalog*.

    Does not change chat resolve. Empty / missing catalog → ``DEFAULT_VIDEO_MODEL``.
    """
    rows = list(catalog) if catalog is not None else []
    videos = [
        m
        for m in rows
        if (m.id or "").strip().lower().replace("_", "-").startswith("grok-imagine-video")
    ]
    if not videos:
        return DEFAULT_VIDEO_MODEL
    return max(videos, key=_imagine_video_sort_key).id


def prefer_latest_model(
    catalog: Sequence[ModelInfo] | None = None,
    *,
    role: str | None = None,
) -> str | None:
    """Pick newest flagship from the role pool (chat: coding SKUs skipped when others exist)."""
    role_n = normalize_role(role)
    pool = models_for_role(catalog, role_n)
    if not pool:
        return None
    best = max(pool, key=lambda m: _newest_key(m, role_n))
    return best.id


def _public_ranking_price(model: ModelInfo, role: str) -> float | None:
    """List/public rate for image/video/voice when SDK omitted ``input_per_million``."""
    if role == ROLE_CHAT:
        return None
    from xaikit.pricing import default_price_table

    table = default_price_table()
    key = (model.id or "").strip()
    if not key:
        return None
    price = None
    if key in table.models:
        price = table.models[key]
    else:
        candidates = sorted(
            (k for k in table.models if k != "default" and key.startswith(k)),
            key=len,
            reverse=True,
        )
        if candidates:
            price = table.models[candidates[0]]
    if price is None:
        return None
    if role == ROLE_VIDEO and price.per_second_usd is not None:
        return float(price.per_second_usd)
    if role == ROLE_VOICE and price.per_minute_usd is not None:
        return float(price.per_minute_usd)
    if role == ROLE_IMAGE and price.per_call_usd is not None:
        return float(price.per_call_usd)
    return None


def _ranking_price(model: ModelInfo, role: str) -> float:
    if model.input_per_million is not None:
        return float(model.input_per_million)
    public = _public_ranking_price(model, role)
    if public is not None:
        return public
    return 1e9


def _has_ranking_price(model: ModelInfo, role: str) -> bool:
    if model.input_per_million is not None:
        return True
    return _public_ranking_price(model, role) is not None


def _cheapest_tie_key(model: ModelInfo) -> tuple:
    """Oldest, then non-reasoning, then not multi-agent — budget pick among a price tie."""
    mid = (model.id or "").lower().replace("_", "-")
    created = model.created or 0
    missing_created = 0 if model.created else 1
    is_multi_agent = 1 if "multi-agent" in mid else 0
    is_non_reasoning = 0 if "non-reasoning" in mid else 1
    return (missing_created, created, is_multi_agent, is_non_reasoning, mid)


def cheapest_model(
    catalog: Sequence[ModelInfo] | None = None,
    *,
    role: str | None = None,
) -> str | None:
    """Lowest ranking-price model in the role pool.

    Chat uses ``input_per_million``. Image/video/voice use that field when
    set, otherwise public list rates. One price band → flagship. Multiple
    bands → oldest / non-reasoning in the cheapest band.
    """
    role_n = normalize_role(role)
    pool = models_for_role(catalog, role_n)
    if not pool:
        return None
    priced = [m for m in pool if _has_ranking_price(m, role_n)]
    use = priced or pool
    prices = {_ranking_price(m, role_n) for m in use}
    if len(prices) <= 1:
        return prefer_latest_model(use, role=role_n) or use[0].id
    min_price = min(prices)
    candidates = [m for m in use if _ranking_price(m, role_n) == min_price]
    return min(candidates, key=_cheapest_tie_key).id


def best_model(
    catalog: Sequence[ModelInfo] | None = None,
    *,
    role: str | None = None,
) -> str | None:
    """Alias for prefer_latest (flagship / best quality heuristic)."""
    return prefer_latest_model(catalog, role=role)


def economy_model(
    catalog: Sequence[ModelInfo] | None = None,
    *,
    role: str | None = None,
) -> str | None:
    """Newest model in the price band strictly below flagship for this role.

    This is the mid / economy rung, not a performance-per-dollar optimum
    (that ratio can belong to ``best``). Overlaps ``cheapest`` when that
    band is a single price, and overlaps ``best`` when nothing is cheaper
    than the flagship.
    """
    role_n = normalize_role(role)
    pool = models_for_role(catalog, role_n)
    if not pool:
        return None
    flagship_id = prefer_latest_model(pool, role=role_n)
    if not flagship_id:
        return cheapest_model(pool, role=role_n)
    flagship = next((m for m in pool if m.id == flagship_id), None)
    if flagship is None:
        return flagship_id
    cap = _ranking_price(flagship, role_n)
    cheaper = [m for m in pool if _ranking_price(m, role_n) < cap]
    if cheaper:
        return prefer_latest_model(cheaper, role=role_n) or cheaper[0].id
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
    role: str | None = None,
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
        role=role,
    ).model_id


def _bootstrap_model_id(role: str, bootstrap: str) -> str:
    if role == ROLE_CHAT:
        return (bootstrap or BOOTSTRAP_MODEL).strip() or BOOTSTRAP_MODEL
    return _ROLE_BOOTSTRAP.get(role, BOOTSTRAP_MODEL)


def resolve_model_selection(
    *,
    pin: str | None = None,
    intent: str | None = None,
    task: str | None = None,
    thought_level: str | None = None,
    catalog: Sequence[ModelInfo] | None = None,
    bootstrap: str = BOOTSTRAP_MODEL,
    task_assignment: _TaskAssignFn | None = None,
    role: str | None = None,
) -> ModelSelection:
    """pin → intent (cheapest|economy|best) → task hook → prefer_latest → bootstrap.

    ``role=`` selects the pool (``chat`` default). Coding-SKU skip is chat-only.
    """
    level = normalize_thought_level(thought_level)
    role_n = normalize_role(role)

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
            INTENT_ECONOMY: economy_model,
            INTENT_BEST: best_model,
        }[canonical]
        mid = picker(cat, role=role_n)
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
        latest = prefer_latest_model(cat, role=role_n)
        if latest:
            return ModelSelection(
                model_id=latest, thought_level=level, source="prefer_latest"
            )

    return ModelSelection(
        model_id=_bootstrap_model_id(role_n, bootstrap),
        thought_level=level,
        source="bootstrap",
    )


def catalog_source() -> str | None:
    with _state.lock:
        snap = _state.snapshot
    return snap.source if snap else None
