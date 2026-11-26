"""Diff public xAI docs against a committed slug/resolution baseline.

A new slug or resolution is reported on the first scan. A baseline id that
leaves the live docs is a first miss in scripts/data/xai_models_watch_pending.json
and is reported as a drop only after a second miss. The daily workflow commits
that file in "Commit watch pending file when the scan changes". A drop stays
quiet only when a Dropped slugs or Dropped resolutions line lists it. After a
real knob change, run --write-baseline.

    uv run python scripts/watch_xai_models.py
    uv run python scripts/watch_xai_models.py --write-baseline
    uv run python scripts/watch_xai_models.py --select-unlisted --slugs grok-4.7 --issues-json issues.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Slugs: the public model/price tables. Resolutions: Imagine pages (4k etc.).
# Release notes are not scanned — headings look like slugs (`grok-4-is-released`).
SLUG_URLS = (
    "https://docs.x.ai/developers/models",
    "https://docs.x.ai/developers/pricing",
)
RESOLUTION_URLS = (
    "https://docs.x.ai/developers/model-capabilities/images/generation",
    "https://docs.x.ai/developers/model-capabilities/video/generation",
)
WATCH_URLS = SLUG_URLS + RESOLUTION_URLS

_SLUG_STOP = frozenset(
    {
        "and",
        "api",
        "available",
        "dropped",
        "enterprise",
        "is",
        "launch",
        "live",
        "modalities",
        "models",
        "prices",
        "released",
        "the",
    }
)

_SLUG_RE = re.compile(r"\bgrok-[a-z0-9]+(?:[-._][a-z0-9]+)*", re.IGNORECASE)
_RESOL_RE = re.compile(
    r"(?<![\w.])(?:1\.5k|1k|2k|4k|8k|480p|720p|1080p|1440p|2160p)\b",
    re.IGNORECASE,
)

BASELINE_PATH = Path(__file__).resolve().parent / "data" / "xai_models_watch.json"
PENDING_PATH = Path(__file__).resolve().parent / "data" / "xai_models_watch_pending.json"
# Docs token integers: 20000 = $2 / 1M. Media integers: 800000000 = $0.08.
_TOKEN_SCALE = 10_000
_MEDIA_SCALE = 10_000_000_000
_PUBLIC_MODELS_RE = re.compile(
    r"__XAI_PUBLIC_MODELS__\s*=\s*(\{.*?\})\s*;",
    re.DOTALL,
)
_PREFERRED_CLUSTER = "us-east-1"

_UA = "xaikit-model-watch/0.1 (+https://github.com/BrianCLowe/xAIkit)"


def _looks_like_model_slug(raw: str) -> bool:
    slug = raw.strip().lower().rstrip(".,);:]")
    if not slug.startswith("grok-"):
        return False
    # Marketing / UTM collapse of dotted versions: ``highlights-grok-46`` for
    # Grok 4.6. Real SKUs use a dot (``grok-4.6``) or a hyphenated suffix
    # (``grok-4.20-0309``). Keep single-digit ids like ``grok-4``.
    if re.fullmatch(r"grok-\d{2,}", slug):
        return False
    parts = re.split(r"[-._]", slug)
    if any(p in _SLUG_STOP for p in parts):
        return False
    if re.search(r"\d", slug):
        return True
    return slug.startswith(("grok-imagine", "grok-voice", "grok-build", "grok-code"))


def extract_slugs(text: str) -> list[str]:
    found: set[str] = set()
    for match in _SLUG_RE.finditer(text or ""):
        slug = match.group(0).lower().rstrip(".,);:]")
        if _looks_like_model_slug(slug):
            found.add(slug)
    return sorted(found)


def extract_resolutions(text: str) -> list[str]:
    found = {m.group(0).lower() for m in _RESOL_RE.finditer(text or "")}
    return sorted(found)


def fetch_text(url: str, *, timeout: float = 30.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "text/html,text/plain,*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def scan_pages(
    pages: dict[str, str],
    *,
    slug_urls: tuple[str, ...] = SLUG_URLS,
    resolution_urls: tuple[str, ...] = RESOLUTION_URLS,
) -> dict[str, list[str]]:
    slugs: set[str] = set()
    resolutions: set[str] = set()
    for url, body in pages.items():
        if url in slug_urls:
            slugs.update(extract_slugs(body))
        if url in resolution_urls:
            resolutions.update(extract_resolutions(body))
    return {"slugs": sorted(slugs), "resolutions": sorted(resolutions)}


def load_baseline(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


class _PendingError(ValueError):
    """The pending file cannot be read. Callers must not write it."""


def _utc_now_stamp() -> str:
    """UTC time with seconds precision and a Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_pending(path: Path) -> dict[str, dict[str, dict[str, str]]]:
    """Load pending state. A missing file is empty. Bad files raise."""
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise _PendingError("invalid JSON") from exc
    if not isinstance(raw, dict):
        raise _PendingError("pending top level is not an object")
    unknown = [key for key in raw if key not in ("slugs", "resolutions")]
    if unknown:
        raise _PendingError("unknown pending keys")
    loaded: dict[str, dict[str, dict[str, str]]] = {}
    for side in ("slugs", "resolutions"):
        if side not in raw:
            continue
        entries = raw[side]
        if not isinstance(entries, dict):
            raise _PendingError("pending side is not an object")
        side_out: dict[str, dict[str, str]] = {}
        for token, entry in entries.items():
            if not isinstance(entry, dict):
                raise _PendingError("pending token entry is not an object")
            if "first_miss" not in entry or not isinstance(entry.get("first_miss"), str):
                raise _PendingError("pending first_miss is missing or not a string")
            extra = set(entry) - {"first_miss", "reported_at"}
            if extra:
                raise _PendingError("unknown pending token keys")
            cleaned = {"first_miss": entry["first_miss"]}
            if "reported_at" in entry:
                if not isinstance(entry["reported_at"], str):
                    raise _PendingError("pending reported_at is not a string")
                cleaned["reported_at"] = entry["reported_at"]
            side_out[str(token).lower()] = cleaned
        if side_out:
            loaded[side] = side_out
    return loaded


