"""Model catalog + resolution for XaiKit.

Resolve chain: pin → need-filter → intent (cheapest|economy|best) → task hook → prefer_latest → bootstrap.
``role=`` selects the pool (``chat`` default, or ``image`` / ``video`` / ``voice`` / ``speech-to-text``).
No settings import; callers pass knobs / inject fixtures.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from xaikit.types import ModelInfo, ModelSelection

logger = logging.getLogger(__name__)

BOOTSTRAP_MODEL = "grok-4.7"
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
ROLE_SPEECH_TO_TEXT = "speech-to-text"
KNOWN_ROLES = (ROLE_CHAT, ROLE_IMAGE, ROLE_VIDEO, ROLE_VOICE, ROLE_SPEECH_TO_TEXT)
# grok-voice-transcribe* is speech-to-text, not the realtime voice pool.
_SPEECH_TO_TEXT_BOOTSTRAP = "grok-voice-transcribe-2.0"
_NON_CHAT_SLUG_ROLES = frozenset(
    {ROLE_IMAGE, ROLE_VIDEO, ROLE_VOICE, ROLE_SPEECH_TO_TEXT}
)
_ROLE_BOOTSTRAP = {
    ROLE_CHAT: BOOTSTRAP_MODEL,
    ROLE_IMAGE: DEFAULT_IMAGE_MODEL,
    ROLE_VIDEO: DEFAULT_VIDEO_MODEL,
    ROLE_VOICE: DEFAULT_VOICE_MODEL,
    ROLE_SPEECH_TO_TEXT: _SPEECH_TO_TEXT_BOOTSTRAP,
}
# Canonical three; aliases normalize in. Overlap is allowed when the lineup is thin.
# "economy" = cheaper-than-flagship rung, not "best performance-per-dollar".
_INTENT_ALIASES = {
    "cheapest": INTENT_CHEAPEST,
    "economy": INTENT_ECONOMY,
    "best": INTENT_BEST,
}

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
    source: str = "unknown"  # sdk | rest | persist | fixture | inject
    base_url: str = ""
    # When set, caps freshness below the caller TTL. Deadline fallbacks use this.
    fresh_for: float | None = None

    def age_seconds(self) -> float:
        return max(0.0, time.time() - self.fetched_at)

    def is_fresh(self, ttl_seconds: int) -> bool:
        limit = float(ttl_seconds)
        if self.fresh_for is not None:
            limit = min(limit, float(self.fresh_for))
        if limit <= 0:
            return False
        return self.age_seconds() < limit


@dataclass
class _CatalogState:
    snapshot: CatalogSnapshot | None = None
    # One latest successful SDK or REST list, shared by every timeout.
    live: CatalogSnapshot | None = None
    # Fetch-attempt fallbacks, keyed by the timeout that stored them.
    fallbacks: dict[float, CatalogSnapshot] = field(default_factory=dict)
    # None when snapshot is shared (live or caller catalog). A float when
    # snapshot is that timeout's fallback, published only for catalog_source.
    snapshot_timeout: float | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


_state = _CatalogState()
_test_fetch: _FetchFn | None = None
_task_assignment: _TaskAssignFn | None = None
_injected_models: list[ModelInfo] | None = None


def clear_catalog_cache() -> None:
    """Drop in-process catalog cache."""
    with _state.lock:
        _state.snapshot = None
        _state.live = None
        _state.snapshot_timeout = None
        _state.fallbacks.clear()


def _published_snapshot() -> CatalogSnapshot | None:
    """Live list wins so a per-timeout fallback cannot hide a fresher one."""
    if _state.live is not None:
        return _state.live
    return _state.snapshot


def find_cached_model(model_id: str) -> ModelInfo | None:
    """Match a cached catalog row by id or alias. None when the cache is empty."""
    rows = cached_catalog()
    if not rows:
        return None
    key = (model_id or "").strip()
    if not key:
        return None
    for row in rows:
        if row.id == key:
            return row
    low = key.lower()
    for row in rows:
        if row.id.lower() == low:
            return row
        if any(alias.lower() == low for alias in row.aliases):
            return row
    return None


def cached_catalog() -> list[ModelInfo] | None:
    """Return the in-process snapshot, or None when nothing has been fetched.

    Does not call the SDK or write the bootstrap pair. Metering uses this so
    a price lookup cannot populate the catalog cache.
    """
    with _state.lock:
        snap = _published_snapshot()
    if snap is None:
        return None
    return list(snap.models)


def _live_key_needs_fetch(snap: CatalogSnapshot, key: str | None) -> bool:
    """A no-key bootstrap/persist snapshot must not hide a later keyed fetch."""
    if not key:
        return False
    if _injected_models is not None or _test_fetch is not None:
        return False
    return snap.source in {"bootstrap", "persist"}


# Successful SDK or REST lists. Every other source is non-live.
_LIVE_SOURCES = frozenset({"sdk", "rest"})
# Caller-supplied catalogs. A failed fetch that lands on these is a fallback.
_CALLER_CATALOG_SOURCES = frozenset({"inject", "fixture", "persist"})


def _snapshot_slot(source: str, *, fetch_failed: bool) -> str:
    """Classify a snapshot as ``live``, ``fallback``, or ``explicit``.

    ``live``: successful SDK or REST list. One shared snapshot. Storing it
    clears every per-timeout fallback.

    ``fallback``: non-live result of a fetch that failed. That includes
    persist, fixture, inject, bootstrap, and ``sdk-error``. A deadline keeps
    ``fresh_for`` of ``CATALOG_TIMEOUT_RETRY_SECONDS`` (60). Any other failure
    keeps the caller TTL. The entry stays on the timeout that stored it and
    does not replace a live snapshot. A newer fallback for that timeout
    replaces the previous entry.

    ``explicit``: caller inject, test fetch, or a fixture, persist, or
    bootstrap load with no failed fetch. Inject, fixture, and persist replace
    the one shared snapshot the way the single-slot cache did. Bootstrap
    replaces that shared snapshot too, and leaves other timeouts' fallbacks
    in place so an offline list does not drop a deadline window.
    """
    if source in _LIVE_SOURCES:
        return "live"
    if fetch_failed:
        return "fallback"
    return "explicit"


def _snapshot_usable(
    snap: CatalogSnapshot | None,
    *,
    ttl_seconds: int,
    rest_base: str,
    key: str | None,
) -> bool:
    if snap is None:
        return False
    if not snap.is_fresh(ttl_seconds) or snap.base_url != rest_base:
        return False
    if snap.fresh_for is None and _live_key_needs_fetch(snap, key):
        return False
    return True


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
_VIDEO_EXTRAS_1_5_LITE = ("1080p",)


def feature_options(model: str | None = None) -> list[str]:
    """UI-queryable extra capabilities for a SKU (tools + media knobs).

    No ``model`` → current chat flagship extras (Grok 4.7; same set as 4.6+).
    ``grok-4.6`` and later chat SKUs (including ``grok-4.7``) → that set (not ``batch``).
    ``grok-4.3`` → ``batch``. Imagine **quality** extras (extend / edit / R2V)
    go only to unversioned ``grok-imagine-video``, its ``-latest`` alias, and a
    dated snapshot of that id. ``grok-imagine-video-1.5`` → 1080p / R2V (no
    extend or edit). ``grok-imagine-video-1.5-lite`` → 1080p only (text and
    image in; no R2V, extend, or edit). A versioned or unknown id such as
    ``grok-imagine-video-2.0-preview`` or ``grok-imagine-video-3.0-lite`` is
    empty until the catalog lists it.
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


