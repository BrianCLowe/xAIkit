"""Model catalog + resolution for XaiKit.

Resolve chain: pin → need-filter → intent (cheapest|economy|best) → task hook → prefer_latest → bootstrap.
``role=`` selects the pool (``chat`` default, or ``image`` / ``video`` / ``voice``).
No settings import; callers pass knobs / inject fixtures.
"""

from __future__ import annotations

import json
import logging
import os
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

BOOTSTRAP_MODEL = "grok-4.6"
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

# Canonical 4.6 set. Older families contract via contract_thought_level().
THOUGHT_LEVELS_API = ("low", "medium", "high", "xhigh")
EFFORT_OPTIONS = THOUGHT_LEVELS_API
_THOUGHT_LEVELS_SET = frozenset(THOUGHT_LEVELS_API)

_FAMILY_FULL = "full"  # 4.6+, 4.20-multi-agent: low|medium|high|xhigh
_FAMILY_NO_XHIGH = "no_xhigh"  # 4.5: low|medium|high (xhigh → high)
_FAMILY_LOW_HIGH = "low_high"  # older / unknown reasoners
_FAMILY_NONE = "none"  # non-reasoning SKUs: omit the knob

_FetchFn = Callable[[str], list[ModelInfo]]
_TaskAssignFn = Callable[[str], str | None]


class CatalogSnapshot(BaseModel):
    """Cached catalog with fetch metadata."""

    models: list[ModelInfo] = Field(default_factory=list)
    fetched_at: float = Field(default_factory=time.time)
    source: str = "unknown"  # sdk | persist | fixture | inject

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


def effort_options(model: str | None = None) -> list[str]:
    """UI-queryable effort / thought_level options.

    No ``model`` → full 4.6 set (``low`` | ``medium`` | ``high`` | ``xhigh``).
    With ``model`` → levels that family actually accepts (empty if none).
    """
    family = reasoning_knob_family(model) if model else _FAMILY_FULL
    if family == _FAMILY_NONE:
        return []
    if family == _FAMILY_LOW_HIGH:
        return ["low", "high"]
    if family == _FAMILY_NO_XHIGH:
        return ["low", "medium", "high"]
    return list(EFFORT_OPTIONS)


# Extra capabilities (tools + media), not role tags. resolve_model(need=)
# filters the pool to SKUs that have every requested extra. Unknown / older
# SKUs return [].
_CHAT_EXTRAS_4_6 = (
    "web_search",
    "x_search",
    "code_execution",
    "file_attachments",
    "collections_search",
    "image_understanding",
    "x_video_understanding",
    "mcp",
)
_VIDEO_EXTRAS_QUALITY = ("video_extend", "video_edit", "r2v")
_VIDEO_EXTRAS_1_5 = ("1080p", "r2v")


def feature_options(model: str | None = None) -> list[str]:
    """UI-queryable extra capabilities for a SKU (tools + media knobs).

    No ``model`` → current chat flagship extras (Grok 4.6 set).
    ``grok-4.6`` and later chat SKUs → that set (not ``batch``).
    ``grok-4.3`` → ``batch``. Imagine **quality**
    (``grok-imagine-video`` without ``-1.5``) → extend / edit / R2V.
    ``grok-imagine-video-1.5`` → 1080p / R2V (no extend or edit).
    Unknown or older SKUs → empty (do not invent).
    ``resolve_model(need=…)`` uses this list so ``best`` is best for the job.
    """
    slug = (model or "").strip().lower().replace("_", "-")
    if not slug:
        return list(_CHAT_EXTRAS_4_6)
    video = _video_feature_family(slug)
    if video is not None:
        return list(video)
    if _is_chat_4_6_or_later(slug):
        return list(_CHAT_EXTRAS_4_6)
    if _is_chat_4_3(slug):
        return ["batch"]
    return []


def _video_feature_family(slug: str) -> tuple[str, ...] | None:
    if re.search(r"imagine-video-1[.-]5", slug):
        return _VIDEO_EXTRAS_1_5
    if "imagine-video" in slug:
        return _VIDEO_EXTRAS_QUALITY
    return None