def dump_pending(state: Mapping[str, Mapping[str, Mapping[str, str]]]) -> str:
    """Serialize pending JSON. Empty state is exactly ``{}`` plus a newline."""
    payload: dict[str, dict[str, dict[str, str]]] = {}
    for side in ("resolutions", "slugs"):
        entries = state.get(side) or {}
        if entries:
            payload[side] = {token: dict(entries[token]) for token in entries}
    if not payload:
        return "{}\n"
    return json.dumps(payload, sort_keys=True, indent=2) + "\n"


def _write_pending(path: Path, state: Mapping[str, Mapping[str, Mapping[str, str]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_pending(state), encoding="utf-8")


def _write_scan_ok(path: Path | None, ok: bool) -> None:
    if path is None:
        return
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"scan_ok={'true' if ok else 'false'}\n")


def _baseline_list(baseline: Mapping[str, Any], key: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in baseline.get(key) or []:
        token = str(raw).lower()
        if not token or token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def _scan_side(
    pages: Mapping[str, str], urls: tuple[str, ...], key: str
) -> tuple[bool, list[str]]:
    """One side. Empty union or an extractor exception is not a scan."""
    side_pages = {url: pages.get(url, "") for url in urls}
    try:
        scanned = scan_pages(side_pages)
    except Exception:
        return False, []
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in scanned.get(key) or []:
        token = str(raw).lower()
        if not token or token in seen:
            continue
        seen.add(token)
        ordered.append(token)
    if not ordered:
        return False, []
    return True, ordered


def _apply_side(
    entries: Mapping[str, Mapping[str, str]],
    baseline_tokens: Sequence[str],
    live_tokens: Sequence[str],
    *,
    now: str,
    record_misses: bool,
) -> tuple[dict[str, dict[str, str]], list[str]]:
    """Prune, clear live tokens, and optionally record a first or second miss.

    The scan path never writes ``reported_at``. A second miss is emitted and
    left unmarked so a failed filing is retried on the next scan.
    """
    live = set(live_tokens)
    baseline_set = set(baseline_tokens)
    kept: dict[str, dict[str, str]] = {}
    for token, entry in entries.items():
        if token in baseline_set:
            kept[token] = dict(entry)
    for token in list(kept):
        if token in live:
            del kept[token]
    emitted: list[str] = []
    if record_misses:
        for token in baseline_tokens:
            if token in live or token not in baseline_set:
                continue
            entry = kept.get(token)
            if entry is None:
                kept[token] = {"first_miss": now}
            elif "reported_at" not in entry:
                emitted.append(token)
    return kept, emitted


def _store_side(
    state: dict[str, dict[str, dict[str, str]]],
    side: str,
    entries: Mapping[str, Mapping[str, str]],
) -> None:
    if entries:
        state[side] = {token: dict(entries[token]) for token in entries}
    else:
        state.pop(side, None)


def _dropped_tokens(baseline_values: Any, live_values: Sequence[str]) -> list[str]:
    """Baseline ids missing from live, lowercased, in baseline order."""
    live_norm = {str(item).lower() for item in live_values}
    dropped: list[str] = []
    seen: set[str] = set()
    for raw in baseline_values or []:
        token = str(raw).lower()
        if not token or token in seen or token in live_norm:
            continue
        seen.add(token)
        dropped.append(token)
    return dropped


def diff_watch(live: dict[str, list[str]], baseline: dict[str, Any]) -> dict[str, list[str]]:
    known_slugs = {str(s).lower() for s in baseline.get("slugs") or []}
    known_res = {str(s).lower() for s in baseline.get("resolutions") or []}
    new_slugs = [s for s in live["slugs"] if s not in known_slugs]
    new_res = [s for s in live["resolutions"] if s not in known_res]
    return {
        "slugs": new_slugs,
        "resolutions": new_res,
        "dropped_slugs": _dropped_tokens(baseline.get("slugs"), live["slugs"]),
        "dropped_resolutions": _dropped_tokens(baseline.get("resolutions"), live["resolutions"]),
    }


# Slug characters, so ``grok-4`` does not count as ``grok-4.7`` (``.`` is not a ``\b``).
_TOKEN_EDGE = r"A-Za-z0-9._-"
_NEW_DECLARED_LINE = re.compile(
    r"^\s*\*\*New (?:slugs|resolutions):\*\*\s*`([^`]*)`",
    re.IGNORECASE | re.MULTILINE,
)
_DECLARED_LINE = re.compile(
    r"^\s*\*\*(?:New|Dropped) (?:slugs|resolutions):\*\*\s*`([^`]*)`",
    re.IGNORECASE | re.MULTILINE,
)
_DROPPED_DECLARED_LINE = re.compile(
    r"^\s*\*\*Dropped (?:slugs|resolutions):\*\*\s*`([^`]*)`",
    re.IGNORECASE | re.MULTILINE,
)


def split_watch_tokens(raw: str) -> list[str]:
    """Comma list from Actions output. ``none`` and blanks drop out."""
    out: list[str] = []
    for part in (raw or "").split(","):
        token = part.strip().lower()
        if token and token != "none":
            out.append(token)
    return out


def token_is_listed(token: str, text: str) -> bool:
    """True when ``token`` appears as a whole slug/resolution in ``text``."""
    raw = (token or "").strip()
    if not raw or not text:
        return False
    pattern = rf"(?<![{_TOKEN_EDGE}]){re.escape(raw)}(?![{_TOKEN_EDGE}])"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def _line_tokens(text: str, pattern: re.Pattern[str]) -> set[str]:
    found: set[str] = set()
    for match in pattern.finditer(text or ""):
        found.update(split_watch_tokens(match.group(1)))
    return found


def declared_watch_tokens(text: str) -> set[str]:
    """Tokens named on New or Dropped slugs/resolutions lines.

    The issue checklist mentions ``4k`` as an example. That prose is not a listing.
    """
    return _line_tokens(text, _DECLARED_LINE)


def _comment_text(issue: dict[str, Any]) -> str:
    raw = issue.get("comments")
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        parts: list[str] = []
        for item in raw:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("body") or ""))
        return "\n".join(parts)
    return ""