# ``lite`` as its own id segment. ``latest``, ``elite``, and ``lites`` do not match.
_LITE_SEGMENT = re.compile(r"(?:^|-)lite(?:-|$)")


def _is_lite_id(model_id: str) -> bool:
    """True when ``lite`` is its own segment of the model id."""
    mid = (model_id or "").strip().lower().replace("_", "-")
    return _LITE_SEGMENT.search(mid) is not None


def _non_lite_rank(model_id: str) -> int:
    """1 for a non-lite id, 0 for a ``-lite`` id. Higher sorts first."""
    return 0 if _is_lite_id(model_id) else 1


def _is_imagine_video_lite(slug: str) -> bool:
    """True for a ``-lite`` Imagine video id (not ``-latest``)."""
    return _is_lite_id(slug)


def _video_feature_family(slug: str) -> tuple[str, ...] | None:
    """Known Imagine video extras, or None when the id is not a known family.

    The 1.5 family keeps today's classification, including preview and dated
    ids. Extend, edit, and r2v belong only to unversioned
    ``grok-imagine-video``, its ``-latest`` alias, and a dated snapshot of
    that id. Any other versioned or unknown id stays unknown so a pin is kept
    and ``need=`` does not select it.
    """
    if "imagine-video" not in slug:
        return None
    if re.search(r"imagine-video-1[.-]5", slug):
        if _is_lite_id(slug):
            return _VIDEO_EXTRAS_1_5_LITE
        return _VIDEO_EXTRAS_1_5
    if _snapshot_family(slug) == "grok-imagine-video":
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
    major, minor = _chat_major_minor(slug)
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
    """Map ``role=`` to chat, image, video, voice, or speech-to-text (default chat)."""
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


# Public docs token scale: 20000 = $2 / 1M, 60000 = $6 / 1M.
_SDK_TOKEN_SCALE = 10_000
# Public docs media scale: 500000000 = $0.05 / image, 800000000 = $0.08 / video second.
_SDK_MEDIA_SCALE = 10_000_000_000


def _price_from_sdk_units(raw: int | None) -> float | None:
    """Language-token list price (USD per 1M) from SDK / docs integer units."""
    if raw is None or raw == 0:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    if value == 0:
        return None
    if abs(value) >= 100:
        return float(value) / float(_SDK_TOKEN_SCALE)
    return float(value)


def _price_from_media_units(raw: int | None) -> float | None:
    """Per-image (or per-second) USD from the public media integer scale.

    Values under 1_000_000 are already dollars (test fixtures). Docs and the
    live list use 1e10 = $1.
    """
    if raw is None or raw == 0:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    if value == 0:
        return None
    if abs(value) >= 1_000_000:
        return float(value) / float(_SDK_MEDIA_SCALE)
    return float(value)


def _slug_role(*parts: str) -> str | None:
    """Role implied by a model id / alias slug (video before image)."""
    for part in parts:
        mid = str(part or "").strip().lower().replace("_", "-")
        if not mid:
            continue
        if mid.startswith("grok-imagine-video") or "-imagine-video" in mid:
            return ROLE_VIDEO
        # Transcribe ids leave role=voice. They resolve only as speech-to-text.
        if mid.startswith("grok-voice-transcribe"):
            return ROLE_SPEECH_TO_TEXT
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
    caps: list[str] = [] if slug in _NON_CHAT_SLUG_ROLES else ["chat"]
    out_mods = list(getattr(lm, "output_modalities", None) or [])
    in_mods = list(getattr(lm, "input_modalities", None) or [])
    for m in out_mods + in_mods:
        tag = _modality_name(m)
        if tag and tag not in ("invalid", "invalid_modality", "0"):
            if slug in _NON_CHAT_SLUG_ROLES and tag in {
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
        cached_input_per_million=_price_from_sdk_units(
            getattr(lm, "cached_prompt_token_price", None)
        ),
        image_token_per_million=_price_from_sdk_units(
            getattr(lm, "prompt_image_token_price", None)
        ),
        input_long_per_million=_price_from_sdk_units(
            getattr(lm, "prompt_text_token_price_long_context", None)
        ),
        output_long_per_million=_price_from_sdk_units(
            getattr(lm, "completion_token_price_long_context", None)
        ),
        cached_input_long_per_million=_price_from_sdk_units(
            getattr(lm, "cached_prompt_token_price_long_context", None)
        ),
        created=_created_unix(getattr(lm, "created", None)),
    )


