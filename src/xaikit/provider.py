"""Chat provider abstraction for XaiKit.

Live path uses the xAI SDK. Offline tests inject :class:`MockChatProvider`.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass
class ProviderResponse:
    """Normalized completion from any provider implementation."""

    content: str
    usage: dict[str, Any] | None = None
    model: str | None = None
    raw: Any = None
    reasoning_content: str | None = None
    finish_reason: str | None = None


@dataclass
class ProviderStreamChunk:
    """One incremental stream piece from :meth:`ChatProvider.stream`."""

    delta: str
    accumulated: str
    usage: dict[str, Any] | None = None
    finish_reason: str | None = None
    reasoning_delta: str | None = None
    raw: Any = None


@runtime_checkable
class ChatProvider(Protocol):
    """Minimal surface XaiClient needs for chat / JSON / stream completion."""

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        thought_level: str | None = None,
        system_prompt: str | None = None,
    ) -> ProviderResponse: ...

    def stream(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        thought_level: str | None = None,
        system_prompt: str | None = None,
    ) -> Iterator[ProviderStreamChunk]: ...


def _build_sdk_messages(
    messages: list[dict[str, str]],
    *,
    system_prompt: str | None,
) -> list[Any]:
    from xai_sdk.chat import assistant, system, user

    chat_messages: list[Any] = []
    if system_prompt:
        chat_messages.append(system(system_prompt))
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "user":
            chat_messages.append(user(content))
        else:
            chat_messages.append(assistant(content))
    return chat_messages


def _sdk_chat_kwargs(
    *,
    model: str,
    temperature: float,
    max_tokens: int | None,
    thought_level: str | None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if thought_level:
        kwargs["reasoning_effort"] = thought_level
    return kwargs


def _usage_from_sdk(obj: Any) -> dict[str, Any] | None:
    usage_obj = getattr(obj, "usage", None)
    if not usage_obj:
        return None
    prompt = getattr(usage_obj, "prompt_tokens", None)
    completion = getattr(usage_obj, "completion_tokens", None)
    if prompt is None and completion is None:
        return None
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
    }


class SdkChatProvider:
    """Thin adapter over ``xai_sdk.Client`` (production path)."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        thought_level: str | None = None,
        system_prompt: str | None = None,
    ) -> ProviderResponse:
        chat_messages = _build_sdk_messages(messages, system_prompt=system_prompt)
        kwargs = _sdk_chat_kwargs(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            thought_level=thought_level,
        )
        chat = self._client.chat.create(messages=chat_messages, **kwargs)
        response = chat.sample()
        text = getattr(response, "content", "") or ""
        if isinstance(text, (list, tuple)):
            text = "".join(str(part) for part in text)

        usage = _usage_from_sdk(response)
        reasoning = getattr(response, "reasoning_content", None) or ""
        if isinstance(reasoning, (list, tuple)):
            reasoning = "".join(str(part) for part in reasoning)
        finish = getattr(response, "finish_reason", None)
        return ProviderResponse(
            content=str(text),
            usage=usage,
            model=model,
            raw=response,
            reasoning_content=str(reasoning) if reasoning else None,
            finish_reason=str(finish) if finish is not None else None,
        )

    def stream(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        thought_level: str | None = None,
        system_prompt: str | None = None,
    ) -> Iterator[ProviderStreamChunk]:
        chat_messages = _build_sdk_messages(messages, system_prompt=system_prompt)
        kwargs = _sdk_chat_kwargs(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            thought_level=thought_level,
        )
        chat = self._client.chat.create(messages=chat_messages, **kwargs)
        for response, chunk in chat.stream():
            delta = getattr(chunk, "content", "") or ""
            if isinstance(delta, (list, tuple)):
                delta = "".join(str(part) for part in delta)
            reasoning_delta = getattr(chunk, "reasoning_content", None) or ""
            if isinstance(reasoning_delta, (list, tuple)):
                reasoning_delta = "".join(str(part) for part in reasoning_delta)
            accumulated = getattr(response, "content", "") or ""
            if isinstance(accumulated, (list, tuple)):
                accumulated = "".join(str(part) for part in accumulated)
            finish = getattr(response, "finish_reason", None)
            yield ProviderStreamChunk(
                delta=str(delta),
                accumulated=str(accumulated),
                usage=_usage_from_sdk(response) or _usage_from_sdk(chunk),
                finish_reason=str(finish) if finish is not None else None,
                reasoning_delta=str(reasoning_delta) if reasoning_delta else None,
                raw=(response, chunk),
            )