def unlisted_watch_tokens(
    tokens: Sequence[str],
    issues: Sequence[dict[str, Any]],
    *,
    dropped: bool = False,
) -> list[str]:
    """Tokens that still need their own watch issue.

    New tokens use the base rule: a New slugs/resolutions line, a whole token
    in an issue title, or a whole token in a comment. Dropped tokens are
    declared only by a Dropped slugs or Dropped resolutions line in an issue
    body. A New line, a title, a comment, or a guard issue does not declare
    a dropped token.
    """
    declared: set[str] = set()
    loose: list[str] = []
    for issue in issues:
        body = str(issue.get("body") or "")
        if dropped:
            declared.update(_line_tokens(body, _DROPPED_DECLARED_LINE))
            continue
        title = str(issue.get("title") or "")
        declared.update(_line_tokens(body, _NEW_DECLARED_LINE))
        declared.update(_line_tokens(title, _NEW_DECLARED_LINE))
        loose.append(title)
        loose.append(_comment_text(issue))
    haystack = "\n".join(loose)
    pending: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        key = token.strip().lower()
        if not key or key == "none" or key in seen:
            continue
        seen.add(key)
        if key in declared or (not dropped and token_is_listed(key, haystack)):
            continue
        pending.append(key)
    return pending


def _usd_per_million(raw: Any) -> float | None:
    """USD per 1M tokens. ``0`` is a real rate. Missing values stay unset."""
    if raw is None or raw == "":
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return round(value / float(_TOKEN_SCALE), 8)