def contract_model_for_need(
    model: str | None,
    need: str | Sequence[str],
    *,
    role: str | None = None,
    catalog: Sequence[ModelInfo] | None = None,
) -> str:
    """Keep ``model`` if it can do the job; otherwise resolve ``best`` for ``need``.

    Unknown SKUs (empty :func:`feature_options`) stay pinned — do not invent.
    Known SKUs missing an extra (1.5 + extend) remap to the job's best.
    """
    needed = _normalize_need(need)
    slug = (model or "").strip()
    if not needed:
        return slug
    extras = feature_options(slug) if slug else []
    known = bool(slug) and _known_feature_sku(slug)
    if slug and not extras and not known:
        return slug
    if slug and needed <= set(extras):
        return slug
    return resolve_model(intent=INTENT_BEST, role=role, need=need, catalog=catalog)


def _is_chat_4_5(slug: str) -> bool:
    if "imagine" in slug or "voice" in slug:
        return False
    return bool(re.search(r"grok-4[.-]5(?!\d)", slug))


def _is_chat_4_3(slug: str) -> bool:
    if "imagine" in slug or "voice" in slug:
        return False
    return bool(re.search(r"grok-4[.-]3(?!\d)", slug))


def _known_feature_sku(slug: str) -> bool:
    """True when we know this family's extras (including a known-empty set)."""
    return (
        _video_feature_family(slug) is not None
        or _is_chat_4_6_or_later(slug)
        or _is_chat_4_5(slug)
        or _is_chat_4_3(slug)
    )


def _is_chat_4_6_or_later(slug: str) -> bool:
    if "imagine" in slug or "voice" in slug or "non-reasoning" in slug:
        return False
    if re.search(r"grok-4[.-]20(?!\d)", slug):
        return False
    matched = re.search(r"grok-(\d+)(?:[.-](\d+))?", slug)
    if not matched:
        return False
    major = int(matched.group(1))
    minor = int(matched.group(2) or 0)
    return major > 4 or (major == 4 and minor >= 6)


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


def reasoning_knob_family(model: str | None) -> str:
    """Which ``reasoning_effort`` set a model accepts.

    ``grok-4.20`` is *older* than ``grok-4.5`` / ``grok-4.6`` despite the
    larger minor — do not treat numeric 20 as “4.6 and later”.
    """
    slug = (model or "").strip().lower().replace("_", "-")
    if not slug:
        return _FAMILY_FULL
    if "non-reasoning" in slug:
        return _FAMILY_NONE
    if "multi-agent" in slug:
        return _FAMILY_FULL
    if re.search(r"grok-4[.-]20(?!\d)", slug):
        return _FAMILY_LOW_HIGH
    if re.search(r"grok-4[.-]5(?!\d)", slug):
        return _FAMILY_NO_XHIGH
    matched = re.search(r"grok-(\d+)(?:[.-](\d+))?", slug)
    if matched:
        major = int(matched.group(1))
        minor = int(matched.group(2) or 0)
        if major > 4 or (major == 4 and minor >= 6):
            return _FAMILY_FULL
    return _FAMILY_LOW_HIGH


def normalize_thought_level(level: str | None) -> str | None:
    """Map product thought/effort levels to canonical 4.6 API values.

    Canonical: ``low`` | ``medium`` | ``high`` | ``xhigh``.
    Aliases: ``med``/``mid`` → ``medium``; ``x-high``/``extra``/``max`` → ``xhigh``.
    Empty / unknown → None (omit knob). Does not contract for a specific model —
    see :func:`contract_thought_level`.
    """
    if level is None:
        return None
    raw = str(level).strip().lower().replace(" ", "-").replace("_", "-")
    if not raw:
        return None
    if raw in ("effort", "thought-level", "reasoning-effort"):
        return None
    aliases = {
        "low": "low",
        "lo": "low",
        "medium": "medium",
        "med": "medium",
        "mid": "medium",
        "high": "high",
        "hi": "high",
        "xhigh": "xhigh",
        "x-high": "xhigh",
        "xh": "xhigh",
        "extra": "xhigh",
        "extra-high": "xhigh",
        "max": "xhigh",
        "maximum": "xhigh",
    }
    if raw in aliases:
        return aliases[raw]
    if raw in _THOUGHT_LEVELS_SET:
        return raw
    logger.warning("Unknown thought_level %r — ignoring", level)
    return None