ScriptedReply = str | dict[str, Any] | list[Any] | Callable[..., str | dict[str, Any]]


def _chunk_text(text: str, *, size: int = 6) -> list[str]:
    """Split text into small deltas so mock stream is incremental (not buffer-then-return)."""
    if text == "":
        return [""]
    return [text[i : i + size] for i in range(0, len(text), size)]


class MockChatProvider:
    """Deterministic offline provider for unit tests and CI (no network)."""

    def __init__(
        self,
        replies: ScriptedReply = "ok",
        *,
        default_usage: dict[str, Any] | None = None,
        fail_times: int = 0,
        fail_exc: BaseException | Callable[[], BaseException] | None = None,
        stream_chunk_size: int = 6,
    ) -> None:
        self.replies = replies
        self.default_usage = default_usage or {
            "prompt_tokens": 10,
            "completion_tokens": 5,
        }
        self._fail_remaining = max(0, int(fail_times))
        self._fail_exc = fail_exc
        self._queue_index = 0
        self.stream_chunk_size = max(1, int(stream_chunk_size))
        self.calls: list[dict[str, Any]] = []

    def _next_failure(self) -> BaseException:
        if self._fail_exc is None:
            return RuntimeError("mock provider transient failure")
        if callable(self._fail_exc) and not isinstance(self._fail_exc, BaseException):
            return self._fail_exc()  # type: ignore[misc]
        return self._fail_exc  # type: ignore[return-value]

    def _resolve_reply(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> str:
        r = self.replies
        if callable(r) and not isinstance(r, type):
            out = r(messages, **kwargs)
        elif isinstance(r, list):
            if self._queue_index >= len(r):
                item = r[-1] if r else "ok"
            else:
                item = r[self._queue_index]
                self._queue_index += 1
            out = item
        else:
            out = r

        if isinstance(out, dict):
            return json.dumps(out)
        return str(out)

    def _note_call(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        temperature: float,
        max_tokens: int | None,
        thought_level: str | None,
        system_prompt: str | None,
        kind: str,
    ) -> None:
        self.calls.append(
            {
                "kind": kind,
                "messages": list(messages),
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "thought_level": thought_level,
                "system_prompt": system_prompt,
            }
        )

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        thought_level: str | None = None,
        system_prompt: str | None = None,
    ) -> ProviderResponse:
        self._note_call(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            thought_level=thought_level,
            system_prompt=system_prompt,
            kind="complete",
        )

        if self._fail_remaining > 0:
            self._fail_remaining -= 1
            raise self._next_failure()

        content = self._resolve_reply(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            thought_level=thought_level,
            system_prompt=system_prompt,
        )
        return ProviderResponse(
            content=content,
            usage=dict(self.default_usage),
            model=model,
            finish_reason="stop",
        )

    def stream(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        thought_level: str | None = None,
        system_prompt: str | None = None,
    ) -> Iterator[ProviderStreamChunk]:
        self._note_call(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            thought_level=thought_level,
            system_prompt=system_prompt,
            kind="stream",
        )

        if self._fail_remaining > 0:
            self._fail_remaining -= 1
            raise self._next_failure()

        content = self._resolve_reply(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            thought_level=thought_level,
            system_prompt=system_prompt,
        )
        parts = _chunk_text(content, size=self.stream_chunk_size)
        accumulated = ""
        for i, part in enumerate(parts):
            accumulated += part
            is_last = i == len(parts) - 1
            yield ProviderStreamChunk(
                delta=part,
                accumulated=accumulated,
                usage=dict(self.default_usage) if is_last else None,
                finish_reason="stop" if is_last else None,
            )