def model_info_from_image_proto(im: Any) -> ModelInfo:
    """Map xAI SDK ImageGenerationModel proto (or duck-typed object) → ModelInfo.

    Tags ``image`` (or ``video`` / ``voice`` / ``speech-to-text`` when the slug says so).
    Stores ``image_price`` as ``per_image_usd`` and does **not** copy it into
    ``input_per_million`` (incompatible units). Resolve ranks image/video/voice
    on public list rates.
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
        per_image_usd=_price_from_media_units(getattr(im, "image_price", None)),
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
            "cached_input_per_million": (
                existing.cached_input_per_million
                if existing.cached_input_per_million is not None
                else info.cached_input_per_million
            ),
            "image_token_per_million": (
                existing.image_token_per_million
                if existing.image_token_per_million is not None
                else info.image_token_per_million
            ),
            "input_long_per_million": (
                existing.input_long_per_million
                if existing.input_long_per_million is not None
                else info.input_long_per_million
            ),
            "output_long_per_million": (
                existing.output_long_per_million
                if existing.output_long_per_million is not None
                else info.output_long_per_million
            ),
            "cached_input_long_per_million": (
                existing.cached_input_long_per_million
                if existing.cached_input_long_per_million is not None
                else info.cached_input_long_per_million
            ),
            "per_image_usd": (
                existing.per_image_usd
                if existing.per_image_usd is not None
                else info.per_image_usd
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


# Seconds for one host GET /v1/models. Tests may shorten this.
HOST_MODELS_TIMEOUT_SECONDS = 30.0

_shipped_roles: dict[str, str] | None = None


def _shipped_role_map() -> dict[str, str]:
    """Exact ids the shipped price table and speech-to-text defaults already know.

    Lookup is by id only. A prefix or an id pattern is not a role.
    """
    global _shipped_roles
    if _shipped_roles is not None:
        return _shipped_roles
    from xaikit.pricing import (
        _DEFAULT_IMAGE_MODELS,
        _DEFAULT_MODELS,
        _DEFAULT_STT_MODELS,
        _DEFAULT_VIDEO_MODELS,
        _DEFAULT_VOICE_MODELS,
    )

    roles: dict[str, str] = {}
    for mid in _DEFAULT_MODELS:
        if mid != "default":
            roles[mid] = ROLE_CHAT
    for mid in _DEFAULT_IMAGE_MODELS:
        roles[mid] = ROLE_IMAGE
    for mid in _DEFAULT_VIDEO_MODELS:
        roles[mid] = ROLE_VIDEO
    for mid in _DEFAULT_VOICE_MODELS:
        roles[mid] = ROLE_VOICE
    for mid in _DEFAULT_STT_MODELS:
        roles[mid] = ROLE_SPEECH_TO_TEXT
    roles["grok-voice-transcribe-1.0"] = ROLE_SPEECH_TO_TEXT
    roles[_SPEECH_TO_TEXT_BOOTSTRAP] = ROLE_SPEECH_TO_TEXT
    _shipped_roles = roles
    return roles


def static_role_for_id(model_id: str) -> str:
    """Role of a listed id from the static catalog.

    An id the static catalog does not know is chat. The REST ``/v1/models``
    payload is not consulted: that list tags every model as chat.
    """
    key = (model_id or "").strip()
    if not key:
        return ROLE_CHAT
    return _shipped_role_map().get(key, ROLE_CHAT)


def _exact_injected_row(model_id: str) -> ModelInfo | None:
    rows = _injected_models
    if not rows:
        return None
    for row in rows:
        if row.id == model_id:
            return row
    return None


def _exact_shipped_price(model_id: str) -> Any:
    from xaikit.pricing import default_price_table

    return default_price_table().models.get(model_id)


def _payload_created(value: Any) -> int | None:
    """Unix seconds from a host catalog row.

    Only a real int counts. Strings (ISO or otherwise), null, bool, and
    other types stay unset so ranking treats them as oldest.
    """
    if type(value) is not int:
        return None
    if value == 0:
        return None
    return value


def _payload_owned_by(value: Any) -> str | None:
    """Owner string from a host catalog row. Non-strings stay unset."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def describe_listed_id(
    model_id: str,
    *,
    row: Mapping[str, Any] | None = None,
) -> tuple[ModelInfo, str]:
    """One host-listed id as ``(row, role)``.

    Role comes from :func:`static_role_for_id`. Prices prefer an injected row
    for that exact id, then the shipped table's exact row. REST tags and
    payload price fields are ignored. A usable ``created`` or ``owned_by`` on
    *row* wins. When the host omitted them, the injected row is kept.
    """
    role = static_role_for_id(model_id)
    source = _exact_injected_row(model_id)
    input_rate = source.input_per_million if source is not None else None
    output_rate = source.output_per_million if source is not None else None
    created = source.created if source is not None else None
    owned_by = source.owned_by if source is not None else None
    if row is not None:
        row_created = row.get("created")
        if row_created is not None:
            created = row_created
        row_owner = row.get("owned_by")
        if row_owner:
            owned_by = row_owner
    if input_rate is None or output_rate is None:
        price = _exact_shipped_price(model_id)
        if price is not None:
            if input_rate is None:
                input_rate = price.input_per_million
            if output_rate is None:
                output_rate = price.output_per_million
    caps = ["chat"] if role == ROLE_CHAT else [role]
    info = ModelInfo(
        id=model_id,
        display_name=model_id,
        capabilities=caps,
        input_per_million=input_rate,
        output_per_million=output_rate,
        created=created,
        owned_by=owned_by,
    )
    return info, role