def contract_thought_level(level: str | None, model: str | None = None) -> str | None:
    """Normalize then clamp to what ``model`` accepts.

    * 4.6+ / multi-agent: pass through
    * 4.5: ``xhigh`` → ``high``
    * older / unknown reasoners: ``xhigh`` → ``high``, ``medium`` → ``low``
    * ``*-non-reasoning*``: omit the knob
    """
    canonical = normalize_thought_level(level)
    if canonical is None:
        return None
    family = reasoning_knob_family(model)
    if family == _FAMILY_NONE:
        return None
    if family == _FAMILY_FULL:
        return canonical
    if family == _FAMILY_NO_XHIGH:
        return "high" if canonical == "xhigh" else canonical
    if canonical == "xhigh":
        return "high"
    if canonical == "medium":
        return "low"
    return canonical


# Imagine generate knobs (REST /v1/images/generations).
# quality is grok-imagine-image-2.0 only — omit on other SKUs.
# Unknown aspect_ratio / resolution: omit (do not 400).
IMAGINE_ASPECT_RATIOS = frozenset(
    {
        "1:1",
        "16:9",
        "9:16",
        "4:3",
        "3:4",
        "3:2",
        "2:3",
        "2:1",
        "1:2",
        "19.5:9",
        "9:19.5",
        "20:9",
        "9:20",
        "auto",
    }
)
IMAGINE_RESOLUTIONS = frozenset({"1k", "2k"})
IMAGINE_QUALITIES = frozenset({"low", "medium"})
_IMAGINE_QUALITY_SKU_MARK = "imagine-image-2.0"


def imagine_supports_quality(model: str | None) -> bool:
    """True only for the Imagine 2.0 image SKU (``grok-imagine-image-2.0``)."""
    slug = (model or "").strip().lower().replace("_", "-")
    return _IMAGINE_QUALITY_SKU_MARK in slug


def contract_imagine_aspect_ratio(value: str | None) -> str | None:
    """Keep official Imagine ratios (incl. ``auto``, ``19.5:9``, ``20:9``); omit unknown."""
    raw = (value or "").strip()
    if not raw:
        return None
    if raw not in IMAGINE_ASPECT_RATIOS:
        logger.warning("Unknown Imagine aspect_ratio %r — omitting", value)
        return None
    return raw


def contract_imagine_resolution(value: str | None) -> str | None:
    """Keep ``1k`` | ``2k``; omit unknown (do not 400)."""
    raw = (value or "").strip().lower()
    if not raw:
        return None
    if raw not in IMAGINE_RESOLUTIONS:
        logger.warning("Unknown Imagine resolution %r — omitting", value)
        return None
    return raw


def contract_imagine_quality(quality: str | None, model: str | None = None) -> str | None:
    """Keep ``low`` | ``medium`` on Imagine 2.0; omit on other SKUs and unknown values."""
    raw = (quality or "").strip().lower()
    if not raw:
        return None
    if raw not in IMAGINE_QUALITIES:
        logger.warning("Unknown Imagine quality %r — omitting", quality)
        return None
    if not imagine_supports_quality(model):
        return None
    return raw


def imagine_generate_knobs(
    model: str,
    *,
    aspect_ratio: str | None = None,
    resolution: str | None = None,
    quality: str | None = None,
    response_format: str | None = None,
) -> dict[str, str]:
    """Optional Imagine generate fields this SKU accepts. Unknown knobs omitted."""
    out: dict[str, str] = {}
    aspect = contract_imagine_aspect_ratio(aspect_ratio)
    if aspect:
        out["aspect_ratio"] = aspect
    res = contract_imagine_resolution(resolution)
    if res:
        out["resolution"] = res
    q = contract_imagine_quality(quality, model)
    if q:
        out["quality"] = q
    fmt = (response_format or "").strip()
    if fmt:
        out["response_format"] = fmt
    return out


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


def save_catalog_snapshot(path: Path | str, models: Sequence[ModelInfo]) -> Path:
    """Write ``{models: [...]}`` JSON (same shape ``load_fixture_catalog`` reads).

    Creates parent directories. An empty *models* list is a valid snapshot.
    Does not choose a default path — callers must pass one. OS errors are
    wrapped in ``RuntimeError``.
    """
    p = Path(path)
    tmp: Path | None = None
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {"models": [m.model_dump(mode="json") for m in models]}
        # Write beside the target then replace so a failed write cannot
        # truncate the last good snapshot (in-place write_text would).
        tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, p)
        tmp = None
    except OSError as exc:
        raise RuntimeError(f"Cannot write catalog snapshot to {p}") from exc
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
    return p


