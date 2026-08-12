"""Opt-in **dev completion traces** for XaiKit (full prompt/response).

Default **off** — apps inject a ``CompletionTracer`` / sink on ``XaiClient``.
Intended for local debugging. Events retain prompts and responses (not scrubbed).
Do not point a durable production sink at this without an explicit privacy review.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class CompletionTrace(BaseModel):
    """One chat/completion exchange for offline debugging."""

    timestamp: datetime = Field(default_factory=_utc_now)
    purpose: str | None = None
    model: str | None = None
    messages: list[dict[str, str]] = Field(default_factory=list)
    system_prompt: str | None = None
    response: str | None = None
    thought_level: str | None = None
    success: bool = True
    error: str | None = None
    modality: str = "chat"
    parent_id: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)


@runtime_checkable
class TraceSink(Protocol):
    def append(self, event: CompletionTrace) -> None: ...

    def iter_events(self) -> Iterable[CompletionTrace]: ...


class NullTraceSink:
    """Discard sink — default-off companion."""

    def append(self, event: CompletionTrace) -> None:
        return None

    def iter_events(self) -> Iterable[CompletionTrace]:
        return []


class InMemoryTraceSink:
    """Thread-safe list sink for unit tests and ephemeral runs."""

    def __init__(self) -> None:
        self._events: list[CompletionTrace] = []
        self._lock = threading.Lock()

    def append(self, event: CompletionTrace) -> None:
        with self._lock:
            self._events.append(event)

    def iter_events(self) -> Iterable[CompletionTrace]:
        with self._lock:
            return list(self._events)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


class JsonlTraceSink:
    """Append-only JSONL file sink (one CompletionTrace per line)."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def append(self, event: CompletionTrace) -> None:
        line = event.model_dump_json() + "\n"
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line)

    def iter_events(self) -> Iterable[CompletionTrace]:
        if not self.path.is_file():
            return []
        out: list[CompletionTrace] = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(CompletionTrace.model_validate_json(line))
                except Exception as exc:
                    logger.warning("Skipping corrupt trace line: %s", exc)
        return out


class CompositeTraceSink:
    """Fan-out to multiple sinks (e.g. memory + file)."""

    def __init__(self, *sinks: TraceSink) -> None:
        self.sinks = list(sinks)

    def append(self, event: CompletionTrace) -> None:
        for s in self.sinks:
            s.append(event)

    def iter_events(self) -> Iterable[CompletionTrace]:
        if not self.sinks:
            return []
        return self.sinks[0].iter_events()


class CompletionTracer:
    """Record full prompt/response traces when injected into ``XaiClient``."""

    def __init__(self, sink: TraceSink | None = None) -> None:
        self.sink: TraceSink = sink if sink is not None else NullTraceSink()

    def record(
        self,
        *,
        messages: list[dict[str, str]],
        response: str | None = None,
        system_prompt: str | None = None,
        purpose: str | None = None,
        model: str | None = None,
        thought_level: str | None = None,
        success: bool = True,
        error: str | None = None,
        modality: str = "chat",
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> CompletionTrace:
        event = CompletionTrace(
            purpose=purpose,
            model=model,
            messages=[dict(m) for m in messages],
            system_prompt=system_prompt,
            response=response,
            thought_level=thought_level,
            success=success,
            error=error,
            modality=modality,
            parent_id=parent_id,
            labels=dict(labels or {}),
        )
        try:
            self.sink.append(event)
        except Exception:
            logger.exception("Failed to append completion trace (purpose=%s)", purpose)
        return event

    def iter_events(self) -> Iterable[CompletionTrace]:
        return self.sink.iter_events()


def build_completion_tracer(sink: TraceSink | None = None) -> CompletionTracer:
    """Convenience constructor (still default-off until passed to ``XaiClient``)."""
    return CompletionTracer(sink=sink)
