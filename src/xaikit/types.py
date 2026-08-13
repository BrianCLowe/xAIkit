"""Shared response / selection types for XaiKit."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field


class CompletionResponse(BaseModel):
    """Normalized chat completion returned by :class:`XaiClient`."""

    content: str
    usage: dict[str, Any] | None = None
    model: str | None = None
    reasoning_content: str | None = None
    finish_reason: str | None = None


class StreamChunk(BaseModel):
    """One incremental chat-stream delta from :meth:`XaiClient.chat_stream`."""

    delta: str = ""
    accumulated: str = ""
    model: str | None = None
    usage: dict[str, Any] | None = None
    finish_reason: str | None = None
    reasoning_delta: str | None = None


@dataclass(frozen=True, slots=True)
class ModelSelection:
    """Resolved model id + optional thought/effort level + resolve source."""

    model_id: str
    thought_level: str | None = None
    source: str = "bootstrap"


class ModelInfo(BaseModel):
    """One row in the provider (or fixture) model catalog."""

    id: str
    display_name: str | None = None
    aliases: list[str] = Field(default_factory=list)
    version: str | None = None
    capabilities: list[str] = Field(
        default_factory=list,
        description="Tags e.g. chat, reasoning, image",
    )
    context_length: int | None = None
    input_per_million: float | None = None
    output_per_million: float | None = None
    created: int | None = None

    @property
    def is_chat(self) -> bool:
        caps = {c.lower() for c in self.capabilities}
        if not caps:
            return True
        if "embedding" in caps and "chat" not in caps and "text" not in caps:
            return False
        exclusive = {"image", "video", "voice"}
        if (caps & exclusive) and "chat" not in caps and "text" not in caps:
            return False
        return "chat" in caps or "text" in caps or "reasoning" in caps