def _media_unit(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    if value == 0:
        return None
    return value / float(_MEDIA_SCALE)


def _usd_media(raw: Any) -> float | None:
    value = _media_unit(raw)
    if value is None:
        return None
    return round(value, 8)


def _resolution_key(raw: str) -> str:
    text = (raw or "").strip().lower()
    text = text.replace("video_resolution_", "")
    text = text.replace("image_resolution_", "")
    return text


def _put_price(models: dict[str, dict[str, Any]], name: str, row: dict[str, Any]) -> None:
    key = (name or "").strip()
    if not key or key in models or not row:
        return
    models[key] = row


def _language_price(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    mapping = (
        ("input_per_million", "promptTextTokenPrice"),
        ("output_per_million", "completionTextTokenPrice"),
        ("cached_input_per_million", "cachedPromptTokenPrice"),
        ("image_token_per_million", "promptImageTokenPrice"),
        ("input_long_per_million", "promptTextTokenPriceLongContext"),
        ("output_long_per_million", "completionTokenPriceLongContext"),
        ("cached_input_long_per_million", "cachedPromptTokenPriceLongContext"),
    )
    for dest, src in mapping:
        if row.get(src) in (None, ""):
            continue
        price = _usd_per_million(row.get(src))
        if price is not None:
            out[dest] = price
    # ModelPrice requires both token sides. A missing side is an incomplete
    # row (skip it). A documented 0 is free and must still be written.
    if "input_per_million" not in out or "output_per_million" not in out:
        return {}
    return out


def _image_quality_token(item: dict[str, Any]) -> str:
    raw = item.get("quality")
    if raw is None:
        return ""
    return str(raw).strip().lower()


def _one_k_per_image_usd(row: dict[str, Any]) -> float | None:
    """1K Low pricePerImage, else no-quality 1K when no 1K row has a quality."""
    low_price: float | None = None
    bare_price: float | None = None
    saw_quality = False
    for item in row.get("resolutionPricing") or []:
        if not isinstance(item, dict):
            continue
        if _resolution_key(str(item.get("resolution") or "")) != "1k":
            continue
        token = _image_quality_token(item)
        price = _usd_media(item.get("pricePerImage"))
        if token:
            saw_quality = True
        if token == "low":
            if low_price is None and price is not None:
                low_price = price
        elif token == "" and bare_price is None and price is not None:
            bare_price = price
    if low_price is not None:
        return low_price
    if saw_quality:
        return None
    return bare_price


def _image_price(row: dict[str, Any]) -> dict[str, Any]:
    per_call = _one_k_per_image_usd(row)
    if per_call is None:
        per_call = _usd_media(row.get("imagePrice"))
    if per_call is None:
        return {}
    return {
        "input_per_million": 0.0,
        "output_per_million": 0.0,
        "per_call_usd": per_call,
    }


def _video_price(row: dict[str, Any]) -> dict[str, Any]:
    by_res: dict[str, float] = {}
    for item in row.get("resolutionPricing") or []:
        if not isinstance(item, dict):
            continue
        key = _resolution_key(str(item.get("resolution") or ""))
        price = _usd_media(item.get("pricePerSecond"))
        if key and price is not None:
            by_res[key] = price
    if not by_res:
        return {}
    default = by_res.get("480p", next(iter(by_res.values())))
    return {
        "input_per_million": 0.0,
        "output_per_million": 0.0,
        "per_second_usd": default,
        "per_second_usd_by_resolution": by_res,
    }


def _audio_price(row: dict[str, Any]) -> dict[str, Any]:
    endpoints = row.get("endpoints") or []
    pricing: dict[str, Any] = {}
    for endpoint in endpoints:
        if isinstance(endpoint, dict) and isinstance(endpoint.get("pricing"), dict):
            pricing = endpoint["pricing"]
            break
    per_second = _media_unit(pricing.get("realtimeAudioSecondPrice"))
    if per_second is not None:
        return {
            "input_per_million": 0.0,
            "output_per_million": 0.0,
            "per_minute_usd": round(per_second * 60.0, 8),
        }
    streaming = _media_unit(pricing.get("perAudioSecondStreaming"))
    if streaming is not None:
        return {
            "input_per_million": 0.0,
            "output_per_million": 0.0,
            "per_minute_usd": round(streaming * 60.0, 8),
        }
    return {}


def _load_public_models(pages: dict[str, str]) -> dict[str, Any] | None:
    for url in SLUG_URLS:
        body = pages.get(url) or ""
        match = _PUBLIC_MODELS_RE.search(body)
        if not match:
            continue
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def extract_public_prices(pages: dict[str, str]) -> dict[str, Any]:
    """Rates from the docs ``__XAI_PUBLIC_MODELS__`` blob.

    ``us-east-1`` wins when the same id is listed in more than one cluster.
    Speech-to-text streaming is also stored under the meter key ``stt``.
    """
    blob = _load_public_models(pages)
    models: dict[str, dict[str, Any]] = {}
    stt_rate: float | None = None
    if blob:
        clusters = list(blob.get("clusterConfigs") or [])
        clusters.sort(key=lambda row: 0 if row.get("clusterName") == _PREFERRED_CLUSTER else 1)
        for cluster in clusters:
            if not isinstance(cluster, dict):
                continue
            for row in cluster.get("languageModels") or []:
                if isinstance(row, dict):
                    _put_price(models, str(row.get("name") or ""), _language_price(row))
            for row in cluster.get("imageGenerationModels") or []:
                if isinstance(row, dict):
                    _put_price(models, str(row.get("name") or ""), _image_price(row))
                    for alias in row.get("aliases") or []:
                        _put_price(models, str(alias), _image_price(row))
            for row in cluster.get("videoGenerationModels") or []:
                if isinstance(row, dict):
                    _put_price(models, str(row.get("name") or ""), _video_price(row))
                    for alias in row.get("aliases") or []:
                        _put_price(models, str(alias), _video_price(row))
            for row in cluster.get("audioModels") or []:
                if not isinstance(row, dict):
                    continue
                priced = _audio_price(row)
                name = str(row.get("name") or "")
                _put_price(models, name, priced)
                for alias in row.get("aliases") or []:
                    _put_price(models, str(alias), priced)
                if stt_rate is None and name.startswith("grok-voice-transcribe"):
                    minute = priced.get("per_minute_usd")
                    if isinstance(minute, (int, float)):
                        stt_rate = float(minute)
    if stt_rate is not None and "stt" not in models:
        models["stt"] = {
            "input_per_million": 0.0,
            "output_per_million": 0.0,
            "per_minute_usd": stt_rate,
        }
    ordered = {key: models[key] for key in sorted(models)}
    return {
        "source_url": "https://docs.x.ai/developers/models",
        "cluster_preference": _PREFERRED_CLUSTER,
        "models": ordered,
    }


def write_public_prices(path: Path, pages: dict[str, str]) -> bool | None:
    """Write the gap file.

    Return True when the bytes changed, False when they matched, None when
    the extract had no models. None leaves an existing file untouched so a
    docs HTML change cannot wipe the committed rates.
    """
    payload = extract_public_prices(pages)
    if not payload.get("models"):
        print(
            "refusing to write an empty public price extract; gap file left untouched",
            file=sys.stderr,
        )
        return None
    text = json.dumps(payload, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = path.read_text(encoding="utf-8") if path.is_file() else None
    if previous == text:
        return False
    path.write_text(text, encoding="utf-8")
    return True


class GuardResult:
    """Shipped image ids missing from a watcher extract, or present at another rate."""

    def __init__(self, ok: bool, ids: tuple[str, ...]) -> None:
        self.ok = ok
        self.ids = ids


def check_shipped_image_prices(
    extract: dict, shipped: Mapping[str, float]
) -> GuardResult:
    """Compare watcher output to shipped grok-imagine-image per-call defaults.

    A shipped id fails when the extract has no row or a different per_call_usd.
    Extra extract ids, including drops that are not shipped defaults, are ignored.
    """
    models = extract.get("models") if isinstance(extract, dict) else None
    if not isinstance(models, dict):
        models = {}
    bad: list[str] = []
    for model_id, rate in shipped.items():
        row = models.get(model_id)
        got = row.get("per_call_usd") if isinstance(row, dict) else None
        if got is None or float(got) != float(rate):
            bad.append(str(model_id))
    return GuardResult(ok=not bad, ids=tuple(bad))


def guard_issue_text(result: GuardResult) -> tuple[str, str]:
    """Title and body for the xai-models issue. Both name each failing id."""
    if result.ok:
        return (
            "xAI shipped image prices match the watcher extract",
            "No shipped image ids are missing or mismatched.",
        )
    listed = ", ".join(result.ids)
    title = f"xAI shipped image price guard failed: {listed}"
    lines = "\n".join(f"- {model_id}" for model_id in result.ids)
    body = (
        "The watcher extract is missing a shipped image id "
        "or its per_call_usd does not match the shipped default.\n\n"
        f"{lines}\n"
    )
    return title, body


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_PYTEST_FAILED_RE = re.compile(r"^FAILED\s+(\S+)", re.MULTILINE)


def parse_pytest_failing_nodes(log: str) -> tuple[str, ...]:
    """Return pytest node ids from FAILED lines, in first-seen order.

    The parameter suffix stays on the node id. ANSI color is stripped so a
    colored log yields the same ids as a plain one.
    """
    text = _ANSI_RE.sub("", log)
    found: list[str] = []
    seen: set[str] = set()
    for match in _PYTEST_FAILED_RE.finditer(text):
        node = match.group(1)
        if node in seen:
            continue
        seen.add(node)
        found.append(node)
    return tuple(found)


def guard_diagnostic_text(
    result: GuardResult, failing_nodes: Sequence[str]
) -> tuple[str, str]:
    """Title and body when pytest failed during the price guard.

    Id-check-only failures stay on guard_issue_text. A clean id check is
    described as a pytest failure, not as missing shipped ids, and the first
    failing node is named. A failed id check names those ids and the node ids.
    """
    nodes = tuple(failing_nodes)
    if result.ok:
        title = "xAI shipped image price guard failed: pytest"
        lines = [
            "This is a pytest failure, not missing shipped image ids.",
            "The shipped image id check passed: no shipped image id is missing or mismatched.",
            "",
        ]
        if nodes:
            lines.append(f"First failing test: {nodes[0]}")
            if len(nodes) > 1:
                lines.append("")
                lines.append("Later failing tests:")
                lines.extend(f"- {node}" for node in nodes[1:])
        else:
            lines.append("First failing test: (none captured)")
        return title, "\n".join(lines) + "\n"

    listed = ", ".join(result.ids)
    title = (
        f"xAI shipped image price guard failed: {listed}"
        if listed
        else "xAI shipped image price guard failed"
    )
    lines = [
        "The shipped image price guard failed pytest and the shipped image id check.",
        "",
        "Failing shipped image ids:",
    ]
    if result.ids:
        lines.extend(f"- {model_id}" for model_id in result.ids)
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("Failing pytest node ids:")
    if nodes:
        lines.extend(f"- {node}" for node in nodes)
    else:
        lines.append("- (none captured)")
    return title, "\n".join(lines) + "\n"


def _shipped_image_per_call() -> dict[str, float]:
    from xaikit.pricing import default_price_table

    shipped: dict[str, float] = {}
    for model_id, price in default_price_table().models.items():
        if str(model_id).startswith("grok-imagine-image") and price.per_call_usd is not None:
            shipped[str(model_id)] = float(price.per_call_usd)
    return shipped


def _run_price_guard(args: argparse.Namespace) -> int:
    path: Path = args.guard_prices
    extract: dict[str, Any] = {}
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raw = {}
        if isinstance(raw, dict):
            extract = raw
    result = check_shipped_image_prices(extract, _shipped_image_per_call())
    pytest_rc = args.pytest_exit_code
    pytest_failed = pytest_rc not in (None, 0)
    if pytest_failed:
        nodes: tuple[str, ...] = ()
        log_path = args.pytest_log
        if isinstance(log_path, Path) and log_path.is_file():
            nodes = parse_pytest_failing_nodes(
                log_path.read_text(encoding="utf-8", errors="replace")
            )
        title, body = guard_diagnostic_text(result, nodes)
        step_ok = False
    else:
        title, body = guard_issue_text(result)
        step_ok = result.ok
    print(title)
    print(body)
    if args.github_output is not None:
        with args.github_output.open("a", encoding="utf-8") as fh:
            fh.write(f"guard_ok={'true' if step_ok else 'false'}\n")
            fh.write(f"guard_ids={','.join(result.ids)}\n")
            fh.write(f"guard_title={title}\n")
            fh.write("guard_body<<XAIkit_GUARD_BODY\n")
            fh.write(body if body.endswith("\n") else body + "\n")
            fh.write("XAIkit_GUARD_BODY\n")
    return 0 if step_ok else 1


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline",
        type=Path,
        default=BASELINE_PATH,
        help="Committed watch snapshot (JSON)",
    )
    parser.add_argument(
        "--pending",
        type=Path,
        default=PENDING_PATH,
        help="Pending first-miss file (JSON)",
    )
    parser.add_argument(
        "--mark-reported",
        action="store_true",
        help="Set reported_at on dropped tokens already pending, then exit",
    )
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="Overwrite the snapshot with today's public-docs scan",
    )
    parser.add_argument(
        "--github-output",
        type=Path,
        default=None,
        help="Append new and dropped slug/resolution outputs for Actions",
    )
    parser.add_argument(
        "--select-unlisted",
        action="store_true",
        help="Print slugs/resolutions not already listed on open watch issues",
    )
    parser.add_argument("--slugs", default="", help="Comma-separated slugs to filter")
    parser.add_argument(
        "--resolutions",
        default="",
        help="Comma-separated resolution tokens to filter",
    )
    parser.add_argument(
        "--dropped-slugs",
        default="",
        help="Comma-separated dropped slugs to filter",
    )
    parser.add_argument(
        "--dropped-resolutions",
        default="",
        help="Comma-separated dropped resolution tokens to filter",
    )
    parser.add_argument(
        "--issues-json",
        type=Path,
        default=None,
        help="Open xai-models issues (number, title, body, comments)",
    )
    parser.add_argument(
        "--write-prices",
        type=Path,
        default=None,
        help="Write scripts/data/xai_public_prices.json from the docs blob",
    )
    parser.add_argument(
        "--guard-prices",
        type=Path,
        default=None,
        help="Check a watcher price extract against shipped image defaults",
    )
    parser.add_argument(
        "--pytest-log",
        type=Path,
        default=None,
        help="Pytest log captured by the price-guard step",
    )
    parser.add_argument(
        "--pytest-exit-code",
        type=int,
        default=None,
        help="Pytest exit code captured by the price-guard step",
    )
    return parser.parse_args(argv)


def _load_issues(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8") or "[]")
    if not isinstance(raw, list):
        return []
    return [row for row in raw if isinstance(row, dict)]


def _select_unlisted(args: argparse.Namespace) -> int:
    issues = _load_issues(args.issues_json)
    slugs = unlisted_watch_tokens(split_watch_tokens(args.slugs), issues)
    resolutions = unlisted_watch_tokens(split_watch_tokens(args.resolutions), issues)
    dropped_slugs = unlisted_watch_tokens(
        split_watch_tokens(args.dropped_slugs),
        issues,
        dropped=True,
    )
    dropped_resolutions = unlisted_watch_tokens(
        split_watch_tokens(args.dropped_resolutions),
        issues,
        dropped=True,
    )
    has_dropped = bool(dropped_slugs or dropped_resolutions)
    print(f"slugs={','.join(slugs)}")
    print(f"resolutions={','.join(resolutions)}")
    print(f"dropped_slugs={','.join(dropped_slugs)}")
    print(f"dropped_resolutions={','.join(dropped_resolutions)}")
    print(f"has_dropped={'true' if has_dropped else 'false'}")
    return 0


def _mark_reported(args: argparse.Namespace) -> int:
    """Set reported_at on tokens already pending. Does not fetch or scan."""
    slugs = split_watch_tokens(args.dropped_slugs)
    resolutions = split_watch_tokens(args.dropped_resolutions)
    path: Path = args.pending
    if not slugs and not resolutions:
        return 0
    try:
        state = load_pending(path)
    except _PendingError:
        print(f"pending file is malformed {path}", file=sys.stderr)
        _write_scan_ok(args.github_output, False)
        return 1
    now: str | None = None
    changed = False
    for side, tokens in (("slugs", slugs), ("resolutions", resolutions)):
        entries = state.get(side)
        if not entries:
            continue
        for token in tokens:
            entry = entries.get(token)
            if entry is None or "reported_at" in entry:
                continue
            if now is None:
                now = _utc_now_stamp()
            entry["reported_at"] = now
            changed = True
    if changed:
        _write_pending(path, state)
    return 0


def _format_pending_ids(tokens: set[str]) -> str:
    if not tokens:
        return "none"
    return ",".join(sorted(tokens))


def _pending_watch_line(
    pending: Mapping[str, Mapping[str, Mapping[str, str]]],
    first_miss: set[tuple[str, str]],
    *,
    slug_ok: bool,
    res_ok: bool,
) -> str:
    """Name this scan's first misses, then other pending ids on scanned sides."""
    scanned = {
        side
        for side, ok in (("slugs", slug_ok), ("resolutions", res_ok))
        if ok
    }
    first: set[str] = set()
    still: set[str] = set()
    for side in ("slugs", "resolutions"):
        if side not in scanned:
            continue
        for token in pending.get(side) or {}:
            if (side, token) in first_miss:
                first.add(token)
            else:
                still.add(token)
    return (
        "xAI public docs watch pending: "
        f"first-miss {_format_pending_ids(first)}; "
        f"still-absent {_format_pending_ids(still)}"
    )


def _write_watch_outputs(
    path: Path | None,
    *,
    new_slugs: Sequence[str],
    new_resolutions: Sequence[str],
    dropped_slugs: Sequence[str],
    dropped_resolutions: Sequence[str],
    scan_ok: bool,
) -> tuple[bool, bool]:
    has_new = bool(new_slugs or new_resolutions)
    has_dropped = bool(dropped_slugs or dropped_resolutions)
    if path is None:
        return has_new, has_dropped
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"new_slugs={','.join(new_slugs)}\n")
        handle.write(f"new_resolutions={','.join(new_resolutions)}\n")
        handle.write(f"has_new={'true' if has_new else 'false'}\n")
        handle.write(f"dropped_slugs={','.join(dropped_slugs)}\n")
        handle.write(f"dropped_resolutions={','.join(dropped_resolutions)}\n")
        handle.write(f"has_dropped={'true' if has_dropped else 'false'}\n")
        handle.write(f"scan_ok={'true' if scan_ok else 'false'}\n")
    return has_new, has_dropped


def _read_prices(args: argparse.Namespace, pages: Mapping[str, str]) -> bool:
    if args.write_prices is None:
        return False
    changed = write_public_prices(args.write_prices, pages)
    if changed is None:
        return True
    print(f"{'updated' if changed else 'unchanged'} {args.write_prices}")
    return False


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.select_unlisted:
        return _select_unlisted(args)
    if args.guard_prices is not None:
        return _run_price_guard(args)
    if args.mark_reported:
        return _mark_reported(args)
    try:
        pending = load_pending(args.pending)
    except _PendingError:
        print(f"pending file is malformed {args.pending}", file=sys.stderr)
        _write_scan_ok(args.github_output, False)
        return 1

    pages: dict[str, str] = {}
    for url in WATCH_URLS:
        try:
            pages[url] = fetch_text(url)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            print(f"fetch failed {url}: {exc}", file=sys.stderr)
            _write_scan_ok(args.github_output, False)
            return 1

    slug_ok, slug_tokens = _scan_side(pages, SLUG_URLS, "slugs")
    res_ok, res_tokens = _scan_side(pages, RESOLUTION_URLS, "resolutions")
    prices_failed = _read_prices(args, pages)
    if not slug_ok and not res_ok:
        _write_watch_outputs(
            args.github_output,
            new_slugs=(),
            new_resolutions=(),
            dropped_slugs=(),
            dropped_resolutions=(),
            scan_ok=False,
        )
        return 1

    now = _utc_now_stamp()
    if args.write_baseline:
        old_slugs: list[Any] = []
        old_resolutions: list[Any] = []
        if (not slug_ok or not res_ok) and args.baseline.is_file():
            old = load_baseline(args.baseline)
            old_slugs = list(old.get("slugs") or [])
            old_resolutions = list(old.get("resolutions") or [])
        payload = {
            "source_urls": list(WATCH_URLS),
            "slugs": slug_tokens if slug_ok else old_slugs,
            "resolutions": res_tokens if res_ok else old_resolutions,
        }
        args.baseline.parent.mkdir(parents=True, exist_ok=True)
        args.baseline.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(
            f"wrote {args.baseline} "
            f"({len(payload['slugs'])} slugs, {len(payload['resolutions'])} resolutions)"
        )
        if slug_ok:
            kept, _emitted = _apply_side(
                pending.get("slugs") or {},
                slug_tokens,
                slug_tokens,
                now=now,
                record_misses=False,
            )
            _store_side(pending, "slugs", kept)
        if res_ok:
            kept, _emitted = _apply_side(
                pending.get("resolutions") or {},
                res_tokens,
                res_tokens,
                now=now,
                record_misses=False,
            )
            _store_side(pending, "resolutions", kept)
        _write_pending(args.pending, pending)
        _write_scan_ok(args.github_output, True)
        return 1 if prices_failed else 0

    if not args.baseline.is_file():
        print(f"missing baseline {args.baseline}", file=sys.stderr)
        _write_scan_ok(args.github_output, False)
        return 1

    baseline = load_baseline(args.baseline)
    base_slugs = _baseline_list(baseline, "slugs")
    base_resolutions = _baseline_list(baseline, "resolutions")
    live_view = {
        "slugs": slug_tokens if slug_ok else base_slugs,
        "resolutions": res_tokens if res_ok else base_resolutions,
    }
    delta = diff_watch(live_view, baseline)
    first_miss: set[tuple[str, str]] = set()
    if slug_ok:
        before_slugs = pending.get("slugs") or {}
        kept, dropped_slugs = _apply_side(
            before_slugs,
            base_slugs,
            slug_tokens,
            now=now,
            record_misses=True,
        )
        first_miss.update(("slugs", token) for token in kept if token not in before_slugs)
        _store_side(pending, "slugs", kept)
        new_slugs = delta["slugs"]
    else:
        dropped_slugs = []
        new_slugs = []
    if res_ok:
        before_res = pending.get("resolutions") or {}
        kept, dropped_resolutions = _apply_side(
            before_res,
            base_resolutions,
            res_tokens,
            now=now,
            record_misses=True,
        )
        first_miss.update(
            ("resolutions", token) for token in kept if token not in before_res
        )
        _store_side(pending, "resolutions", kept)
        new_resolutions = delta["resolutions"]
    else:
        dropped_resolutions = []
        new_resolutions = []

    has_new, has_dropped = _write_watch_outputs(
        args.github_output,
        new_slugs=new_slugs,
        new_resolutions=new_resolutions,
        dropped_slugs=dropped_slugs,
        dropped_resolutions=dropped_resolutions,
        scan_ok=True,
    )
    _write_pending(args.pending, pending)

    pending_line = _pending_watch_line(
        pending, first_miss, slug_ok=slug_ok, res_ok=res_ok
    )
    # An empty classification is "none; none". Do not print that line.
    # Failed-side carry-over is not first-miss or still-absent.
    scanned_has_pending = pending_line != (
        "xAI public docs watch pending: first-miss none; still-absent none"
    )
    if scanned_has_pending:
        print(pending_line)
    elif not has_new and not has_dropped:
        print("xAI public docs match the committed watch baseline")
    if not slug_ok:
        print("xAI public docs watch unscanned: slugs skipped")
    if not res_ok:
        print("xAI public docs watch unscanned: resolutions skipped")

    if not has_new and not has_dropped:
        return 1 if prices_failed else 0

    if has_new:
        print("New xAI public-docs signals (kit may need a knob/family/price check):")
        if new_slugs:
            print("  slugs:", ", ".join(new_slugs))
        if new_resolutions:
            print("  resolutions:", ", ".join(new_resolutions))
        print("Checklist: thought_level families, Imagine quality/resolution, video 1080p/4k, pricing.py, BOOTSTRAP_MODEL")
        print("Then add the new tokens to scripts/data/xai_models_watch.json (--write-baseline after review)")
    if has_dropped:
        print("Dropped xAI public-docs tokens (baseline ids missing from the live scan):")
        if dropped_slugs:
            print("  dropped slugs:", ", ".join(dropped_slugs))
        if dropped_resolutions:
            print("  dropped resolutions:", ", ".join(dropped_resolutions))
    return 1 if prices_failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
