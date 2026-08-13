"""Usage / cost metering for XaiKit.

Optional inject: when a meter is attached to the client, billable calls auto-record
and require a purpose tag. Attribution is generic (parent_id + labels dict).
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from xaikit.pricing import PriceTable, default_price_table

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class UsageEvent(BaseModel):
    """One billable (or failed-but-tracked) xAI call."""

    timestamp: datetime = Field(default_factory=_utc_now)
    purpose: str = Field(
        ...,
        min_length=1,
        description="App purpose/job tag (app vocabulary)",
    )
    model: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    estimated_usd: float | None = None
    parent_id: str | None = Field(
        default=None,
        description="Optional parent id for attribution",
    )
    labels: dict[str, str] = Field(
        default_factory=dict,
        description="Generic attribution labels (not strategy_id)",
    )
    success: bool = True
    thought_level: str | None = None
    error: str | None = Field(
        default=None,
        description="Short error class only — never secrets or raw prompts",
    )
    modality: str | None = Field(
        default=None,
        description="Optional modality tag e.g. chat, stt, tts, imagine, video, realtime, files, embed, tokenize",
    )

    def model_post_init(self, __context: Any) -> None:
        if self.total_tokens is None:
            pt = self.prompt_tokens
            ct = self.completion_tokens
            if pt is not None or ct is not None:
                self.total_tokens = (pt or 0) + (ct or 0)


class UsageRollup(BaseModel):
    """Aggregated cost for a filter (parent, purpose, labels, period)."""

    key: str
    event_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_usd: float = 0.0
    incomplete_cost: bool = False


@runtime_checkable
class UsageSink(Protocol):
    def append(self, event: UsageEvent) -> None: ...

    def iter_events(self) -> Iterable[UsageEvent]: ...


class InMemoryUsageSink:
    """Thread-safe list sink for unit tests and ephemeral runs."""

    def __init__(self) -> None:
        self._events: list[UsageEvent] = []
        self._lock = threading.Lock()

    def append(self, event: UsageEvent) -> None:
        with self._lock:
            self._events.append(event)

    def iter_events(self) -> Iterable[UsageEvent]:
        with self._lock:
            return list(self._events)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


class JsonlUsageSink:
    """Append-only JSONL file sink (one UsageEvent per line)."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def append(self, event: UsageEvent) -> None:
        line = event.model_dump_json() + "\n"
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line)

    def iter_events(self) -> Iterable[UsageEvent]:
        if not self.path.is_file():
            return []
        out: list[UsageEvent] = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(UsageEvent.model_validate_json(line))
                except Exception as exc:
                    logger.warning("Skipping corrupt usage line: %s", exc)
        return out


class CompositeUsageSink:
    """Fan-out to multiple sinks (e.g. memory + file)."""

    def __init__(self, *sinks: UsageSink) -> None:
        self.sinks = list(sinks)

    def append(self, event: UsageEvent) -> None:
        for s in self.sinks:
            s.append(event)

    def iter_events(self) -> Iterable[UsageEvent]:
        if not self.sinks:
            return []
        return self.sinks[0].iter_events()


# xAI video usage: 1 USD = 10_000_000_000 ticks (1 cent = 100_000_000 ticks).
_USD_TICKS_PER_DOLLAR = 10_000_000_000


def _parse_usage_dict(
    usage: dict[str, Any] | None,
) -> tuple[int | None, int | None]:
    if not usage:
        return None, None
    pt = usage.get("prompt_tokens")
    ct = usage.get("completion_tokens")
    if pt is None:
        pt = usage.get("input_tokens")
    if ct is None:
        ct = usage.get("output_tokens")
    try:
        pt_i = int(pt) if pt is not None else None
    except (TypeError, ValueError):
        pt_i = None
    try:
        ct_i = int(ct) if ct is not None else None
    except (TypeError, ValueError):
        ct_i = None
    return pt_i, ct_i


def _usd_from_ticks(raw: Any) -> float | None:
    try:
        ticks = int(raw)
    except (TypeError, ValueError):
        return None
    return round(ticks / float(_USD_TICKS_PER_DOLLAR), 8)


def _duration_seconds_from_usage(usage: dict[str, Any] | None) -> float | None:
    if not usage:
        return None
    raw = usage.get("duration")
    if raw is None:
        raw = usage.get("duration_seconds")
    try:
        if raw is None:
            return None
        return float(raw)
    except (TypeError, ValueError):
        return None


