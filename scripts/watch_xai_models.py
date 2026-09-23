"""Diff public xAI docs against a committed slug/resolution baseline.

Catches new model ids (Imagine 3.0) and new resolution tokens (4k) without
an API key. Does not invent knobs — it only prompts a human/kit check.

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
from collections.abc import Sequence
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
    r"\b(?:1k|2k|4k|8k|480p|720p|1080p|1440p|2160p)\b",
    re.IGNORECASE,
)

BASELINE_PATH = Path(__file__).resolve().parent / "data" / "xai_models_watch.json"

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


def diff_watch(live: dict[str, list[str]], baseline: dict[str, Any]) -> dict[str, list[str]]:
    known_slugs = {str(s).lower() for s in baseline.get("slugs") or []}
    known_res = {str(s).lower() for s in baseline.get("resolutions") or []}
    new_slugs = [s for s in live["slugs"] if s not in known_slugs]
    new_res = [s for s in live["resolutions"] if s not in known_res]
    return {"slugs": new_slugs, "resolutions": new_res}


# Slug characters, so ``grok-4`` does not count as ``grok-4.7`` (``.`` is not a ``\b``).
_TOKEN_EDGE = r"A-Za-z0-9._-"
_DECLARED_LINE = re.compile(
    r"^\s*\*\*New (?:slugs|resolutions):\*\*\s*`([^`]*)`",
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


def declared_watch_tokens(text: str) -> set[str]:
    """Tokens named on ``**New slugs:**`` / ``**New resolutions:**`` lines.

    The issue checklist mentions ``4k`` as an example. That prose is not a listing.
    """
    found: set[str] = set()
    for match in _DECLARED_LINE.finditer(text or ""):
        found.update(split_watch_tokens(match.group(1)))
    return found


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


def unlisted_watch_tokens(tokens: Sequence[str], issues: Sequence[dict[str, Any]]) -> list[str]:
    """Tokens that still need their own watch issue.

    A token is already listed when it is on a New slugs / New resolutions line,
    a whole token in the issue title, or a whole token in a comment.
    """
    declared: set[str] = set()
    loose: list[str] = []
    for issue in issues:
        declared.update(declared_watch_tokens(str(issue.get("body") or "")))
        declared.update(declared_watch_tokens(str(issue.get("title") or "")))
        loose.append(str(issue.get("title") or ""))
        loose.append(_comment_text(issue))
    haystack = "\n".join(loose)
    pending: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        key = token.strip().lower()
        if not key or key == "none" or key in seen:
            continue
        seen.add(key)
        if key in declared or token_is_listed(key, haystack):
            continue
        pending.append(key)
    return pending


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline",
        type=Path,
        default=BASELINE_PATH,
        help="Committed watch snapshot (JSON)",
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
        help="Append new_slugs / new_resolutions for Actions",
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
        "--issues-json",
        type=Path,
        default=None,
        help="Open xai-models issues (number, title, body, comments)",
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
    print(f"slugs={','.join(slugs)}")
    print(f"resolutions={','.join(resolutions)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.select_unlisted:
        return _select_unlisted(args)
    pages: dict[str, str] = {}
    for url in WATCH_URLS:
        try:
            pages[url] = fetch_text(url)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            print(f"fetch failed {url}: {exc}", file=sys.stderr)
            return 1

    live = scan_pages(pages)
    if args.write_baseline:
        args.baseline.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "source_urls": list(WATCH_URLS),
            **live,
        }
        args.baseline.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.baseline} ({len(live['slugs'])} slugs, {len(live['resolutions'])} resolutions)")
        return 0

    if not args.baseline.is_file():
        print(f"missing baseline {args.baseline}", file=sys.stderr)
        return 1

    delta = diff_watch(live, load_baseline(args.baseline))
    if args.github_output is not None:
        with args.github_output.open("a", encoding="utf-8") as fh:
            fh.write(f"new_slugs={','.join(delta['slugs'])}\n")
            fh.write(f"new_resolutions={','.join(delta['resolutions'])}\n")
            fh.write(f"has_new={'true' if delta['slugs'] or delta['resolutions'] else 'false'}\n")

    if not delta["slugs"] and not delta["resolutions"]:
        print("xAI public docs match the committed watch baseline")
        return 0

    print("New xAI public-docs signals (kit may need a knob/family/price check):")
    if delta["slugs"]:
        print("  slugs:", ", ".join(delta["slugs"]))
    if delta["resolutions"]:
        print("  resolutions:", ", ".join(delta["resolutions"]))
    print("Checklist: thought_level families, Imagine quality/resolution, video 1080p/4k, pricing.py, BOOTSTRAP_MODEL")
    print("Then add the new tokens to scripts/data/xai_models_watch.json (--write-baseline after review)")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