def _model_ids_from_payload(payload: Any) -> list[dict[str, Any]]:
    """Read each ``data`` row and normalize ``created`` and ``owned_by``.

    Role tags and prices are left on the mapping and are not applied.
    Rows that are not objects, or that have no id, are skipped.
    """
    if not isinstance(payload, dict):
        raise RuntimeError("Model catalog returned unexpected payload")
    data = payload.get("data")
    if not isinstance(data, list):
        raise RuntimeError("Model catalog returned unexpected payload")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, dict) or "id" not in item:
            continue
        mid = str(item.get("id") or "").strip()
        if not mid or mid in seen:
            continue
        seen.add(mid)
        kept = dict(item)
        kept["id"] = mid
        kept["created"] = _payload_created(item.get("created"))
        kept["owned_by"] = _payload_owned_by(item.get("owned_by"))
        rows.append(kept)
    if not rows:
        raise RuntimeError("Model catalog returned an empty data list")
    return rows


def log_host_catalog_fallback(host: str) -> None:
    """One warning when a client's host model list cannot be used."""
    logger.warning(
        "Model list for host %s failed; using the static catalog",
        host,
    )


def _host_catalog_rows(response: Any) -> list[tuple[ModelInfo, str]]:
    """Rows from a finished ``GET /models`` response.

    Shared by the sync and async fetches so both keep ``created`` and
    ``owned_by`` the same way. Raises on HTTP errors, non-JSON bodies, and a
    200 with an empty ``data`` list.
    """
    if response.status_code >= 400:
        detail = response.text[:500] if response.text else response.reason_phrase
        raise RuntimeError(f"Model catalog failed ({response.status_code}): {detail}")
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise RuntimeError("Model catalog returned non-JSON response") from exc
    return [
        describe_listed_id(str(row["id"]), row=row)
        for row in _model_ids_from_payload(payload)
    ]


def regional_host_catalog_timeout(sdk_timeout: float) -> float:
    """Async host-list timeout: resolved SDK timeout, capped at 30 seconds.

    ``sdk_timeout`` is the client's resolved value (constructor, then
    ``XAI_SDK_TIMEOUT_SECONDS``, then 180). The cap is
    ``HOST_MODELS_TIMEOUT_SECONDS``. Sync ``fetch_host_catalog`` does not use
    this helper.
    """
    return min(float(sdk_timeout), float(HOST_MODELS_TIMEOUT_SECONDS))