def _optional_path(value: Path | str | None) -> Path | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return Path(value)


def _try_load_persist(path: Path) -> list[ModelInfo] | None:
    if not path.is_file():
        return None
    try:
        return load_fixture_catalog(path)
    except Exception:
        logger.warning("Catalog persist file unreadable (%s); ignoring", path, exc_info=True)
        return None


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

    Tags ``image`` (or ``video`` / ``voice`` when the slug says so). Does
    **not** copy ``image_price`` into ``input_per_million`` (incompatible
    units). Resolve ranks image/video/voice on public list rates.
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
        input_per_million=None,
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
) -> tuple[list[ModelInfo] | None, BaseException | None]:
    """Return ``(rows, None)`` on success, ``(None, exc)`` if the list call failed.

    Missing methods are success with an empty list (not a fetch failure).
    """
    fn = getattr(getattr(client, "models", None), method_name, None)
    if not callable(fn):
        return [], None
    try:
        rows = fn()
    except Exception as exc:
        logger.warning(
            "Model catalog %s failed (%s); keeping other lists",
            method_name,
            type(exc).__name__,
        )
        return None, exc
    out: list[ModelInfo] = []
    for row in rows or []:
        try:
            info = mapper(row)
        except Exception:
            logger.warning("Skipping catalog row from %s", method_name, exc_info=True)
            continue
        if info.id:
            out.append(info)
    return out, None


def fetch_models_from_sdk(api_key: str) -> list[ModelInfo]:
    """Live fetch language + image-generation models via xAI SDK.

    Video/voice have no list APIs — those rows are tagged by slug when they
    appear on either list. One list failing does not wipe the others. If
    **every** list call fails, raise so ``list_models`` can fixture-fallback
    instead of caching an empty SDK snapshot.
    """
    from xai_sdk import Client

    client = Client(api_key=api_key)
    by_id: dict[str, ModelInfo] = {}
    errors: list[BaseException] = []
    any_ok = False
    try:
        for method_name, mapper in (
            ("list_language_models", model_info_from_language_proto),
            ("list_image_generation_models", model_info_from_image_proto),
        ):
            rows, err = _sdk_list_models(client, method_name, mapper)
            if err is not None:
                errors.append(err)
                continue
            any_ok = True
            for info in rows or []:
                _merge_catalog_row(by_id, info)
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    if not any_ok:
        raise errors[0] if errors else RuntimeError("Model catalog SDK lists unavailable")
    return list(by_id.values())


def _bootstrap_offline_models() -> list[ModelInfo]:
    # Two current chat bands so cheapest / economy / best still differ.
    # Public under-200k rates: https://docs.x.ai/docs/models (fetched 2026-08-13).
    return [
        ModelInfo(
            id=BOOTSTRAP_MODEL,
            display_name=BOOTSTRAP_MODEL,
            capabilities=["chat"],
            input_per_million=2.0,
            output_per_million=6.0,
        ),
        ModelInfo(
            id="grok-4.3",
            display_name="grok-4.3",
            capabilities=["chat"],
            input_per_million=1.25,
            output_per_million=2.5,
        ),
    ]


