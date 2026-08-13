"""Chat provider abstraction for XaiKit.

Live path uses the xAI SDK. Offline tests inject :class:`MockChatProvider`.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel


@dataclass
class ProviderResponse:
    """Normalized completion from any provider implementation."""

    content: str
    usage: dict[str, Any] | None = None
    model: str | None = None
    raw: Any = None
    reasoning_content: str | None = None
    finish_reason: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


@dataclass
class ProviderStreamChunk:
    """One incremental stream piece from :meth:`ChatProvider.stream`."""

    delta: str
    accumulated: str
    usage: dict[str, Any] | None = None
    finish_reason: str | None = None
    reasoning_delta: str | None = None
    raw: Any = None
    tool_call_delta: list[dict[str, Any]] | None = None
    tool_calls: list[dict[str, Any]] | None = None


@runtime_checkable
class ChatProvider(Protocol):
    """Minimal surface XaiClient needs for chat / JSON / stream completion."""

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        thought_level: str | None = None,
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        parallel_tool_calls: bool | None = None,
        response_format: Any = None,
    ) -> ProviderResponse: ...

    def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        thought_level: str | None = None,
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        parallel_tool_calls: bool | None = None,
        response_format: Any = None,
    ) -> Iterator[ProviderStreamChunk]: ...


def _parse_tool_arguments(raw: Any) -> Any:
    """Parse tool-call arguments: JSON object/array when possible, else the raw string.

    Missing or blank payloads stay ``""`` (not ``{}``) so incomplete stream
    deltas are not mistaken for a finished empty-object call.
    """
    if raw is None:
        return ""
    if isinstance(raw, (dict, list)):
        return raw
    text = str(raw)
    if not text.strip():
        return ""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _normalize_tool_calls(raw: Any) -> list[dict[str, Any]] | None:
    """Normalize SDK protos or JSON dicts to ``{id, name, arguments}``."""
    if not raw:
        return None
    out: list[dict[str, Any]] = []
    for tc in raw:
        if isinstance(tc, dict):
            fn = tc.get("function") if isinstance(tc.get("function"), dict) else None
            name = tc.get("name")
            arguments = tc.get("arguments")
            if fn is not None:
                name = name or fn.get("name")
                if arguments is None:
                    arguments = fn.get("arguments")
            out.append(
                {
                    "id": str(tc.get("id") or ""),
                    "name": str(name or ""),
                    "arguments": _parse_tool_arguments(arguments),
                }
            )
            continue
        fn = getattr(tc, "function", None)
        name = getattr(fn, "name", None) if fn is not None else getattr(tc, "name", None)
        arguments = (
            getattr(fn, "arguments", None) if fn is not None else getattr(tc, "arguments", None)
        )
        out.append(
            {
                "id": str(getattr(tc, "id", "") or ""),
                "name": str(name or ""),
                "arguments": _parse_tool_arguments(arguments),
            }
        )
    return out or None


def _dump_tool_arguments(arguments: Any) -> str:
    if isinstance(arguments, str):
        return arguments
    return json.dumps(arguments if arguments is not None else {})


def _sdk_tool_call_proto(tc: dict[str, Any]) -> Any:
    from xai_sdk.proto import chat_pb2

    fn = tc.get("function") if isinstance(tc.get("function"), dict) else None
    name = tc.get("name") or (fn.get("name") if fn else "")
    arguments = tc.get("arguments")
    if arguments is None and fn is not None:
        arguments = fn.get("arguments")
    return chat_pb2.ToolCall(
        id=str(tc.get("id") or ""),
        function=chat_pb2.FunctionCall(
            name=str(name or ""),
            arguments=_dump_tool_arguments(arguments),
        ),
    )


def _image_url_and_detail(part: dict[str, Any]) -> tuple[str, str]:
    detail = part.get("detail")
    url = part.get("url") or part.get("image_url")
    if isinstance(url, dict):
        detail = detail or url.get("detail")
        url = url.get("url") or url.get("image_url")
    url_s = str(url).strip() if url else ""
    detail_s = str(detail).strip() if detail else "auto"
    if detail_s not in {"auto", "low", "high"}:
        detail_s = "auto"
    return url_s, detail_s


def _sdk_file_part(part: dict[str, Any]) -> Any:
    from xai_sdk.chat import file

    file_id = part.get("file_id") or part.get("id")
    data = part.get("data")
    url = part.get("url") or part.get("file_url")
    filename = part.get("filename")
    mime_type = part.get("mime_type")
    nested = part.get("file")
    if isinstance(nested, dict):
        file_id = file_id or nested.get("file_id") or nested.get("id")
        data = data if data is not None else nested.get("data")
        url = url or nested.get("url")
        filename = filename or nested.get("filename")
        mime_type = mime_type or nested.get("mime_type")
    if file_id:
        return file(str(file_id).strip())
    if data is not None:
        raw = data if isinstance(data, (bytes, bytearray)) else str(data).encode("utf-8")
        return file(data=bytes(raw), filename=filename, mime_type=mime_type)
    if url:
        return file(url=str(url).strip(), filename=filename, mime_type=mime_type)
    raise ValueError("file part needs file_id, data, or url")


def _sdk_content_part(part: Any) -> Any:
    from xai_sdk.chat import file, image, text

    if isinstance(part, str):
        return part
    if not isinstance(part, dict):
        return str(part)
    ptype = str(part.get("type") or "").strip().lower()
    if ptype in {"text", ""} and "text" in part:
        return part.get("text") or ""
    if ptype in {"image_url", "image"}:
        url, detail = _image_url_and_detail(part)
        if not url:
            raise ValueError("image part missing url")
        return image(url, detail=detail)  # type: ignore[arg-type]
    if ptype in {"file", "file_id"}:
        return _sdk_file_part(part)
    if ptype in {"video_url", "video"}:
        file_id = part.get("file_id")
        url = part.get("url") or part.get("video_url")
        if isinstance(url, dict):
            url = url.get("url")
        if file_id:
            return file(str(file_id).strip())
        if url:
            return file(
                url=str(url).strip(),
                mime_type=part.get("mime_type") or "video/mp4",
            )
        raise ValueError("video part missing url or file_id")
    if "text" in part:
        return part.get("text") or ""
    if part.get("url") or part.get("image_url"):
        url, detail = _image_url_and_detail(part)
        if url:
            return image(url, detail=detail)  # type: ignore[arg-type]
    return text(json.dumps(part))


def _sdk_content_args(content: Any) -> list[Any]:
    if content is None:
        return []
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        return [_sdk_content_part(p) for p in content]
    if isinstance(content, dict):
        return [_sdk_content_part(content)]
    return [str(content)]


def _tool_result_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return json.dumps(content)


def _build_sdk_messages(
    messages: list[dict[str, Any]],
    *,
    system_prompt: str | None,
) -> list[Any]:
    from xai_sdk.chat import assistant, system, tool_result, user

    chat_messages: list[Any] = []
    if system_prompt:
        chat_messages.append(system(system_prompt))
    for m in messages:
        role = str(m.get("role") or "user").strip().lower()
        content = m.get("content", "")
        if role == "tool":
            chat_messages.append(
                tool_result(
                    _tool_result_text(content),
                    tool_call_id=m.get("tool_call_id") or None,
                )
            )
            continue
        parts = _sdk_content_args(content)
        if role == "system":
            chat_messages.append(system(*(parts or [""])))
            continue
        if role == "user":
            chat_messages.append(user(*(parts or [""])))
            continue
        msg = assistant(*(parts or ([] if m.get("tool_calls") else [""])))
        for tc in m.get("tool_calls") or []:
            if isinstance(tc, dict):
                msg.tool_calls.append(_sdk_tool_call_proto(tc))
        chat_messages.append(msg)
    return chat_messages


def _sdk_tool(defn: Any) -> Any:
    from xai_sdk.chat import tool

    if not isinstance(defn, dict):
        return defn
    fn = defn.get("function") if isinstance(defn.get("function"), dict) else defn
    name = fn.get("name") or defn.get("name")
    description = fn.get("description") if "description" in fn else defn.get("description")
    parameters = fn.get("parameters") if "parameters" in fn else defn.get("parameters")
    if not isinstance(parameters, dict):
        parameters = {"type": "object", "properties": {}}
    return tool(str(name or ""), str(description or ""), parameters)


def _sdk_tool_choice(choice: Any) -> Any:
    from xai_sdk.chat import required_tool

    if isinstance(choice, str):
        return choice
    if isinstance(choice, dict):
        name = choice.get("name")
        fn = choice.get("function")
        if not name and isinstance(fn, dict):
            name = fn.get("name")
        if name:
            return required_tool(str(name))
    return choice


def _json_schema_response_format(schema: dict[str, Any]) -> Any:
    from xai_sdk.proto import chat_pb2

    return chat_pb2.ResponseFormat(
        format_type=chat_pb2.FORMAT_TYPE_JSON_SCHEMA,
        schema=json.dumps(schema),
    )


def _sdk_response_format(value: Any) -> Any:
    """Map kit JSON-dict / pydantic / string knobs onto SDK ``response_format``."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, type) and issubclass(value, BaseModel):
        return value
    if isinstance(value, dict):
        kind = str(value.get("type") or "").strip().lower()
        if kind == "json_object":
            return "json_object"
        if kind == "text":
            return "text"
        if kind == "json_schema":
            nested = value.get("json_schema") or value.get("schema") or value
            if isinstance(nested, dict) and isinstance(nested.get("schema"), dict):
                nested = nested["schema"]
            if isinstance(nested, dict):
                return _json_schema_response_format(nested)
            return value
        return _json_schema_response_format(value)
    return value