def fetch_host_catalog(api_key: str, base_url: str) -> list[tuple[ModelInfo, str]]:
    """GET ``<base>/models`` and classify each id from the static catalog.

    Each row keeps ``created`` and ``owned_by``. Role tags and payload prices
    are ignored. Raises on HTTP errors, connection failures, timeouts,
    non-JSON bodies, and a 200 with an empty ``data`` list. Does not cache.
    The timeout is ``HOST_MODELS_TIMEOUT_SECONDS`` only.
    """
    import httpx

    from xaikit.base_url import join_url

    url = join_url(base_url, "models")
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        response = httpx.get(
            url,
            headers=headers,
            timeout=HOST_MODELS_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Model catalog request failed: {exc}") from exc
    return _host_catalog_rows(response)


async def fetch_host_catalog_async(
    api_key: str,
    base_url: str,
    *,
    timeout: float,
) -> list[tuple[ModelInfo, str]]:
    """Async GET ``<base>/models`` via ``httpx.AsyncClient``.

    Same rows and errors as :func:`fetch_host_catalog`. ``timeout`` is the
    caller's limit in seconds. ``AsyncXaiClient`` passes
    :func:`regional_host_catalog_timeout`. Does not cache. Does not block the
    event loop.
    """
    import httpx

    from xaikit.base_url import join_url

    url = join_url(base_url, "models")
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Model catalog request failed: {exc}") from exc
    return _host_catalog_rows(response)


def fetch_models_via_rest(api_key: str, base_url: str) -> list[ModelInfo]:
    """GET ``<base>/models`` for a non-default inference base.

    Ids come from ``data[].id``. ``created`` and ``owned_by`` are kept.
    Each row's role comes from the static catalog. An unknown id is chat.
    This function does not cache and does not filter the client's later
    resolve; callers do that.
    """
    return [info for info, _role in fetch_host_catalog(api_key, base_url)]


def static_fallback_models() -> list[ModelInfo]:
    """Offline catalog when a host model list cannot be read.

    Injected rows win. Otherwise the bootstrap pair. Does not fetch and does
    not write the process-wide snapshot.
    """
    if _injected_models is not None:
        return list(_injected_models)
    return _bootstrap_offline_models()


def fetch_models_from_sdk(api_key: str, *, timeout: float | None = None) -> list[ModelInfo]:
    """Live fetch language + image-generation models via xAI SDK.

    Video, voice, and speech-to-text have no list APIs. Those rows are tagged
    by slug when they appear on either list. One list failing does not wipe
    the others. If **every** list call fails, raise so ``list_models`` can
    fixture-fallback instead of caching an empty SDK snapshot. When any of
    those failures is a deadline, that deadline is the error raised.
    ``timeout=None`` uses ``XAI_SDK_TIMEOUT_SECONDS`` when set, otherwise 180.
    """
    from xai_sdk import Client

    from xaikit.errors import timeout_for_catalog

    client = Client(api_key=api_key, timeout=timeout_for_catalog(timeout))
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
        raise _preferred_catalog_error(errors)
    return list(by_id.values())


def _bootstrap_offline_models() -> list[ModelInfo]:
    # Two current chat bands so cheapest / economy / best still differ.
    # Public under-200k rates: https://docs.x.ai/developers/models (fetched 2026-09-23).
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


# A deadline fallback is reused for this long, then the SDK is tried again.
# Other SDK failures keep the caller TTL (one hour by default).
CATALOG_TIMEOUT_RETRY_SECONDS = 60


def _is_catalog_deadline(exc: BaseException) -> bool:
    """True for ``XaiTimeoutError`` or gRPC ``DEADLINE_EXCEEDED``."""
    from xaikit.errors import XaiTimeoutError, is_grpc_deadline_exceeded

    return isinstance(exc, XaiTimeoutError) or is_grpc_deadline_exceeded(exc)


def _preferred_catalog_error(errors: list[BaseException]) -> BaseException:
    """Prefer a deadline when every SDK list failed."""
    for err in errors:
        if _is_catalog_deadline(err):
            return err
    if errors:
        return errors[0]
    return RuntimeError("Model catalog SDK lists unavailable")


def _rest_catalog_base(base_url: str | None) -> str:
    """Empty string keeps today's gRPC catalog. A non-default base uses REST."""
    if base_url is None or not str(base_url).strip():
        return ""
    from xaikit.base_url import parse_base_url

    resolved = parse_base_url(str(base_url).strip())
    if not resolved.models_over_rest:
        return ""
    return resolved.base_url


def list_models(
    *,
    force_refresh: bool = False,
    api_key: str | None = None,
    ttl_seconds: int = 3600,
    fixture_path: Path | str | None = None,
    persist_path: Path | str | None = None,
    allow_fixture_fallback: bool = True,
    base_url: str | None = None,
    sdk_timeout: float | None = None,
) -> list[ModelInfo]:
    """Return the model catalog (cached).

    Order when no inject/test-fetch: fresh memory cache → SDK if key →
    ``persist_path`` file if present → ``fixture_path`` → bootstrap.
    A fresh bootstrap or persist snapshot does not count when *api_key* is
    set — that call tries the SDK. SDK failure with fallback allowed caches
    the bootstrap pair as ``sdk-error`` for the TTL so a dead list is not
    retried on every call. An invalid ``sdk_timeout``, or an invalid
    ``XAI_SDK_TIMEOUT_SECONDS`` when ``sdk_timeout`` is omitted, raises
    ``ValueError`` before that fetch and does not write the cache. A deadline
    (``XaiTimeoutError`` or gRPC ``DEADLINE_EXCEEDED``) uses the same
    persist, fixture, and bootstrap fallbacks, cached for
    ``CATALOG_TIMEOUT_RETRY_SECONDS`` (60) on that timeout only, instead of
    the full TTL. A different timeout does not receive that fallback.
    One latest live SDK or REST snapshot is shared by every timeout.
    Each successful live load replaces it and clears every per-timeout
    fallback. A non-live result of a failed fetch (persist, fixture,
    inject, bootstrap, or ``sdk-error``, including a deadline) is cached
    only for that timeout. A deadline keeps the 60 second window. A newer
    fallback for that timeout replaces the previous one. The fallback does
    not replace a live snapshot, and a newer live snapshot hides it.
    Caller inject and an explicit fixture or persist load with no failed
    fetch still replace the one shared snapshot.

    After a successful SDK fetch, if ``persist_path`` is set, write
    ``{models: [...]}`` there (best-effort: disk errors are logged and the
    live list is still returned). No default path — omit to skip disk.
    ``clear_catalog_cache`` drops memory only; it does not delete the file.
    """
    from xaikit.errors import timeout_for_catalog

    resolved_timeout = timeout_for_catalog(sdk_timeout)

    key = (api_key or "").strip() or None
    rest_base = _rest_catalog_base(base_url)
    if not force_refresh:
        with _state.lock:
            fallback = _state.fallbacks.get(resolved_timeout)
            live = _state.live
            live_ok = live is not None and _snapshot_usable(
                live, ttl_seconds=ttl_seconds, rest_base=rest_base, key=key
            )
            fallback_ok = fallback is not None and _snapshot_usable(
                fallback, ttl_seconds=ttl_seconds, rest_base=rest_base, key=key
            )
            # A later live load wins. Equal timestamps keep the fallback:
            # a failed fetch in the same tick is stored after the live clear.
            if (
                live_ok
                and live is not None
                and fallback_ok
                and fallback is not None
                and live.fetched_at > fallback.fetched_at
            ):
                return list(live.models)
            if fallback_ok and fallback is not None:
                return list(fallback.models)
            if live_ok and live is not None:
                return list(live.models)
            shared = _state.snapshot
            own_shared = (
                _state.snapshot_timeout is None
                or _state.snapshot_timeout == resolved_timeout
            )
            if (
                shared is not None
                and own_shared
                and _snapshot_usable(
                    shared, ttl_seconds=ttl_seconds, rest_base=rest_base, key=key
                )
            ):
                return list(shared.models)

    models: list[ModelInfo] | None = None
    source: str | None = None
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
                if rest_base:
                    models = fetch_models_via_rest(key, rest_base)
                    source = "rest"
                else:
                    # Omit timeout when the caller did not pass one so a
                    # replacement fetch that only accepts the key still works.
                    # fetch_models_from_sdk applies the same env default.
                    if sdk_timeout is None:
                        models = fetch_models_from_sdk(key)
                    else:
                        models = fetch_models_from_sdk(key, timeout=resolved_timeout)
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
        if models is None and key and sdk_error is not None and allow_fixture_fallback:
            models = _bootstrap_offline_models()
            source = "sdk-error"
        elif models is None and key is None and allow_fixture_fallback:
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

    fresh_for = None
    if sdk_error is not None and _is_catalog_deadline(sdk_error):
        fresh_for = CATALOG_TIMEOUT_RETRY_SECONDS
    snap = CatalogSnapshot(
        models=models,
        fetched_at=time.time(),
        source=source,
        base_url=rest_base,
        fresh_for=fresh_for,
    )
    slot = _snapshot_slot(source, fetch_failed=sdk_error is not None)
    with _state.lock:
        if slot == "live":
            _state.live = snap
            _state.snapshot = snap
            _state.snapshot_timeout = None
            _state.fallbacks.clear()
        elif slot == "fallback":
            # Replace this timeout's entry so a newer persist, fixture, or
            # bootstrap body is not hidden by an older sdk-error.
            _state.fallbacks[resolved_timeout] = snap
            if _state.live is None:
                _state.snapshot = snap
                _state.snapshot_timeout = resolved_timeout
        else:
            _state.live = None
            _state.snapshot = snap
            _state.snapshot_timeout = None
            if source in _CALLER_CATALOG_SOURCES:
                _state.fallbacks.clear()
    return list(models)


def _is_coding_sku(model: ModelInfo) -> bool:
    """True for coding-specialized ids (grok-build-*, grok-code-*, *code-fast*)."""
    mid = (model.id or "").strip().lower().replace("_", "-")
    return bool(mid and _CODE_SKU_ID.search(mid))


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
        if slug in {ROLE_VIDEO, ROLE_VOICE, ROLE_SPEECH_TO_TEXT}:
            return False
        return ROLE_IMAGE in caps and not model.is_chat
    if role == ROLE_VIDEO:
        return slug == ROLE_VIDEO or ROLE_VIDEO in caps
    if role == ROLE_VOICE:
        # A speech-to-text slug stays out of voice even if a modality tag says voice.
        if slug == ROLE_SPEECH_TO_TEXT:
            return False
        return slug == ROLE_VOICE or ROLE_VOICE in caps
    if role == ROLE_SPEECH_TO_TEXT:
        return slug == ROLE_SPEECH_TO_TEXT or ROLE_SPEECH_TO_TEXT in caps
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


_CHAT_VERSION = re.compile(r"grok-(\d+)(?:[.-](\d+))?", re.IGNORECASE)
# Historical grok-4.20 (the Feb 2026 generation) is older than grok-4.3.
# A float parse turned 4.20 into 4.2 by accident and 4.10 into 4.1.
_HISTORICAL_4_20 = re.compile(r"grok-4[.-]20(?!\d)", re.IGNORECASE)


def _chat_major_minor(model_id: str) -> tuple[int, int]:
    """Integer ``(major, minor)`` for chat newest-sort.

    ``grok-4.10`` is ``(4, 10)`` (above 4.9). ``grok-5`` / ``grok-5.0`` is
    ``(5, 0)`` (above every 4.x). ``grok-4.20`` sorts as minor 2 so it stays
    older than ``grok-4.3``. Dashed and compact snapshot dates are removed
    first, so ``grok-4-20260530`` and ``grok-4-2026-05-30`` stay ``(4, 0)``
    and a ``grok-5`` snapshot stays ``(5, 0)``.
    """
    mid = _strip_snapshot_dates(model_id)
    matched = _CHAT_VERSION.search(mid)
    if not matched:
        return (0, 0)
    major = int(matched.group(1))
    minor = int(matched.group(2) or 0)
    if major == 4 and minor == 20 and _HISTORICAL_4_20.search(mid):
        minor = 2
    return (major, minor)


# ``preview`` as its own id segment: ``preview``, ``-preview``, or ``preview-``.
_PREVIEW_SEGMENT = re.compile(r"(?:^|-)preview(?:-|$)")


def _is_preview_id(model_id: str) -> bool:
    """True when ``preview`` is its own segment of the model id."""
    mid = (model_id or "").strip().lower().replace("_", "-")
    return _PREVIEW_SEGMENT.search(mid) is not None


def _stable_rank(model_id: str) -> int:
    """1 for a stable id, 0 for a ``-preview`` id. Higher sorts first."""
    return 0 if _is_preview_id(model_id) else 1


def _version_tuple(model: ModelInfo) -> tuple:
    mid = model.id.lower()
    is_latest_alias = mid.endswith("-latest") or mid.endswith("_latest")
    major, minor = _chat_major_minor(mid)
    is_mini = "mini" in mid
    is_fast = "fast" in mid and "non-reasoning" not in mid
    created = model.created or 0
    # After major/minor, so a newer dated-only family still beats an older
    # plain id. Before created, so a snapshot of this version does not.
    is_plain = 0 if _is_snapshot_id(mid) else 1
    return (
        # Before stable and version, so a newer or higher lite id loses best.
        _non_lite_rank(mid),
        _stable_rank(mid),
        major,
        minor,
        is_plain,
        1 if is_latest_alias else 0,
        0 if is_mini else 1,
        0 if is_fast else 1,
        _snapshot_date_key(mid),
        created,
        mid,
    )


# Snapshot markers in every role: dashed YYYY-MM-DD and compact YYYYMMDD.
# Compact counts only for a plausible calendar date. Four-digit suffixes
# such as 0309 and 0825 are not markers.
_DASHED_SNAPSHOT_DATE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
_COMPACT_SNAPSHOT_DATE = re.compile(r"(?<!\d)(\d{8})(?!\d)")


def _norm_model_id(model_id: str) -> str:
    return (model_id or "").strip().lower().replace("_", "-")


def _ymd_in_range(year: int, month: int, day: int) -> bool:
    return 2000 <= year <= 2099 and 1 <= month <= 12 and 1 <= day <= 31


def _snapshot_dates(model_id: str) -> tuple[tuple[int, int, int], ...]:
    """Calendar dates embedded in an id. Empty when the id is not a snapshot."""
    mid = _norm_model_id(model_id)
    found: list[tuple[int, int, int]] = []
    for match in _DASHED_SNAPSHOT_DATE.finditer(mid):
        year, month, day = (int(match.group(index)) for index in (1, 2, 3))
        if _ymd_in_range(year, month, day):
            found.append((year, month, day))
    for match in _COMPACT_SNAPSHOT_DATE.finditer(mid):
        raw = match.group(1)
        year, month, day = int(raw[0:4]), int(raw[4:6]), int(raw[6:8])
        if _ymd_in_range(year, month, day):
            found.append((year, month, day))
    return tuple(found)


def _is_snapshot_id(model_id: str) -> bool:
    return bool(_snapshot_dates(model_id))


def _snapshot_date_key(model_id: str) -> tuple[int, int, int]:
    """Newest calendar date in the id, or ``(0, 0, 0)`` when there is none."""
    dates = _snapshot_dates(model_id)
    if not dates:
        return (0, 0, 0)
    return max(dates)


def _strip_snapshot_dates(model_id: str) -> str:
    """Remove snapshot dates so they are not version digits."""
    mid = _norm_model_id(model_id)

    def _dashed(match: re.Match[str]) -> str:
        year, month, day = (int(match.group(index)) for index in (1, 2, 3))
        if _ymd_in_range(year, month, day):
            return "-"
        return match.group(0)

    def _compact(match: re.Match[str]) -> str:
        raw = match.group(1)
        year, month, day = int(raw[0:4]), int(raw[4:6]), int(raw[6:8])
        if _ymd_in_range(year, month, day):
            return "-"
        return match.group(0)

    stripped = _DASHED_SNAPSHOT_DATE.sub(_dashed, mid)
    return _COMPACT_SNAPSHOT_DATE.sub(_compact, stripped)


def _snapshot_family(model_id: str) -> str:
    """Family is the id with snapshot dates and a trailing ``-latest`` removed."""
    stripped = _strip_snapshot_dates(model_id)
    stripped = re.sub(r"-{2,}", "-", stripped).strip("-")
    if stripped.endswith("-latest"):
        stripped = stripped[: -len("-latest")].strip("-")
    return stripped


def _version_digits(model_id: str) -> tuple[int, ...]:
    cleaned = _strip_snapshot_dates(model_id)
    nums = [int(part) for part in re.split(r"[^0-9]+", cleaned) if part.isdigit()]
    return tuple(nums) if nums else (0,)


def _imagine_video_rest(model_id: str) -> str:
    mid = _norm_model_id(model_id)
    prefix = "grok-imagine-video"
    if mid.startswith(prefix):
        return mid[len(prefix) :].lstrip("-")
    return mid


def _imagine_video_version_nums(rest: str) -> tuple[int, ...]:
    """Version digits. Snapshot dates, ``preview``, and ``lite`` are not a version."""
    cleaned = _strip_snapshot_dates(rest)
    cleaned = re.sub(r"(?:^|-)preview(?:-|$)", "-", cleaned)
    cleaned = re.sub(r"(?:^|-)lite(?:-|$)", "-", cleaned)
    nums = [int(part) for part in re.split(r"[^0-9]+", cleaned) if part.isdigit()]
    return tuple(nums) if nums else (0,)


def _imagine_video_sort_key(model: ModelInfo) -> tuple:
    """Newest grok-imagine-video* id.

    ``-lite`` ranks below every non-lite id. A stable id then ranks above any
    ``-preview`` id, ahead of version, so ``grok-imagine-video-1.5`` beats
    ``grok-imagine-video-2.0-preview``. Dashed and compact snapshot dates are
    removed before the version compare, then the plain id ranks ahead of a
    snapshot of that same version. The plain flag stays after version so a
    newer family that only has dated ids still beats an older plain id.
    Among dated ids of one version, the newest calendar date wins, and
    ``created`` breaks only an equal-date tie. Among lite ids, the version
    digits still order them. A preview is chosen only when no stable non-lite
    id exists.
    """
    mid = _norm_model_id(model.id)
    rest = _imagine_video_rest(mid)
    is_lite = _non_lite_rank(mid)
    is_stable = _stable_rank(mid)
    is_preview = is_stable == 0
    is_snapshot = _is_snapshot_id(mid)
    is_plain = 0 if (is_preview or is_snapshot) else 1
    is_latest = 1 if rest.endswith("latest") or "-latest-" in f"-{rest}-" else 0
    created = model.created or 0
    return (
        is_lite,
        is_stable,
        _imagine_video_version_nums(rest),
        is_plain,
        is_latest,
        _snapshot_date_key(mid),
        created,
        mid,
    )


def _generic_rank_key(model: ModelInfo, role: str) -> tuple:
    """Non-lite, then stable, then created, for image, voice, and speech-to-text.

    A ``-lite`` id ranks below every non-lite id before stable, created, or
    version, same as video. Image names are product families, not numeric
    versions, so the id string breaks a created tie
    (``grok-imagine-image-quality`` above ``grok-imagine-image-2.0``). Voice
    and speech-to-text still use version digits with snapshot dates removed.
    """
    mid = _norm_model_id(model.id)
    is_latest = 1 if mid.endswith("-latest") or "-latest-" in f"-{mid}-" else 0
    created = model.created or 0
    stable = _stable_rank(mid)
    non_lite = _non_lite_rank(mid)
    if role == ROLE_IMAGE:
        return (non_lite, stable, created, is_latest, mid)
    return (non_lite, stable, created, is_latest, _version_digits(mid), mid)


def _newest_key(model: ModelInfo, role: str) -> tuple:
    """Sort key for ``best`` / prefer-latest within a role pool.

    A non-lite id ranks above any ``-lite`` id in every role, before stable,
    version, or created date. A stable id then ranks above any ``-preview``
    id. Chat uses integer major/minor, and a snapshot of that version ranks
    behind the plain id. Video uses the Imagine video key. Other roles then
    use created date. Snapshot dates are not version digits.
    """
    if role == ROLE_CHAT:
        return _version_tuple(model)
    if role == ROLE_VIDEO:
        return _imagine_video_sort_key(model)
    return _generic_rank_key(model, role)


def _dated_only_rank(model: ModelInfo) -> tuple:
    """Newest calendar date, then created, then id. Created does not pick the date."""
    return (_snapshot_date_key(model.id), model.created or 0, _norm_model_id(model.id))


def _family_representatives(pool: Sequence[ModelInfo], role: str) -> list[ModelInfo]:
    """One row per family. A snapshot loses to plain or ``-latest`` in that family only.

    A dated id stays in the pool when its family has no plain or ``-latest``
    id, so a newer dated-only family can still beat an older plain id.
    """
    groups: dict[str, list[ModelInfo]] = {}
    for model in pool:
        groups.setdefault(_snapshot_family(model.id), []).append(model)
    chosen: list[ModelInfo] = []
    for members in groups.values():
        plain = [model for model in members if not _is_snapshot_id(model.id)]
        if plain:
            chosen.append(max(plain, key=lambda model: _newest_key(model, role)))
        else:
            chosen.append(max(members, key=_dated_only_rank))
    return chosen


def _pick_latest(pool: Sequence[ModelInfo], role: str) -> ModelInfo:
    """Highest row for ``role``. Generic roles drop dominated snapshots first."""
    rows = list(pool)
    if role in (ROLE_CHAT, ROLE_VIDEO):
        return max(rows, key=lambda model: _newest_key(model, role))
    return max(_family_representatives(rows, role), key=lambda model: _newest_key(model, role))


def prefer_latest_video_model(catalog: Sequence[ModelInfo] | None = None) -> str:
    """Pick the newest ``grok-imagine-video*`` id from *catalog*.

    Uses the same video key as ``best``. A stable id beats any ``-preview``
    id, ahead of version and created date. ``-lite`` stays below every
    non-lite id. A compact or dashed snapshot of a version ranks behind the
    plain id of that version. A preview is returned only when no stable
    non-lite id is in the pool. Does not change chat resolve.
    Empty / missing catalog returns ``DEFAULT_VIDEO_MODEL``.
    """
    rows = list(catalog) if catalog is not None else []
    videos = [
        m
        for m in rows
        if _norm_model_id(m.id).startswith("grok-imagine-video")
    ]
    if not videos:
        return DEFAULT_VIDEO_MODEL
    return _pick_latest(videos, ROLE_VIDEO).id


def prefer_latest_model(
    catalog: Sequence[ModelInfo] | None = None,
    *,
    role: str | None = None,
) -> str | None:
    """Pick the stable flagship from the role pool.

    In every role a non-lite id beats any ``-lite`` id, regardless of version
    or created date, and a stable id then beats any ``-preview`` id. Preview
    is returned only when those candidates have no stable non-lite model.
    Lite is returned only when the pool has no non-lite id. A snapshot ranks
    behind the plain id or ``-latest`` alias of the same family. Chat skips
    coding SKUs when other chat rows exist.
    """
    role_n = normalize_role(role)
    pool = models_for_role(catalog, role_n)
    if not pool:
        return None
    return _pick_latest(pool, role_n).id


def _public_ranking_price(model: ModelInfo, role: str) -> float | None:
    """Public list rate for image, video, and voice.

    When one exists it wins over ``input_per_million`` for those roles.
    """
    if role == ROLE_CHAT:
        return None
    from xaikit.pricing import default_price_table

    table = default_price_table()
    key = (model.id or "").strip()
    if not key:
        return None
    price = table.price_for(key)
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

    Chat uses ``input_per_million``. For image, video, and voice, the public
    list rate wins over ``input_per_million`` when one exists. One price band
    picks the flagship. Multiple bands pick the oldest / non-reasoning model
    in the cheapest band.
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
    """Alias for prefer_latest (flagship / best quality heuristic).

    In every role a non-lite id beats any ``-lite`` id, regardless of version
    or created date, and a stable id then beats any ``-preview`` id. Preview
    is returned only when those candidates have no stable non-lite model.
    Lite is returned only when the pool has no non-lite id. A snapshot ranks
    behind the plain id or ``-latest`` alias of the same family. The date is
    not a version number, including the minor of an undotted id such as
    ``grok-4`` or ``grok-5``. Lite can still win economy and cheapest.
    """
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
    than the flagship. The same snapshot rule as ``best`` applies inside
    the cheaper band: a dated id does not beat the plain id of its family.
    Lite-last is not applied by dropping lite rows here, so a lone ``-lite``
    id in that cheaper band still wins economy.
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
    api_key: str | None = None,
    base_url: str | None = None,
    sdk_timeout: float | None = None,
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
        api_key=api_key,
        base_url=base_url,
        sdk_timeout=sdk_timeout,
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
    api_key: str | None = None,
    base_url: str | None = None,
    sdk_timeout: float | None = None,
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
            cat = list_models(api_key=api_key, base_url=base_url, sdk_timeout=sdk_timeout)
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
        snap = _published_snapshot()
    return snap.source if snap else None
