"""Optional gap log companion for XaiKit (output_gap / capability_gap).

Append-only events so product/schema/tool misses can be reviewed manually.
Default **off** — apps inject a ``GapLog`` / sink; no auto-attach to transport.
No auto Linear/GitHub issues. Never store secrets or prompts in notes.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

GapKind = Literal["output_gap", "capability_gap"]
_VALID_KINDS = frozenset({"output_gap", "capability_gap"})

# Best-effort scrub of key-like material in freeform notes (never trust model text).
_SECRETISH = re.compile(
    r"(?i)("
    r"(?:api[_-]?key|xai[_-]?api[_-]?key|authorization|bearer|secret|password|token)"
    r"\s*[:=]\s*\S+"
    r"|sk-[A-Za-z0-9_\-]{8,}"
    r"|xai-[A-Za-z0-9_\-]{8,}"
    r")"
)
_ACCOUNTISH = re.compile(r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b")

# Env used only when apps/CLI explicitly build a log from settings — not auto-wired.
GAPS_PATH_ENV = "XAIKIT_GAPS_PATH"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def scrub_gap_text(text: str, *, max_len: int = 4000) -> str:
    """Redact secret-like substrings and cap length. Freeform notes are retained."""
    if not text:
        return ""
    out = _SECRETISH.sub("[REDACTED]", text)
    out = _ACCOUNTISH.sub("[REDACTED_NUM]", out)
    if len(out) > max_len:
        out = out[: max_len - 3] + "..."
    return out


class GapEvent(BaseModel):
    """One product/schema/tool miss discovered by a reasoning path or app code."""

    timestamp: datetime = Field(default_factory=_utc_now)
    kind: GapKind = "output_gap"
    feature: str = Field(
        ...,
        min_length=1,
        description="App feature/purpose tag e.g. demo.chat, notes.propose",
    )
    job_tag: str = Field(
        default="",
        description="Optional finer job id within feature; defaults to feature when empty",
    )
    note: str = Field(
        default="",
        description="Freeform model or app text — scrubbed; never secrets/prompts dump",
    )
    code: str | None = Field(
        default=None,
        description="Optional stable app-known hole id; never invent by paraphrasing note",
    )
    model: str | None = None
    parent_id: str | None = Field(
        default=None,
        description="Optional correlation to usage / request id",
    )

    def model_post_init(self, __context: Any) -> None:
        if not (self.job_tag or "").strip():
            self.job_tag = self.feature
        # Scrub on construct so sinks never see raw secrets from callers
        self.note = scrub_gap_text(self.note or "")
        if self.code is not None:
            cleaned = scrub_gap_text(str(self.code), max_len=200).strip()
            self.code = cleaned or None


@runtime_checkable
class GapSink(Protocol):
    def append(self, event: GapEvent) -> None: ...

    def iter_events(self) -> Iterable[GapEvent]: ...


class NullGapSink:
    """Discard sink — default-off companion (no persistence)."""

    def append(self, event: GapEvent) -> None:
        return None

    def iter_events(self) -> Iterable[GapEvent]:
        return []


class InMemoryGapSink:
    """Thread-safe list sink for unit tests and ephemeral runs."""

    def __init__(self) -> None:
        self._events: list[GapEvent] = []
        self._lock = threading.Lock()

    def append(self, event: GapEvent) -> None:
        with self._lock:
            self._events.append(event)

    def iter_events(self) -> Iterable[GapEvent]:
        with self._lock:
            return list(self._events)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


class JsonlGapSink:
    """Append-only JSONL file sink (one GapEvent per line)."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def append(self, event: GapEvent) -> None:
        line = event.model_dump_json() + "\n"
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line)

    def iter_events(self) -> Iterable[GapEvent]:
        if not self.path.is_file():
            return []
        out: list[GapEvent] = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(GapEvent.model_validate_json(line))
                except Exception as exc:
                    logger.warning("Skipping corrupt gap line: %s", exc)
        return out


class CompositeGapSink:
    """Fan-out to multiple sinks (e.g. memory + file)."""

    def __init__(self, *sinks: GapSink) -> None:
        self.sinks = list(sinks)

    def append(self, event: GapEvent) -> None:
        for s in self.sinks:
            s.append(event)

    def iter_events(self) -> Iterable[GapEvent]:
        if not self.sinks:
            return []
        return self.sinks[0].iter_events()


def _normalize_kind(kind: str | None) -> GapKind:
    k = (kind or "output_gap").strip().lower()
    if k not in _VALID_KINDS:
        return "output_gap"
    return k  # type: ignore[return-value]