def _sdk_chat_kwargs(
    *,
    model: str,
    temperature: float,
    max_tokens: int | None,
    thought_level: str | None,
    tools: list[Any] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
    parallel_tool_calls: bool | None = None,
    response_format: Any = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if thought_level:
        kwargs["reasoning_effort"] = thought_level
    if tools is not None:
        kwargs["tools"] = [_sdk_tool(t) for t in tools]
    if tool_choice is not None:
        kwargs["tool_choice"] = _sdk_tool_choice(tool_choice)
    if parallel_tool_calls is not None:
        kwargs["parallel_tool_calls"] = parallel_tool_calls
    if response_format is not None:
        kwargs["response_format"] = _sdk_response_format(response_format)
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


def _text_from_sdk(value: Any) -> str:
    text = value or ""
    if isinstance(text, (list, tuple)):
        return "".join(str(part) for part in text)
    return str(text) if text else ""


class SdkChatProvider:
    """Thin adapter over ``xai_sdk.Client`` (production path)."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        thought_level: str | None = None,
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        parallel_tool_calls: bool | None = None,
        response_format: Any = None,
    ) -> ProviderResponse:
        chat_messages = _build_sdk_messages(messages, system_prompt=system_prompt)
        kwargs = _sdk_chat_kwargs(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            thought_level=thought_level,
            tools=tools,
            tool_choice=tool_choice,
            parallel_tool_calls=parallel_tool_calls,
            response_format=response_format,
        )
        chat = self._client.chat.create(messages=chat_messages, **kwargs)
        response = chat.sample()
        text = _text_from_sdk(getattr(response, "content", ""))
        reasoning = _text_from_sdk(getattr(response, "reasoning_content", None))
        finish = getattr(response, "finish_reason", None)
        return ProviderResponse(
            content=str(text),
            usage=_usage_from_sdk(response),
            model=model,
            raw=response,
            reasoning_content=str(reasoning) if reasoning else None,
            finish_reason=str(finish) if finish is not None else None,
            tool_calls=_normalize_tool_calls(getattr(response, "tool_calls", None)),
        )

    def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        thought_level: str | None = None,
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        parallel_tool_calls: bool | None = None,
        response_format: Any = None,
    ) -> Iterator[ProviderStreamChunk]:
        chat_messages = _build_sdk_messages(messages, system_prompt=system_prompt)
        kwargs = _sdk_chat_kwargs(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            thought_level=thought_level,
            tools=tools,
            tool_choice=tool_choice,
            parallel_tool_calls=parallel_tool_calls,
            response_format=response_format,
        )
        chat = self._client.chat.create(messages=chat_messages, **kwargs)
        for response, chunk in chat.stream():
            delta = _text_from_sdk(getattr(chunk, "content", ""))
            reasoning_delta = _text_from_sdk(getattr(chunk, "reasoning_content", None))
            accumulated = _text_from_sdk(getattr(response, "content", ""))
            finish = getattr(response, "finish_reason", None)
            yield ProviderStreamChunk(
                delta=str(delta),
                accumulated=str(accumulated),
                usage=_usage_from_sdk(response) or _usage_from_sdk(chunk),
                finish_reason=str(finish) if finish is not None else None,
                reasoning_delta=str(reasoning_delta) if reasoning_delta else None,
                raw=(response, chunk),
                tool_call_delta=_normalize_tool_calls(getattr(chunk, "tool_calls", None)),
                tool_calls=_normalize_tool_calls(getattr(response, "tool_calls", None)),
            )


ScriptedReply = str | dict[str, Any] | list[Any] | Callable[..., str | dict[str, Any]]


def _chunk_text(text: str, *, size: int = 6) -> list[str]:
    """Split text into small deltas so mock stream is incremental (not buffer-then-return)."""
    if text == "":
        return [""]
    return [text[i : i + size] for i in range(0, len(text), size)]


def _split_scripted_reply(out: Any) -> tuple[str, list[dict[str, Any]] | None]:
    """Turn a scripted reply into content + optional tool_calls.

    A dict with a ``tool_calls`` key is a structured mock response (not JSON content).
    Any other dict is JSON-encoded as content (existing ``chat_json`` contract).
    """
    if isinstance(out, dict) and "tool_calls" in out:
        content = out.get("content", "")
        if content is None:
            content = ""
        elif not isinstance(content, str):
            content = json.dumps(content)
        return str(content), _normalize_tool_calls(out.get("tool_calls"))
    if isinstance(out, dict):
        return json.dumps(out), None
    return str(out), None


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
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> tuple[str, list[dict[str, Any]] | None]:
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
        return _split_scripted_reply(out)

    def _note_call(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        temperature: float,
        max_tokens: int | None,
        thought_level: str | None,
        system_prompt: str | None,
        kind: str,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        parallel_tool_calls: bool | None = None,
        response_format: Any = None,
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
                "tools": tools,
                "tool_choice": tool_choice,
                "parallel_tool_calls": parallel_tool_calls,
                "response_format": response_format,
            }
        )

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        thought_level: str | None = None,
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        parallel_tool_calls: bool | None = None,
        response_format: Any = None,
    ) -> ProviderResponse:
        self._note_call(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            thought_level=thought_level,
            system_prompt=system_prompt,
            kind="complete",
            tools=tools,
            tool_choice=tool_choice,
            parallel_tool_calls=parallel_tool_calls,
            response_format=response_format,
        )

        if self._fail_remaining > 0:
            self._fail_remaining -= 1
            raise self._next_failure()

        content, tool_calls = self._resolve_reply(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            thought_level=thought_level,
            system_prompt=system_prompt,
            tools=tools,
            tool_choice=tool_choice,
            parallel_tool_calls=parallel_tool_calls,
            response_format=response_format,
        )
        return ProviderResponse(
            content=content,
            usage=dict(self.default_usage),
            model=model,
            finish_reason="tool_calls" if tool_calls else "stop",
            tool_calls=tool_calls,
        )

    def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        thought_level: str | None = None,
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        parallel_tool_calls: bool | None = None,
        response_format: Any = None,
    ) -> Iterator[ProviderStreamChunk]:
        self._note_call(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            thought_level=thought_level,
            system_prompt=system_prompt,
            kind="stream",
            tools=tools,
            tool_choice=tool_choice,
            parallel_tool_calls=parallel_tool_calls,
            response_format=response_format,
        )

        if self._fail_remaining > 0:
            self._fail_remaining -= 1
            raise self._next_failure()

        content, tool_calls = self._resolve_reply(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            thought_level=thought_level,
            system_prompt=system_prompt,
            tools=tools,
            tool_choice=tool_choice,
            parallel_tool_calls=parallel_tool_calls,
            response_format=response_format,
        )
        finish = "tool_calls" if tool_calls else "stop"
        if not content and tool_calls:
            yield ProviderStreamChunk(
                delta="",
                accumulated="",
                usage=dict(self.default_usage),
                finish_reason=finish,
                tool_call_delta=tool_calls,
                tool_calls=tool_calls,
            )
            return
        parts = _chunk_text(content, size=self.stream_chunk_size)
        accumulated = ""
        for i, part in enumerate(parts):
            accumulated += part
            is_last = i == len(parts) - 1
            yield ProviderStreamChunk(
                delta=part,
                accumulated=accumulated,
                usage=dict(self.default_usage) if is_last else None,
                finish_reason=finish if is_last else None,
                tool_call_delta=tool_calls if is_last else None,
                tool_calls=tool_calls if is_last else None,
            )