def list_models(
    *,
    force_refresh: bool = False,
    api_key: str | None = None,
    ttl_seconds: int = 3600,
    fixture_path: Path | str | None = None,
    persist_path: Path | str | None = None,
    allow_fixture_fallback: bool = True,
) -> list[ModelInfo]:
    """Return the model catalog (cached).

    Order when no inject/test-fetch: fresh memory cache → SDK if key →
    ``persist_path`` file if present → ``fixture_path`` → bootstrap.

    After a successful SDK fetch, if ``persist_path`` is set, write
    ``{models: [...]}`` there (best-effort: disk errors are logged and the
    live list is still returned). No default path — omit to skip disk.
    ``clear_catalog_cache`` drops memory only; it does not delete the file.
    """
    with _state.lock:
        if (
            not force_refresh
            and _state.snapshot is not None
            and _state.snapshot.is_fresh(ttl_seconds)
        ):
            return list(_state.snapshot.models)

    models: list[ModelInfo] | None = None
    source: str | None = None
    key = (api_key or "").strip() or None
    persist = _optional_path(persist_path)
    sdk_error: BaseException | None = None

    if _injected_models is not None:
        models = list(_injected_models)
        source = "inject"
    elif _test_fetch is not None:
        models = list(_test_fetch(key or ""))
        source = "inject"
    else:
        if key:
            try:
                models = fetch_models_from_sdk(key)
                source = "sdk"
            except Exception as exc:
                sdk_error = exc
                logger.warning(
                    "Model catalog SDK fetch failed (%s); falling back if allowed",
                    type(exc).__name__,
                )
        if models is None and persist is not None:
            loaded = _try_load_persist(persist)
            if loaded is not None:
                models = loaded
                source = "persist"
        if models is None and fixture_path is not None and allow_fixture_fallback:
            models = load_fixture_catalog(fixture_path)
            source = "fixture"
        if models is None and key is None and allow_fixture_fallback:
            models = _bootstrap_offline_models()
            source = "bootstrap"

    if models is None or source is None:
        if sdk_error is not None:
            raise sdk_error
        raise RuntimeError(
            "Cannot list models: no API key, inject, or fixture available"
        )

    if source == "sdk" and persist is not None:
        try:
            save_catalog_snapshot(persist, models)
        except Exception:
            logger.warning(
                "Catalog snapshot persist failed for %s; returning live catalog",
                persist,
                exc_info=True,
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
    if role != ROLE_CHAT:
        public = _public_ranking_price(model, role)
        if public is not None:
            return public
    if model.input_per_million is not None:
        return float(model.input_per_million)
    public = _public_ranking_price(model, role)
    if public is not None:
        return public
    return 1e9


def _has_ranking_price(model: ModelInfo, role: str) -> bool:
    if role != ROLE_CHAT and _public_ranking_price(model, role) is not None:
        return True
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


def _normalize_need(need: str | Sequence[str] | None) -> frozenset[str]:
    if need is None:
        return frozenset()
    if isinstance(need, str):
        items: Sequence[str] = (need,)
    else:
        items = need
    return frozenset(str(item).strip() for item in items if str(item).strip())


def _catalog_for_need(
    catalog: Sequence[ModelInfo], needed: frozenset[str]
) -> list[ModelInfo]:
    if not needed:
        return list(catalog)
    return [m for m in catalog if needed <= set(feature_options(m.id))]


_FEATURE_FALLBACK_SLUGS = (
    BOOTSTRAP_MODEL,
    "grok-4.3",
    "grok-imagine-video",
    DEFAULT_VIDEO_MODEL,
    DEFAULT_IMAGE_MODEL,
    DEFAULT_VOICE_MODEL,
)


def _bootstrap_for_need(needed: frozenset[str], role: str, bootstrap: str) -> str:
    if not needed:
        return _bootstrap_model_id(role, bootstrap)
    for slug in _FEATURE_FALLBACK_SLUGS:
        if needed <= set(feature_options(slug)):
            return slug
    return _bootstrap_model_id(role, bootstrap)


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
    need: str | Sequence[str] | None = None,
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
        need=need,
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
    need: str | Sequence[str] | None = None,
) -> ModelSelection:
    """pin → need-filter → intent (cheapest|economy|best) → task hook → prefer_latest → bootstrap.

    ``role=`` selects the pool (``chat`` default). Coding-SKU skip is chat-only.
    ``need=`` (one feature or a sequence) keeps only SKUs whose
    :func:`feature_options` include every requested extra, so ``best`` is
    best for that job (Imagine quality over 1.5 when the job is extend).
    """
    level = normalize_thought_level(thought_level)
    role_n = normalize_role(role)
    needed = _normalize_need(need)

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
    if cat is not None and needed:
        cat = _catalog_for_need(cat, needed)

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
        model_id=_bootstrap_for_need(needed, role_n, bootstrap),
        thought_level=level,
        source="bootstrap",
    )


def catalog_source() -> str | None:
    with _state.lock:
        snap = _state.snapshot
    return snap.source if snap else None