class UsageMeter:
    """Record usage events and compute rollups."""

    def __init__(
        self,
        sink: UsageSink | None = None,
        price_table: PriceTable | None = None,
    ) -> None:
        self.sink: UsageSink = sink if sink is not None else InMemoryUsageSink()
        self.price_table = (
            price_table if price_table is not None else default_price_table()
        )

    def record(
        self,
        *,
        purpose: str,
        model: str,
        usage: dict[str, Any] | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
        success: bool = True,
        thought_level: str | None = None,
        error: str | None = None,
        timestamp: datetime | None = None,
        estimated_usd: float | None = None,
        modality: str | None = None,
        apply_price_table: bool = True,
    ) -> UsageEvent:
        """Build, price, append, and return a UsageEvent.

        *purpose* is required (fail loud). Prefer *usage* dict from the API;
        explicit token kwargs override it. Set *apply_price_table* False to
        record tokens without inventing USD when the public table has no rate.
        """
        tag = (purpose or "").strip()
        if not tag:
            raise ValueError("purpose tag is required for usage recording")

        pt, ct = _parse_usage_dict(usage)
        if prompt_tokens is not None:
            pt = prompt_tokens
        if completion_tokens is not None:
            ct = completion_tokens

        if estimated_usd is None and usage:
            ticks = usage.get("cost_in_usd_ticks")
            if ticks is not None:
                estimated_usd = _usd_from_ticks(ticks)

        if estimated_usd is None and apply_price_table:
            duration = _duration_seconds_from_usage(usage)
            resolution = None
            if usage:
                raw_res = usage.get("resolution")
                if raw_res is not None:
                    resolution = str(raw_res).strip() or None
            estimated_usd = self.price_table.estimate_usd(
                model,
                prompt_tokens=pt,
                completion_tokens=ct,
                duration_seconds=duration,
                resolution=resolution,
            )

        event = UsageEvent(
            timestamp=timestamp or _utc_now(),
            purpose=tag,
            model=model or "",
            prompt_tokens=pt,
            completion_tokens=ct,
            estimated_usd=estimated_usd,
            parent_id=parent_id,
            labels=dict(labels or {}),
            success=success,
            thought_level=thought_level,
            error=error,
            modality=modality,
        )
        self.sink.append(event)
        return event

    def events(
        self,
        *,
        purpose: str | None = None,
        parent_id: str | None = None,
        label: tuple[str, str] | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        success: bool | None = None,
    ) -> list[UsageEvent]:
        """Filter stored events (all filters ANDed when set)."""
        out: list[UsageEvent] = []
        for e in self.sink.iter_events():
            if purpose is not None and e.purpose != purpose:
                continue
            if parent_id is not None and e.parent_id != parent_id:
                continue
            if label is not None:
                lk, lv = label
                if e.labels.get(lk) != lv:
                    continue
            if success is not None and e.success is not success:
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

    def _rollup(self, key: str, events: Iterable[UsageEvent]) -> UsageRollup:
        r = UsageRollup(key=key)
        for e in events:
            r.event_count += 1
            if e.success:
                r.success_count += 1
            else:
                r.failure_count += 1
            r.prompt_tokens += e.prompt_tokens or 0
            r.completion_tokens += e.completion_tokens or 0
            r.total_tokens += e.total_tokens or 0
            if e.estimated_usd is None:
                r.incomplete_cost = True
            else:
                r.estimated_usd += e.estimated_usd
        r.estimated_usd = round(r.estimated_usd, 8)
        return r

    def cost_by_parent(
        self,
        parent_id: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> UsageRollup:
        ev = self.events(parent_id=parent_id, since=since, until=until)
        return self._rollup(parent_id, ev)

    def cost_by_purpose(
        self,
        purpose: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> UsageRollup:
        ev = self.events(purpose=purpose, since=since, until=until)
        return self._rollup(purpose, ev)

    def cost_for_period(
        self,
        since: datetime,
        until: datetime,
        *,
        purpose: str | None = None,
        parent_id: str | None = None,
    ) -> UsageRollup:
        ev = self.events(
            purpose=purpose,
            parent_id=parent_id,
            since=since,
            until=until,
        )
        key = f"{since.isoformat()}..{until.isoformat()}"
        return self._rollup(key, ev)

    def rollup_by_purpose(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[UsageRollup]:
        """Group all events by purpose tag."""
        buckets: dict[str, list[UsageEvent]] = {}
        for e in self.events(since=since, until=until):
            buckets.setdefault(e.purpose, []).append(e)
        return [self._rollup(k, v) for k, v in sorted(buckets.items())]

    def rollup_by_parent(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[UsageRollup]:
        """Group by parent_id (skips events with no parent)."""
        buckets: dict[str, list[UsageEvent]] = {}
        for e in self.events(since=since, until=until):
            if not e.parent_id:
                continue
            buckets.setdefault(e.parent_id, []).append(e)
        return [self._rollup(k, v) for k, v in sorted(buckets.items())]


def dump_events_jsonl(events: Iterable[UsageEvent]) -> str:
    """Serialize events to JSONL string (debug / export; no secrets)."""
    return "".join(json.dumps(e.model_dump(mode="json")) + "\n" for e in events)