def _gap_note_items(raw: Any) -> list[dict[str, Any]]:
    """Extract gap dicts from a structured payload (list of objects)."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            out.append(item)
        elif hasattr(item, "model_dump"):
            try:
                dumped = item.model_dump()
                if isinstance(dumped, dict):
                    out.append(dumped)
            except Exception:
                continue
    return out


class GapLog:
    """Record gap events and query for manual triage (no auto-issue)."""

    def __init__(self, sink: GapSink | None = None) -> None:
        # Default-off: NullGapSink discards unless app injects a real sink.
        self.sink: GapSink = sink if sink is not None else NullGapSink()

    def record(
        self,
        *,
        kind: str = "output_gap",
        feature: str,
        note: str = "",
        job_tag: str | None = None,
        code: str | None = None,
        model: str | None = None,
        parent_id: str | None = None,
        timestamp: datetime | None = None,
    ) -> GapEvent:
        """Build, scrub, append, and return a GapEvent."""
        tag = (feature or "").strip()
        if not tag:
            raise ValueError("feature tag is required for gap logging")

        event = GapEvent(
            timestamp=timestamp or _utc_now(),
            kind=_normalize_kind(kind),
            feature=tag,
            job_tag=(job_tag or "").strip() or tag,
            note=note or "",
            code=code,
            model=model,
            parent_id=parent_id,
        )
        self.sink.append(event)
        return event

    def record_many(
        self,
        items: Iterable[Any],
        *,
        feature: str,
        job_tag: str | None = None,
        model: str | None = None,
        parent_id: str | None = None,
    ) -> list[GapEvent]:
        """Persist each structured gap item (dict or model_dump-able)."""
        events: list[GapEvent] = []
        for item in _gap_note_items(list(items) if not isinstance(items, list) else items):
            note = item.get("note")
            if note is None:
                note = item.get("text") or item.get("message") or ""
            events.append(
                self.record(
                    kind=str(item.get("kind") or "output_gap"),
                    feature=feature,
                    job_tag=job_tag,
                    note=str(note),
                    code=item.get("code"),
                    model=model,
                    parent_id=parent_id,
                )
            )
        return events

    def record_from_payload(
        self,
        payload: dict[str, Any] | None,
        *,
        feature: str,
        job_tag: str | None = None,
        model: str | None = None,
        parent_id: str | None = None,
        gaps_key: str = "gaps",
    ) -> list[GapEvent]:
        """If *payload* has optional gaps[], persist each as a gap log entry."""
        if not payload or not isinstance(payload, dict):
            return []
        raw = payload.get(gaps_key)
        if not raw:
            return []
        return self.record_many(
            raw,
            feature=feature,
            job_tag=job_tag,
            model=model,
            parent_id=parent_id,
        )

    def events(
        self,
        *,
        feature: str | None = None,
        job_tag: str | None = None,
        kind: str | None = None,
        code: str | None = None,
        parent_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[GapEvent]:
        """Filter stored events (all filters ANDed when set)."""
        out: list[GapEvent] = []
        kind_n = kind.strip().lower() if kind else None
        for e in self.sink.iter_events():
            if feature is not None and e.feature != feature:
                continue
            if job_tag is not None and e.job_tag != job_tag:
                continue
            if kind_n is not None and e.kind != kind_n:
                continue
            if code is not None and e.code != code:
                continue
            if parent_id is not None and e.parent_id != parent_id:
                continue
            ts = e.timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if since is not None:
                s = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
                if ts < s:
                    continue
            if until is not None:
                u = until if until.tzinfo else until.replace(tzinfo=timezone.utc)
                if ts >= u:
                    continue
            out.append(e)
        return out

    def recent(
        self,
        limit: int = 50,
        *,
        feature: str | None = None,
        kind: str | None = None,
    ) -> list[GapEvent]:
        """Newest-first dump for manual triage (no auto-issue)."""
        if limit < 1:
            return []
        ev = self.events(feature=feature, kind=kind)
        ev.sort(key=lambda e: e.timestamp, reverse=True)
        return ev[:limit]

    def count_by_code(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> dict[str, int]:
        """Optional rollup by explicit ``code`` only (never freeform notes)."""
        counts: dict[str, int] = {}
        for e in self.events(since=since, until=until):
            if not e.code:
                continue
            counts[e.code] = counts.get(e.code, 0) + 1
        return dict(sorted(counts.items()))


# --- optional process-wide gap log (apps/tests inject; default None / off) ---

_log_lock = threading.Lock()
_default_log: GapLog | None = None


def get_gap_log() -> GapLog | None:
    """Return the process gap log if set; default is off (``None``)."""
    with _log_lock:
        return _default_log


def set_gap_log(log: GapLog | None) -> None:
    """Replace the process gap log (tests/apps: inject InMemoryGapSink)."""
    global _default_log
    with _log_lock:
        _default_log = log


def reset_gap_log() -> None:
    """Clear process log (back to default-off)."""
    set_gap_log(None)


def build_gap_log(
    *,
    gaps_path: str | Path | None = None,
    in_memory: bool = False,
    from_env: bool = False,
) -> GapLog:
    """Construct a gap log for inject / CLI.

    * ``in_memory`` — force memory sink (tests).
    * ``gaps_path`` — JSONL file sink.
    * ``from_env`` — if path unset, read ``XAIKIT_GAPS_PATH`` (still off when empty).
    * Otherwise — ``NullGapSink`` (default off).
    """
    if in_memory:
        return GapLog(sink=InMemoryGapSink())

    path = gaps_path
    if path is None and from_env:
        path = (os.environ.get(GAPS_PATH_ENV) or "").strip() or None
    if path is not None:
        p = str(path).strip()
        if p:
            return GapLog(sink=JsonlGapSink(p))

    return GapLog(sink=NullGapSink())


def dump_gaps_jsonl(events: Iterable[GapEvent]) -> str:
    """Serialize events to JSONL string (review export; no secrets expected)."""
    return "".join(json.dumps(e.model_dump(mode="json")) + "\n" for e in events)


def dump_gaps_text(events: Iterable[GapEvent]) -> str:
    """Human-readable lines for CLI triage."""
    lines: list[str] = []
    for e in events:
        ts = e.timestamp.isoformat() if e.timestamp else ""
        code = e.code or "-"
        note = (e.note or "").replace("\n", " ").strip()
        lines.append(
            f"{ts}\t{e.kind}\t{e.feature}\t{e.job_tag}\t{code}\t{e.model or '-'}\t"
            f"{e.parent_id or '-'}\t{note}"
        )
    return "\n".join(lines) + ("\n" if lines else "")


def main(argv: list[str] | None = None) -> int:
    """CLI: dump recent gaps for manual triage (no auto-issue).

    Examples::

        python -m xaikit.gaps --path data/gaps.jsonl
        xaikit-gaps --limit 20 --kind capability_gap
        xaikit-gaps --json --path ./gaps.jsonl
    """
    parser = argparse.ArgumentParser(
        prog="xaikit-gaps",
        description="Dump recent XaiKit gap logs for manual triage (no auto-issue).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Max events, newest first (default 50)",
    )
    parser.add_argument("--feature", default=None, help="Filter by feature tag")
    parser.add_argument(
        "--kind",
        choices=["output_gap", "capability_gap"],
        default=None,
        help="Filter by gap kind",
    )
    parser.add_argument(
        "--path",
        default=None,
        help=f"JSONL path (default: ${GAPS_PATH_ENV}; required unless process log set)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit JSONL instead of TSV",
    )
    parser.add_argument(
        "--count-codes",
        action="store_true",
        help="Print counts by explicit code only (not freeform notes)",
    )
    args = parser.parse_args(argv)

    if args.path is not None:
        log = build_gap_log(gaps_path=args.path)
    else:
        existing = get_gap_log()
        if existing is not None:
            log = existing
        else:
            env_path = (os.environ.get(GAPS_PATH_ENV) or "").strip()
            if not env_path:
                sys.stderr.write(
                    f"No gap log path: pass --path or set {GAPS_PATH_ENV} "
                    "(gap log is default-off).\n"
                )
                return 2
            log = build_gap_log(gaps_path=env_path)

    if args.count_codes:
        counts = log.count_by_code()
        if args.as_json:
            sys.stdout.write(json.dumps(counts, indent=2) + "\n")
        else:
            for code, n in counts.items():
                sys.stdout.write(f"{n}\t{code}\n")
            if not counts:
                sys.stdout.write("(no coded gaps)\n")
        return 0

    recent = log.recent(limit=args.limit, feature=args.feature, kind=args.kind)
    if args.as_json:
        sys.stdout.write(dump_gaps_jsonl(recent))
    else:
        if not recent:
            sys.stdout.write("(no gaps)\n")
        else:
            sys.stdout.write(
                "timestamp\tkind\tfeature\tjob_tag\tcode\tmodel\tparent_id\tnote\n"
            )
            sys.stdout.write(dump_gaps_text(recent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
