"""xAI (Grok) client — typed transport for XaiKit.

Domain schemas stay in consuming apps; this module is transport only.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections.abc import Iterator, Sequence
from typing import Any

import httpx
from xai_sdk import Client

from xaikit.batch import (
    batch_to_dict,
    call_batch_rpc,
    list_batches_to_dict,
    list_results_to_dict,
    normalize_batch_requests,
)
from xaikit.catalog import (
    BOOTSTRAP_MODEL,
    DEFAULT_IMAGE_MODEL,
    DEFAULT_VIDEO_MODEL,
    normalize_thought_level,
    resolve_model_selection,
)
from xaikit.collections import (
    call_collections_rpc,
    collection_to_dict,
    document_to_dict,
    list_collections_to_dict,
    normalize_collection_ids,
    search_to_dict,
)
from xaikit.credentials import CredentialStore
from xaikit.provider import ChatProvider, SdkChatProvider
from xaikit.realtime import (
    DEFAULT_REALTIME_VOICE,
    DEFAULT_VOICE_MODEL,
    XAI_REALTIME_URL,
    RealtimeSession,
    connect_realtime_websocket,
    realtime_session_url,
)
from xaikit.stt_stream import (
    DEFAULT_STT_ENCODING,
    DEFAULT_STT_SAMPLE_RATE,
    XAI_STT_WS_URL,
    SttSession,
    connect_stt_websocket,
    stt_session_url,
)
from xaikit.retry import RetryPolicy, call_with_retry, default_retry_policy
from xaikit.traces import CompletionTracer
from xaikit.types import CompletionResponse, StreamChunk
from xaikit.usage import UsageMeter

logger = logging.getLogger(__name__)

_JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

XAI_STT_URL = "https://api.x.ai/v1/stt"
XAI_TTS_URL = "https://api.x.ai/v1/tts"
XAI_IMAGES_URL = "https://api.x.ai/v1/images/generations"
XAI_IMAGE_EDITS_URL = "https://api.x.ai/v1/images/edits"
XAI_FILES_URL = "https://api.x.ai/v1/files"
XAI_EMBEDDINGS_URL = "https://api.x.ai/v1/embeddings"
XAI_TOKENIZE_URL = "https://api.x.ai/v1/tokenize-text"
XAI_RESPONSES_URL = "https://api.x.ai/v1/responses"
XAI_VIDEOS_URL = "https://api.x.ai/v1/videos/generations"
XAI_VIDEO_EXTENSIONS_URL = "https://api.x.ai/v1/videos/extensions"
XAI_VIDEO_STATUS_URL = "https://api.x.ai/v1/videos/{request_id}"
DEFAULT_TTS_VOICE_ID = "eve"
XAI_FILE_MAX_BYTES = 50 * 1024 * 1024
XAI_EMBED_MAX_INPUTS = 128
_FILES_TIMEOUT = 120.0
_EMBED_TIMEOUT = 120.0
_TOKENIZE_TIMEOUT = 60.0
_RESPONSES_TIMEOUT = 120.0
XAI_RESPONSES_MAX_TOOLS = 128
_FILES_EXPIRES_AFTER_MIN = 3600
_FILES_EXPIRES_AFTER_MAX = 2_592_000
DEFAULT_FILE_PURPOSE = "assistants"
_REALTIME_OPEN_TIMEOUT = 30.0
_REALTIME_CLOSE_TIMEOUT = 10.0

_VIDEO_ASPECT_RATIOS = frozenset({"1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"})
_VIDEO_RESOLUTIONS = frozenset({"480p", "720p", "1080p"})
_VIDEO_START_TIMEOUT = 60.0
_VIDEO_POLL_TIMEOUT = 60.0
_VIDEO_DOWNLOAD_TIMEOUT = 120.0
_VIDEO_WAIT_TIMEOUT = 600.0
_VIDEO_WAIT_INTERVAL = 5.0
_VIDEO_MAX_REFERENCE_AUDIOS = 3


def _error_class(exc: BaseException) -> str:
    name = type(exc).__name__
    msg = str(exc)
    if len(msg) > 120:
        msg = msg[:117] + "..."
    return f"{name}: {msg}" if msg else name


class XaiClient:
    """High-level xAI client: chat, modalities, optional metering + mock provider."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        *,
        thought_level: str | None = None,
        effort: str | None = None,
        intent: str | None = None,
        task: str | None = None,
        usage_meter: UsageMeter | None = None,
        provider: ChatProvider | None = None,
        retry_policy: RetryPolicy | None = None,
        credential_store: CredentialStore | None = None,
        subject: str | None = None,
        image_model: str | None = None,
        video_model: str | None = None,
        voice_model: str | None = None,
        bootstrap_model: str = BOOTSTRAP_MODEL,
        completion_tracer: CompletionTracer | None = None,
    ) -> None:
        # effort is an alias for thought_level → reasoning_effort on the wire
        level_in = thought_level if thought_level is not None else effort

        if model is not None and str(model).strip():
            self.model = str(model).strip()
            self._resolve_source = "override"
            self.thought_level = normalize_thought_level(level_in)
        else:
            selection = resolve_model_selection(
                pin=None,
                intent=intent,
                task=task,
                thought_level=level_in,
                bootstrap=bootstrap_model,
            )
            self.model = selection.model_id
            self._resolve_source = selection.source
            self.thought_level = (
                normalize_thought_level(level_in)
                if level_in is not None
                else selection.thought_level
            )

        if provider is not None:
            self._provider: ChatProvider = provider
            self.api_key = (api_key or "").strip() or "mock"
            self._client = None
        else:
            key = (api_key or "").strip()
            if not key and credential_store is not None:
                key = (credential_store.get_api_key(subject) or "").strip()
            if not key:
                raise RuntimeError(
                    "xAI credentials not configured. Pass api_key=, inject a "
                    "CredentialStore, or use provider=MockChatProvider for offline."
                )
            self.api_key = key
            # SDK collections create/upload use the management channel. Pass
            # XAI_MANAGEMENT_KEY through if present — do not store a second key
            # on this client. Search uses the regular API channel.
            management_api_key = (os.environ.get("XAI_MANAGEMENT_KEY") or "").strip() or None
            self._client = Client(
                api_key=key,
                management_api_key=management_api_key,
            )
            self._provider = SdkChatProvider(self._client)

        self._usage_meter = usage_meter
        self._completion_tracer = completion_tracer
        self._retry_policy = (
            retry_policy if retry_policy is not None else default_retry_policy()
        )
        self.image_model = (image_model or DEFAULT_IMAGE_MODEL).strip()
        self.video_model = (video_model or DEFAULT_VIDEO_MODEL).strip()
        self.voice_model = (voice_model or DEFAULT_VOICE_MODEL).strip()

    def _require_purpose_if_metered(self, purpose: str | None) -> str | None:
        if self._usage_meter is None:
            return (purpose or "").strip() or None
        tag = (purpose or "").strip()
        if not tag:
            raise ValueError(
                "purpose tag is required when a UsageMeter is attached "
                "(e.g. purpose='demo.chat')"
            )
        return tag

    def _effective_thought_level(
        self,
        thought_level: str | None = None,
        *,
        effort: str | None = None,
    ) -> str | None:
        level_in = thought_level if thought_level is not None else effort
        if level_in is not None:
            return normalize_thought_level(level_in)
        return self.thought_level

    def _complete(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int | None = None,
        thought_level: str | None,
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        parallel_tool_calls: bool | None = None,
        response_format: Any = None,
    ):
        def _call():
            return self._provider.complete(
                messages,
                model=self.model,
                temperature=temperature,
                max_tokens=max_tokens,
                thought_level=thought_level,
                system_prompt=system_prompt,
                tools=tools,
                tool_choice=tool_choice,
                parallel_tool_calls=parallel_tool_calls,
                response_format=response_format,
            )

        return call_with_retry(
            _call,
            policy=self._retry_policy,
            label="xai.complete",
        )

    def _open_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int | None = None,
        thought_level: str | None,
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        parallel_tool_calls: bool | None = None,
        response_format: Any = None,
    ):
        def _call():
            return self._provider.stream(
                messages,
                model=self.model,
                temperature=temperature,
                max_tokens=max_tokens,
                thought_level=thought_level,
                system_prompt=system_prompt,
                tools=tools,
                tool_choice=tool_choice,
                parallel_tool_calls=parallel_tool_calls,
                response_format=response_format,
            )

        # Retry only opening the iterator — mid-stream failures are not retried.
        return call_with_retry(
            _call,
            policy=self._retry_policy,
            label="xai.stream",
        )

    def _trace(
        self,
        *,
        messages: list[dict[str, Any]],
        response: str | None,
        system_prompt: str | None,
        purpose: str | None,
        thought_level: str | None,
        success: bool,
        error: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
        modality: str = "chat",
    ) -> None:
        if self._completion_tracer is None:
            return
        try:
            self._completion_tracer.record(
                messages=messages,
                response=response,
                system_prompt=system_prompt,
                purpose=purpose,
                model=self.model,
                thought_level=thought_level,
                success=success,
                error=error,
                modality=modality,
                parent_id=parent_id,
                labels=labels,
            )
        except Exception:
            logger.exception("Failed to record completion trace (purpose=%s)", purpose)

    def _record(
        self,
        *,
        purpose: str | None,
        usage: dict[str, Any] | None,
        parent_id: str | None,
        labels: dict[str, str] | None,
        success: bool,
        thought_level: str | None,
        error: str | None = None,
        modality: str | None = None,
        model: str | None = None,
        apply_price_table: bool = True,
    ) -> None:
        if self._usage_meter is None:
            return
        if not purpose:
            return
        try:
            self._usage_meter.record(
                purpose=purpose,
                model=model or self.model,
                usage=usage,
                parent_id=parent_id,
                labels=labels,
                success=success,
                thought_level=thought_level,
                error=error,
                modality=modality,
                apply_price_table=apply_price_table,
            )
        except Exception:
            logger.exception("Failed to record usage event (purpose=%s)", purpose)

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        system_prompt: str | None = None,
        thought_level: str | None = None,
        effort: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        parallel_tool_calls: bool | None = None,
    ) -> CompletionResponse:
        """Non-streaming chat completion.

        ``tools`` are JSON-dict function defs (``name``, ``description``, ``parameters``).
        The kit returns ``tool_calls`` on the response; the app runs tools and sends
        ``role="tool"`` follow-up messages. The kit does not execute tools.
        Message ``content`` may be a string or a list of parts (text / image_url / file).
        """
        tag = self._require_purpose_if_metered(purpose)
        level = self._effective_thought_level(thought_level, effort=effort)
        usage: dict[str, Any] | None = None
        try:
            resp = self._complete(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                thought_level=level,
                system_prompt=system_prompt,
                tools=tools,
                tool_choice=tool_choice,
                parallel_tool_calls=parallel_tool_calls,
            )
            text = resp.content or ""
            usage = resp.usage
            self._record(
                purpose=tag,
                usage=usage,
                parent_id=parent_id,
                labels=labels,
                success=True,
                thought_level=level,
                modality="chat",
            )
            self._trace(
                messages=messages,
                response=str(text),
                system_prompt=system_prompt,
                purpose=tag,
                thought_level=level,
                success=True,
                parent_id=parent_id,
                labels=labels,
            )
            return CompletionResponse(
                content=str(text),
                model=self.model,
                usage=usage,
                reasoning_content=getattr(resp, "reasoning_content", None),
                finish_reason=getattr(resp, "finish_reason", None),
                tool_calls=getattr(resp, "tool_calls", None),
            )
        except Exception as exc:
            err = _error_class(exc)
            self._record(
                purpose=tag,
                usage=usage,
                parent_id=parent_id,
                labels=labels,
                success=False,
                thought_level=level,
                error=err,
                modality="chat",
            )
            self._trace(
                messages=messages,
                response=None,
                system_prompt=system_prompt,
                purpose=tag,
                thought_level=level,
                success=False,
                error=err,
                parent_id=parent_id,
                labels=labels,
            )
            logger.exception("xAI chat call failed")
            raise RuntimeError(f"xAI request failed: {exc}") from exc

    def chat_json(
        self,
        user_prompt: str,
        *,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
        system_prompt: str | None = None,
        temperature: float = 0.3,
        thought_level: str | None = None,
        effort: str | None = None,
        schema: Any = None,
        response_format: Any = None,
    ) -> dict[str, Any]:
        """Return a parsed JSON object from a JSON-only model response.

        Pass ``schema=`` (JSON Schema dict or pydantic ``BaseModel`` subclass) or
        ``response_format=`` (``"json_object"`` / ``"text"`` / schema dict / model)
        to use xAI native structured outputs. Fence-stripping remains the fallback
        when the model still returns fenced JSON.
        """
        tag = self._require_purpose_if_metered(purpose)
        level = self._effective_thought_level(thought_level, effort=effort)
        messages = [{"role": "user", "content": user_prompt}]
        sys = system_prompt or (
            "You return ONLY valid JSON (no markdown fences) matching the requested shape."
        )
        fmt = schema if schema is not None else response_format
        usage: dict[str, Any] | None = None
        try:
            resp = self._complete(
                messages,
                temperature=temperature,
                thought_level=level,
                system_prompt=sys,
                response_format=fmt,
            )
            text = resp.content or ""
            usage = resp.usage
            raw = _JSON_FENCE.sub("", str(text).strip()).strip()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                err = _error_class(exc)
                self._record(
                    purpose=tag,
                    usage=usage,
                    parent_id=parent_id,
                    labels=labels,
                    success=False,
                    thought_level=level,
                    error=err,
                    modality="chat",
                )
                self._trace(
                    messages=messages,
                    response=str(text),
                    system_prompt=sys,
                    purpose=tag,
                    thought_level=level,
                    success=False,
                    error=err,
                    parent_id=parent_id,
                    labels=labels,
                )
                logger.exception("xAI JSON parse failed")
                raise RuntimeError(f"Model returned invalid JSON: {exc}") from exc
            if not isinstance(data, dict):
                err = "RuntimeError: JSON not an object"
                self._record(
                    purpose=tag,
                    usage=usage,
                    parent_id=parent_id,
                    labels=labels,
                    success=False,
                    thought_level=level,
                    error=err,
                    modality="chat",
                )
                self._trace(
                    messages=messages,
                    response=str(text),
                    system_prompt=sys,
                    purpose=tag,
                    thought_level=level,
                    success=False,
                    error=err,
                    parent_id=parent_id,
                    labels=labels,
                )
                raise RuntimeError("Model returned JSON that is not an object")
            self._record(
                purpose=tag,
                usage=usage,
                parent_id=parent_id,
                labels=labels,
                success=True,
                thought_level=level,
                modality="chat",
            )
            self._trace(
                messages=messages,
                response=str(text),
                system_prompt=sys,
                purpose=tag,
                thought_level=level,
                success=True,
                parent_id=parent_id,
                labels=labels,
            )
            return data
        except RuntimeError:
            raise
        except Exception as exc:
            err = _error_class(exc)
            self._record(
                purpose=tag,
                usage=usage,
                parent_id=parent_id,
                labels=labels,
                success=False,
                thought_level=level,
                error=err,
                modality="chat",
            )
            self._trace(
                messages=messages,
                response=None,
                system_prompt=sys,
                purpose=tag,
                thought_level=level,
                success=False,
                error=err,
                parent_id=parent_id,
                labels=labels,
            )
            logger.exception("xAI JSON call failed")
            raise RuntimeError(f"JSON xAI request failed: {exc}") from exc

    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        system_prompt: str | None = None,
        thought_level: str | None = None,
        effort: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        parallel_tool_calls: bool | None = None,
    ) -> Iterator[StreamChunk]:
        """Incremental chat completion — yields deltas as the provider streams them.

        Usage is recorded once when the stream completes successfully (or fails).
        Mid-stream provider failures are not retried; only opening the stream is.
        Tool-call deltas are surfaced on each chunk when the SDK yields them; the
        last chunk's ``tool_calls`` is the accumulated list. The app owns the loop.
        """
        tag = self._require_purpose_if_metered(purpose)
        level = self._effective_thought_level(thought_level, effort=effort)
        usage: dict[str, Any] | None = None
        accumulated = ""
        try:
            stream = self._open_stream(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                thought_level=level,
                system_prompt=system_prompt,
                tools=tools,
                tool_choice=tool_choice,
                parallel_tool_calls=parallel_tool_calls,
            )
            for piece in stream:
                accumulated = piece.accumulated
                if piece.usage:
                    usage = piece.usage
                yield StreamChunk(
                    delta=piece.delta or "",
                    accumulated=accumulated,
                    model=self.model,
                    usage=piece.usage,
                    finish_reason=piece.finish_reason,
                    reasoning_delta=piece.reasoning_delta,
                    tool_call_delta=getattr(piece, "tool_call_delta", None),
                    tool_calls=getattr(piece, "tool_calls", None),
                )
            self._record(
                purpose=tag,
                usage=usage,
                parent_id=parent_id,
                labels=labels,
                success=True,
                thought_level=level,
                modality="chat",
            )
            self._trace(
                messages=messages,
                response=accumulated,
                system_prompt=system_prompt,
                purpose=tag,
                thought_level=level,
                success=True,
                parent_id=parent_id,
                labels=labels,
            )
        except GeneratorExit:
            # Consumer abandoned the stream — do not meter/trace as a completed call.
            raise
        except Exception as exc:
            err = _error_class(exc)
            self._record(
                purpose=tag,
                usage=usage,
                parent_id=parent_id,
                labels=labels,
                success=False,
                thought_level=level,
                error=err,
                modality="chat",
            )
            self._trace(
                messages=messages,
                response=accumulated or None,
                system_prompt=system_prompt,
                purpose=tag,
                thought_level=level,
                success=False,
                error=err,
                parent_id=parent_id,
                labels=labels,
            )
            logger.exception("xAI chat stream failed")
            raise RuntimeError(f"xAI stream request failed: {exc}") from exc

    def transcribe(
        self,
        file_bytes: bytes,
        *,
        filename: str = "recording.webm",
        content_type: str = "audio/webm",
        language: str = "en",
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> str:
        """Transcribe audio via xAI Speech-to-Text (REST file upload)."""
        tag = self._require_purpose_if_metered(purpose)
        if not file_bytes:
            raise RuntimeError("Audio file is empty")

        data = {
            "format": "true",
            "language": language,
        }
        files = {
            "file": (filename, file_bytes, content_type or "application/octet-stream"),
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}

        try:
            response = httpx.post(
                XAI_STT_URL,
                headers=headers,
                data=data,
                files=files,
                timeout=120.0,
            )
        except httpx.HTTPError as exc:
            self._record(
                purpose=tag,
                usage=None,
                parent_id=parent_id,
                labels=labels,
                success=False,
                thought_level=None,
                error=_error_class(exc),
                modality="stt",
                model="stt",
            )
            logger.exception("xAI STT request failed")
            raise RuntimeError(f"STT request failed: {exc}") from exc

        if response.status_code == 401:
            raise RuntimeError("xAI STT unauthorized — check API key")
        if response.status_code == 413:
            raise RuntimeError("Audio file too large for STT")
        if response.status_code >= 400:
            detail = response.text[:500] if response.text else response.reason_phrase
            logger.error("xAI STT error %s: %s", response.status_code, detail)
            self._record(
                purpose=tag,
                usage=None,
                parent_id=parent_id,
                labels=labels,
                success=False,
                thought_level=None,
                error=f"HTTP{response.status_code}",
                modality="stt",
                model="stt",
            )
            raise RuntimeError(f"STT failed ({response.status_code}): {detail}")

        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError("STT returned non-JSON response") from exc

        text = payload.get("text") if isinstance(payload, dict) else None
        if text is None:
            raise RuntimeError("STT response missing text field")
        self._record(
            purpose=tag,
            usage=None,
            parent_id=parent_id,
            labels=labels,
            success=True,
            thought_level=None,
            modality="stt",
            model="stt",
        )
        return str(text)

    def synthesize_speech(
        self,
        text: str,
        *,
        voice_id: str = DEFAULT_TTS_VOICE_ID,
        language: str = "en",
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> tuple[bytes, str]:
        """Synthesize spoken audio via xAI Text-to-Speech (REST)."""
        tag = self._require_purpose_if_metered(purpose)
        cleaned = (text or "").strip()
        if not cleaned:
            raise RuntimeError("TTS text is empty")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "audio/mpeg, application/octet-stream, */*",
        }
        body = {
            "text": cleaned,
            "voice_id": voice_id or DEFAULT_TTS_VOICE_ID,
            "language": language or "en",
        }

        try:
            response = httpx.post(
                XAI_TTS_URL,
                headers=headers,
                json=body,
                timeout=120.0,
            )
        except httpx.HTTPError as exc:
            self._record(
                purpose=tag,
                usage=None,
                parent_id=parent_id,
                labels=labels,
                success=False,
                thought_level=None,
                error=_error_class(exc),
                modality="tts",
                model="tts",
            )
            logger.exception("xAI TTS request failed")
            raise RuntimeError(f"TTS request failed: {exc}") from exc

        if response.status_code == 401:
            raise RuntimeError("xAI TTS unauthorized — check API key")
        if response.status_code >= 400:
            detail = response.text[:500] if response.text else response.reason_phrase
            logger.error("xAI TTS error %s: %s", response.status_code, detail)
            self._record(
                purpose=tag,
                usage=None,
                parent_id=parent_id,
                labels=labels,
                success=False,
                thought_level=None,
                error=f"HTTP{response.status_code}",
                modality="tts",
                model="tts",
            )
            raise RuntimeError(f"TTS failed ({response.status_code}): {detail}")

        audio = response.content
        if not audio:
            raise RuntimeError("TTS returned empty audio")

        content_type = response.headers.get("content-type") or "audio/mpeg"
        content_type = content_type.split(";")[0].strip() or "audio/mpeg"
        self._record(
            purpose=tag,
            usage=None,
            parent_id=parent_id,
            labels=labels,
            success=True,
            thought_level=None,
            modality="tts",
            model="tts",
        )
        return audio, content_type

    def _record_files(
        self,
        *,
        tag: str | None,
        parent_id: str | None,
        labels: dict[str, str] | None,
        success: bool,
        error: str | None = None,
    ) -> None:
        self._record(
            purpose=tag,
            usage=None,
            parent_id=parent_id,
            labels=labels,
            success=success,
            thought_level=None,
            error=error,
            modality="files",
            model="files",
        )

    def _files_http(
        self,
        method: str,
        url: str,
        *,
        tag: str | None,
        parent_id: str | None,
        labels: dict[str, str] | None,
        **kwargs: Any,
    ) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        extra_headers = kwargs.pop("headers", None)
        if extra_headers:
            headers.update(extra_headers)
        http_fn = {"POST": httpx.post, "GET": httpx.get, "DELETE": httpx.delete}[method]
        try:
            response = http_fn(
                url,
                headers=headers,
                timeout=_FILES_TIMEOUT,
                **kwargs,
            )
        except httpx.HTTPError as exc:
            self._record_files(
                tag=tag,
                parent_id=parent_id,
                labels=labels,
                success=False,
                error=_error_class(exc),
            )
            logger.exception("xAI Files request failed")
            raise RuntimeError(f"Files request failed: {exc}") from exc

        if response.status_code == 401:
            raise RuntimeError("xAI Files unauthorized — check API key")
        if response.status_code == 413:
            self._record_files(
                tag=tag,
                parent_id=parent_id,
                labels=labels,
                success=False,
                error="HTTP413",
            )
            raise RuntimeError("File too large for Files API")
        if response.status_code >= 400:
            detail = response.text[:500] if response.text else response.reason_phrase
            logger.error("xAI Files error %s: %s", response.status_code, detail)
            self._record_files(
                tag=tag,
                parent_id=parent_id,
                labels=labels,
                success=False,
                error=f"HTTP{response.status_code}",
            )
            raise RuntimeError(f"Files failed ({response.status_code}): {detail}")
        return response

    def upload_file(
        self,
        data: bytes,
        filename: str,
        *,
        purpose: str | None = None,
        content_type: str | None = None,
        file_purpose: str = DEFAULT_FILE_PURPOSE,
        expires_after: int | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Upload bytes via xAI Files REST (multipart). Returns metadata including ``id``."""
        tag = self._require_purpose_if_metered(purpose)
        name = (filename or "").strip()
        if not name:
            raise RuntimeError("Filename is empty")
        if not data:
            raise RuntimeError("File data is empty")
        if len(data) > XAI_FILE_MAX_BYTES:
            raise RuntimeError(
                f"File exceeds {XAI_FILE_MAX_BYTES} byte Files API limit"
            )
        if expires_after is not None and not (
            _FILES_EXPIRES_AFTER_MIN <= expires_after <= _FILES_EXPIRES_AFTER_MAX
        ):
            raise RuntimeError(
                "expires_after must be between 3600 and 2592000 seconds"
            )

        # Dict (not a list of tuples): httpx multipart encoding calls `.items()`
        # on `data` when `files` is also set. Insertion order keeps expires_after
        # before purpose; httpx then appends the file part.
        form: dict[str, str] = {}
        if expires_after is not None:
            form["expires_after"] = str(expires_after)
        form["purpose"] = (file_purpose or "").strip() or DEFAULT_FILE_PURPOSE
        files = {
            "file": (
                name,
                data,
                content_type or "application/octet-stream",
            ),
        }
        response = self._files_http(
            "POST",
            XAI_FILES_URL,
            tag=tag,
            parent_id=parent_id,
            labels=labels,
            data=form,
            files=files,
        )
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError("Files upload returned non-JSON response") from exc
        out = _parse_file_metadata(payload)
        self._record_files(
            tag=tag,
            parent_id=parent_id,
            labels=labels,
            success=True,
        )
        return out

    def get_file(
        self,
        file_id: str,
        *,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Fetch Files metadata for an opaque ``file_id`` (GET /v1/files/{id})."""
        tag = self._require_purpose_if_metered(purpose)
        url = _file_resource_url(file_id)
        response = self._files_http(
            "GET",
            url,
            tag=tag,
            parent_id=parent_id,
            labels=labels,
        )
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError("Files get returned non-JSON response") from exc
        out = _parse_file_metadata(payload)
        self._record_files(
            tag=tag,
            parent_id=parent_id,
            labels=labels,
            success=True,
        )
        return out

    def delete_file(
        self,
        file_id: str,
        *,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Delete a stored file (DELETE /v1/files/{id})."""
        tag = self._require_purpose_if_metered(purpose)
        url = _file_resource_url(file_id)
        response = self._files_http(
            "DELETE",
            url,
            tag=tag,
            parent_id=parent_id,
            labels=labels,
        )
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError("Files delete returned non-JSON response") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Files delete returned unexpected payload")
        deleted = payload.get("deleted")
        raw_id = payload.get("id")
        out: dict[str, Any] = {
            "id": str(raw_id).strip() if raw_id is not None else (file_id or "").strip(),
            "deleted": bool(deleted) if deleted is not None else True,
        }
        if "object" in payload:
            out["object"] = payload.get("object")
        self._record_files(
            tag=tag,
            parent_id=parent_id,
            labels=labels,
            success=True,
        )
        return out

    def _record_embed(
        self,
        *,
        tag: str | None,
        model: str,
        parent_id: str | None,
        labels: dict[str, str] | None,
        success: bool,
        usage: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        self._record(
            purpose=tag,
            usage=usage,
            parent_id=parent_id,
            labels=labels,
            success=success,
            thought_level=None,
            error=error,
            modality="embed",
            model=model,
            apply_price_table=False,
        )

    def embed(
        self,
        texts: str | list[str],
        *,
        model: str,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Embed text via xAI REST ``POST /v1/embeddings``.

        *model* is required (OpenAPI examples use ``v1``; there is no
        documented grok-embedding default). Returns the REST envelope
        ``{object, model, data, usage}`` where ``data`` is
        ``[{index, embedding}, ...]``.
        """
        tag = self._require_purpose_if_metered(purpose)
        pin = (model or "").strip()
        if not pin:
            raise RuntimeError("model is required for embed")
        payload_input = _normalize_embed_texts(texts)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {"model": pin, "input": payload_input}
        try:
            response = httpx.post(
                XAI_EMBEDDINGS_URL,
                headers=headers,
                json=body,
                timeout=_EMBED_TIMEOUT,
            )
        except httpx.HTTPError as exc:
            self._record_embed(
                tag=tag,
                model=pin,
                parent_id=parent_id,
                labels=labels,
                success=False,
                error=_error_class(exc),
            )
            logger.exception("xAI embeddings request failed")
            raise RuntimeError(f"Embeddings request failed: {exc}") from exc

        if response.status_code == 401:
            raise RuntimeError("xAI embeddings unauthorized — check API key")
        if response.status_code >= 400:
            detail = response.text[:500] if response.text else response.reason_phrase
            logger.error("xAI embeddings error %s: %s", response.status_code, detail)
            self._record_embed(
                tag=tag,
                model=pin,
                parent_id=parent_id,
                labels=labels,
                success=False,
                error=f"HTTP{response.status_code}",
            )
            raise RuntimeError(f"Embeddings failed ({response.status_code}): {detail}")

        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError("Embeddings returned non-JSON response") from exc
        out = _parse_embed_response(payload, fallback_model=pin)
        self._record_embed(
            tag=tag,
            model=str(out.get("model") or pin),
            parent_id=parent_id,
            labels=labels,
            success=True,
            usage=out.get("usage") if isinstance(out.get("usage"), dict) else None,
        )
        return out

    def _record_tokenize(
        self,
        *,
        tag: str | None,
        model: str,
        parent_id: str | None,
        labels: dict[str, str] | None,
        success: bool,
        count: int | None = None,
        error: str | None = None,
    ) -> None:
        usage = None
        if count is not None:
            usage = {"prompt_tokens": count, "total_tokens": count}
        self._record(
            purpose=tag,
            usage=usage,
            parent_id=parent_id,
            labels=labels,
            success=success,
            thought_level=None,
            error=error,
            modality="tokenize",
            model=model,
            apply_price_table=False,
        )

    def tokenize(
        self,
        text: str,
        *,
        model: str | None = None,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Tokenize text via xAI REST ``POST /v1/tokenize-text``.

        Returns ``{tokens, count, model}`` where ``tokens`` is a list of
        JSON dicts ``{token_id, string, token_bytes}`` (no protobuf types).
        *model* defaults to this client's chat model. Empty text is rejected
        before HTTP. Works with ``provider=`` mocks (httpx is patched in
        tests); a live SDK client is not required.
        """
        tag = self._require_purpose_if_metered(purpose)
        pin = (model or "").strip() or (self.model or "").strip()
        if not pin:
            raise RuntimeError("model is required for tokenize")
        payload_text = _normalize_tokenize_text(text)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {"text": payload_text, "model": pin}
        try:
            response = httpx.post(
                XAI_TOKENIZE_URL,
                headers=headers,
                json=body,
                timeout=_TOKENIZE_TIMEOUT,
            )
        except httpx.HTTPError as exc:
            self._record_tokenize(
                tag=tag,
                model=pin,
                parent_id=parent_id,
                labels=labels,
                success=False,
                error=_error_class(exc),
            )
            logger.exception("xAI tokenize request failed")
            raise RuntimeError(f"Tokenize request failed: {exc}") from exc

        if response.status_code == 401:
            raise RuntimeError("xAI tokenize unauthorized — check API key")
        if response.status_code >= 400:
            detail = response.text[:500] if response.text else response.reason_phrase
            logger.error("xAI tokenize error %s: %s", response.status_code, detail)
            self._record_tokenize(
                tag=tag,
                model=pin,
                parent_id=parent_id,
                labels=labels,
                success=False,
                error=f"HTTP{response.status_code}",
            )
            raise RuntimeError(f"Tokenize failed ({response.status_code}): {detail}")

        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError("Tokenize returned non-JSON response") from exc
        out = _parse_tokenize_response(payload, fallback_model=pin)
        self._record_tokenize(
            tag=tag,
            model=str(out.get("model") or pin),
            parent_id=parent_id,
            labels=labels,
            success=True,
            count=int(out["count"]),
        )
        return out

    def _record_responses(
        self,
        *,
        tag: str | None,
        model: str,
        parent_id: str | None,
        labels: dict[str, str] | None,
        success: bool,
        usage: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        self._record(
            purpose=tag,
            usage=usage,
            parent_id=parent_id,
            labels=labels,
            success=success,
            thought_level=None,
            error=error,
            modality="responses",
            model=model,
            apply_price_table=False,
        )

    def _responses_http(
        self,
        method: str,
        url: str,
        *,
        tag: str | None,
        model: str,
        parent_id: str | None,
        labels: dict[str, str] | None,
        **kwargs: Any,
    ) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if "json" in kwargs:
            headers["Content-Type"] = "application/json"
        extra_headers = kwargs.pop("headers", None)
        if extra_headers:
            headers.update(extra_headers)
        http_fn = {"POST": httpx.post, "GET": httpx.get}[method]
        try:
            response = http_fn(
                url,
                headers=headers,
                timeout=_RESPONSES_TIMEOUT,
                **kwargs,
            )
        except httpx.HTTPError as exc:
            self._record_responses(
                tag=tag,
                model=model,
                parent_id=parent_id,
                labels=labels,
                success=False,
                error=_error_class(exc),
            )
            logger.exception("xAI responses request failed")
            raise RuntimeError(f"Responses request failed: {exc}") from exc

        if response.status_code == 401:
            raise RuntimeError("xAI responses unauthorized — check API key")
        if response.status_code >= 400:
            detail = response.text[:500] if response.text else response.reason_phrase
            logger.error("xAI responses error %s: %s", response.status_code, detail)
            self._record_responses(
                tag=tag,
                model=model,
                parent_id=parent_id,
                labels=labels,
                success=False,
                error=f"HTTP{response.status_code}",
            )
            raise RuntimeError(f"Responses failed ({response.status_code}): {detail}")
        return response

    def create_response(
        self,
        input: str | list[Any],
        *,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Create a response via xAI REST ``POST /v1/responses``.

        Additive to ``chat`` / ``chat_stream`` — those stay the paved text
        path. Built-in tools (web, X, code, collections, image) are opt-in:
        they are sent only when *tools* is passed. Returns the REST JSON
        object. *model* defaults to this client's chat model. Empty input is
        rejected before HTTP.
        """
        tag = self._require_purpose_if_metered(purpose)
        pin = (model or "").strip() or (self.model or "").strip()
        if not pin:
            raise RuntimeError("model is required for create_response")
        payload_input = _normalize_response_input(input)
        body: dict[str, Any] = {"model": pin, "input": payload_input}
        normalized_tools = _normalize_response_tools(tools)
        if normalized_tools is not None:
            body["tools"] = normalized_tools
        response = self._responses_http(
            "POST",
            XAI_RESPONSES_URL,
            tag=tag,
            model=pin,
            parent_id=parent_id,
            labels=labels,
            json=body,
        )
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError("Responses returned non-JSON response") from exc
        out = _parse_response_payload(payload)
        usage = out.get("usage") if isinstance(out.get("usage"), dict) else None
        self._record_responses(
            tag=tag,
            model=str(out.get("model") or pin),
            parent_id=parent_id,
            labels=labels,
            success=True,
            usage=usage,
        )
        return out

    def get_response(
        self,
        response_id: str,
        *,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Fetch a stored response via xAI REST ``GET /v1/responses/{id}``."""
        tag = self._require_purpose_if_metered(purpose)
        url = _response_resource_url(response_id)
        pin = (self.model or "").strip() or "responses"
        response = self._responses_http(
            "GET",
            url,
            tag=tag,
            model=pin,
            parent_id=parent_id,
            labels=labels,
        )
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError("Responses get returned non-JSON response") from exc
        out = _parse_response_payload(payload)
        # GET is a fetch, not a generation — do not re-count stored usage tokens.
        self._record_responses(
            tag=tag,
            model=str(out.get("model") or pin),
            parent_id=parent_id,
            labels=labels,
            success=True,
        )
        return out

    def _record_batch(
        self,
        *,
        tag: str | None,
        parent_id: str | None,
        labels: dict[str, str] | None,
        success: bool,
        error: str | None = None,
    ) -> None:
        self._record(
            purpose=tag,
            usage=None,
            parent_id=parent_id,
            labels=labels,
            success=success,
            thought_level=None,
            error=error,
            modality="batch",
            model="batch",
            apply_price_table=False,
        )

    def _batch_rpc(
        self,
        operation: str,
        *,
        tag: str | None,
        parent_id: str | None,
        labels: dict[str, str] | None,
        failed: str,
        **kwargs: Any,
    ) -> Any:
        try:
            return call_batch_rpc(
                operation,
                sdk_client=self._client,
                **kwargs,
            )
        except Exception as exc:
            self._record_batch(
                tag=tag,
                parent_id=parent_id,
                labels=labels,
                success=False,
                error=_error_class(exc),
            )
            logger.exception("xAI batch %s failed", operation)
            raise RuntimeError(f"{failed}: {exc}") from exc

    def create_batch(
        self,
        name: str,
        *,
        input_file_id: str | None = None,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Create a batch job (SDK ``client.batch.create``). Returns ``{id, name, …}``."""
        tag = self._require_purpose_if_metered(purpose)
        cleaned = (name or "").strip()
        if not cleaned:
            raise RuntimeError("Batch name is empty")
        file_id = (input_file_id or "").strip() or None
        raw = self._batch_rpc(
            "create",
            tag=tag,
            parent_id=parent_id,
            labels=labels,
            failed="Batch create failed",
            name=cleaned,
            input_file_id=file_id,
        )
        try:
            out = batch_to_dict(raw)
        except Exception as exc:
            self._record_batch(
                tag=tag,
                parent_id=parent_id,
                labels=labels,
                success=False,
                error=_error_class(exc),
            )
            raise RuntimeError(f"Batch create failed: {exc}") from exc
        self._record_batch(
            tag=tag,
            parent_id=parent_id,
            labels=labels,
            success=True,
        )
        return out

    def add_batch_requests(
        self,
        batch_id: str,
        requests: list[dict[str, Any]],
        *,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Add chat-shaped request dicts to a batch (SDK ``client.batch.add``)."""
        tag = self._require_purpose_if_metered(purpose)
        bid = (batch_id or "").strip()
        if not bid:
            raise RuntimeError("Batch id is empty")
        normalized = normalize_batch_requests(requests, default_model=self.model)
        raw = self._batch_rpc(
            "add",
            tag=tag,
            parent_id=parent_id,
            labels=labels,
            failed="Batch add failed",
            batch_id=bid,
            requests=normalized,
        )
        out: dict[str, Any]
        if raw is None:
            out = {"id": bid}
        elif isinstance(raw, dict):
            out = dict(raw)
            out.setdefault("id", bid)
        else:
            out = {"id": bid}
        self._record_batch(
            tag=tag,
            parent_id=parent_id,
            labels=labels,
            success=True,
        )
        return out

    def get_batch(
        self,
        batch_id: str,
        *,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Fetch batch status (SDK ``client.batch.get``). Poll ``state`` for progress."""
        tag = self._require_purpose_if_metered(purpose)
        bid = (batch_id or "").strip()
        if not bid:
            raise RuntimeError("Batch id is empty")
        raw = self._batch_rpc(
            "get",
            tag=tag,
            parent_id=parent_id,
            labels=labels,
            failed="Batch get failed",
            batch_id=bid,
        )
        try:
            out = batch_to_dict(raw)
        except Exception as exc:
            self._record_batch(
                tag=tag,
                parent_id=parent_id,
                labels=labels,
                success=False,
                error=_error_class(exc),
            )
            raise RuntimeError(f"Batch get failed: {exc}") from exc
        self._record_batch(
            tag=tag,
            parent_id=parent_id,
            labels=labels,
            success=True,
        )
        return out

    def cancel_batch(
        self,
        batch_id: str,
        *,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Cancel a batch (SDK ``client.batch.cancel``)."""
        tag = self._require_purpose_if_metered(purpose)
        bid = (batch_id or "").strip()
        if not bid:
            raise RuntimeError("Batch id is empty")
        raw = self._batch_rpc(
            "cancel",
            tag=tag,
            parent_id=parent_id,
            labels=labels,
            failed="Batch cancel failed",
            batch_id=bid,
        )
        try:
            out = batch_to_dict(raw)
        except Exception as exc:
            self._record_batch(
                tag=tag,
                parent_id=parent_id,
                labels=labels,
                success=False,
                error=_error_class(exc),
            )
            raise RuntimeError(f"Batch cancel failed: {exc}") from exc
        self._record_batch(
            tag=tag,
            parent_id=parent_id,
            labels=labels,
            success=True,
        )
        return out

    def list_batches(
        self,
        *,
        limit: int | None = None,
        pagination_token: str | None = None,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """List batches (SDK ``client.batch.list``). Returns ``{batches, pagination_token}``."""
        tag = self._require_purpose_if_metered(purpose)
        raw = self._batch_rpc(
            "list",
            tag=tag,
            parent_id=parent_id,
            labels=labels,
            failed="Batch list failed",
            limit=limit,
            pagination_token=(pagination_token or "").strip() or None,
        )
        try:
            out = list_batches_to_dict(raw)
        except Exception as exc:
            self._record_batch(
                tag=tag,
                parent_id=parent_id,
                labels=labels,
                success=False,
                error=_error_class(exc),
            )
            raise RuntimeError(f"Batch list failed: {exc}") from exc
        self._record_batch(
            tag=tag,
            parent_id=parent_id,
            labels=labels,
            success=True,
        )
        return out

    def list_batch_results(
        self,
        batch_id: str,
        *,
        limit: int | None = None,
        pagination_token: str | None = None,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """List batch results (SDK ``client.batch.list_batch_results``)."""
        tag = self._require_purpose_if_metered(purpose)
        bid = (batch_id or "").strip()
        if not bid:
            raise RuntimeError("Batch id is empty")
        raw = self._batch_rpc(
            "list_results",
            tag=tag,
            parent_id=parent_id,
            labels=labels,
            failed="Batch list results failed",
            batch_id=bid,
            limit=limit,
            pagination_token=(pagination_token or "").strip() or None,
        )
        try:
            out = list_results_to_dict(raw)
        except Exception as exc:
            self._record_batch(
                tag=tag,
                parent_id=parent_id,
                labels=labels,
                success=False,
                error=_error_class(exc),
            )
            raise RuntimeError(f"Batch list results failed: {exc}") from exc
        self._record_batch(
            tag=tag,
            parent_id=parent_id,
            labels=labels,
            success=True,
        )
        return out

    def _record_collections(
        self,
        *,
        tag: str | None,
        parent_id: str | None,
        labels: dict[str, str] | None,
        success: bool,
        error: str | None = None,
    ) -> None:
        self._record(
            purpose=tag,
            usage=None,
            parent_id=parent_id,
            labels=labels,
            success=success,
            thought_level=None,
            error=error,
            modality="collections",
            model="collections",
            apply_price_table=False,
        )

    def _collections_rpc(
        self,
        operation: str,
        *,
        tag: str | None,
        parent_id: str | None,
        labels: dict[str, str] | None,
        failed: str,
        **kwargs: Any,
    ) -> Any:
        try:
            return call_collections_rpc(
                operation,
                sdk_client=self._client,
                **kwargs,
            )
        except Exception as exc:
            self._record_collections(
                tag=tag,
                parent_id=parent_id,
                labels=labels,
                success=False,
                error=_error_class(exc),
            )
            logger.exception("xAI collections %s failed", operation)
            raise RuntimeError(f"{failed}: {exc}") from exc

    def create_collection(
        self,
        name: str,
        *,
        model_name: str | None = None,
        chunk_configuration: dict[str, Any] | None = None,
        description: str | None = None,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Create a collection (SDK ``client.collections.create``). Returns ``{id, name, …}``.

        Live create/get/list/delete/upload use the management API. Set
        ``XAI_MANAGEMENT_KEY`` in the environment; this client does not take a
        second key argument.
        """
        tag = self._require_purpose_if_metered(purpose)
        cleaned = (name or "").strip()
        if not cleaned:
            raise RuntimeError("Collection name is empty")
        pin = (model_name or "").strip() or None
        desc = (description or "").strip() or None
        raw = self._collections_rpc(
            "create",
            tag=tag,
            parent_id=parent_id,
            labels=labels,
            failed="Collection create failed",
            name=cleaned,
            model_name=pin,
            chunk_configuration=chunk_configuration,
            description=desc,
        )
        try:
            out = collection_to_dict(raw)
        except Exception as exc:
            self._record_collections(
                tag=tag,
                parent_id=parent_id,
                labels=labels,
                success=False,
                error=_error_class(exc),
            )
            raise RuntimeError(f"Collection create failed: {exc}") from exc
        self._record_collections(
            tag=tag,
            parent_id=parent_id,
            labels=labels,
            success=True,
        )
        return out

    def get_collection(
        self,
        collection_id: str,
        *,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Fetch collection metadata (SDK ``client.collections.get``)."""
        tag = self._require_purpose_if_metered(purpose)
        cid = (collection_id or "").strip()
        if not cid:
            raise RuntimeError("Collection id is empty")
        raw = self._collections_rpc(
            "get",
            tag=tag,
            parent_id=parent_id,
            labels=labels,
            failed="Collection get failed",
            collection_id=cid,
        )
        try:
            out = collection_to_dict(raw)
        except Exception as exc:
            self._record_collections(
                tag=tag,
                parent_id=parent_id,
                labels=labels,
                success=False,
                error=_error_class(exc),
            )
            raise RuntimeError(f"Collection get failed: {exc}") from exc
        self._record_collections(
            tag=tag,
            parent_id=parent_id,
            labels=labels,
            success=True,
        )
        return out

    def list_collections(
        self,
        *,
        limit: int | None = None,
        pagination_token: str | None = None,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """List collections (SDK ``client.collections.list``). Returns ``{collections, pagination_token}``."""
        tag = self._require_purpose_if_metered(purpose)
        raw = self._collections_rpc(
            "list",
            tag=tag,
            parent_id=parent_id,
            labels=labels,
            failed="Collection list failed",
            limit=limit,
            pagination_token=(pagination_token or "").strip() or None,
        )
        try:
            out = list_collections_to_dict(raw)
        except Exception as exc:
            self._record_collections(
                tag=tag,
                parent_id=parent_id,
                labels=labels,
                success=False,
                error=_error_class(exc),
            )
            raise RuntimeError(f"Collection list failed: {exc}") from exc
        self._record_collections(
            tag=tag,
            parent_id=parent_id,
            labels=labels,
            success=True,
        )
        return out

    def delete_collection(
        self,
        collection_id: str,
        *,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Delete a collection (SDK ``client.collections.delete``)."""
        tag = self._require_purpose_if_metered(purpose)
        cid = (collection_id or "").strip()
        if not cid:
            raise RuntimeError("Collection id is empty")
        raw = self._collections_rpc(
            "delete",
            tag=tag,
            parent_id=parent_id,
            labels=labels,
            failed="Collection delete failed",
            collection_id=cid,
        )
        out: dict[str, Any]
        if isinstance(raw, dict):
            out = dict(raw)
            out.setdefault("id", cid)
            out.setdefault("deleted", True)
        else:
            out = {"id": cid, "deleted": True}
        self._record_collections(
            tag=tag,
            parent_id=parent_id,
            labels=labels,
            success=True,
        )
        return out

    def upload_document(
        self,
        collection_id: str,
        name: str,
        data: bytes,
        *,
        fields: dict[str, str] | None = None,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Upload document bytes into a collection (SDK ``client.collections.upload_document``)."""
        tag = self._require_purpose_if_metered(purpose)
        cid = (collection_id or "").strip()
        if not cid:
            raise RuntimeError("Collection id is empty")
        filename = (name or "").strip()
        if not filename:
            raise RuntimeError("Document name is empty")
        if not data:
            raise RuntimeError("Document data is empty")
        raw = self._collections_rpc(
            "upload_document",
            tag=tag,
            parent_id=parent_id,
            labels=labels,
            failed="Document upload failed",
            collection_id=cid,
            name=filename,
            data=data,
            fields=fields,
        )
        try:
            out = document_to_dict(raw)
        except Exception as exc:
            self._record_collections(
                tag=tag,
                parent_id=parent_id,
                labels=labels,
                success=False,
                error=_error_class(exc),
            )
            raise RuntimeError(f"Document upload failed: {exc}") from exc
        self._record_collections(
            tag=tag,
            parent_id=parent_id,
            labels=labels,
            success=True,
        )
        return out

    def search_collections(
        self,
        query: str,
        collection_ids: str | list[str] | tuple[str, ...],
        *,
        limit: int | None = None,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Search collections (SDK ``client.collections.search``). Returns ``{matches}``.

        *collection_ids* may be one id string or a list. Search uses the regular
        API key (not the management key).
        """
        tag = self._require_purpose_if_metered(purpose)
        cleaned = (query or "").strip()
        if not cleaned:
            raise RuntimeError("Search query is empty")
        ids = normalize_collection_ids(collection_ids)
        raw = self._collections_rpc(
            "search",
            tag=tag,
            parent_id=parent_id,
            labels=labels,
            failed="Collection search failed",
            query=cleaned,
            collection_ids=ids,
            limit=limit,
        )
        try:
            out = search_to_dict(raw)
        except Exception as exc:
            self._record_collections(
                tag=tag,
                parent_id=parent_id,
                labels=labels,
                success=False,
                error=_error_class(exc),
            )
            raise RuntimeError(f"Collection search failed: {exc}") from exc
        self._record_collections(
            tag=tag,
            parent_id=parent_id,
            labels=labels,
            success=True,
        )
        return out

    def _submit_imagine(
        self,
        endpoint: str,
        body: dict[str, Any],
        *,
        image_model: str,
        tag: str | None,
        parent_id: str | None,
        labels: dict[str, str] | None,
        request_failed: str,
        http_failed: str,
    ) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = httpx.post(
                endpoint,
                headers=headers,
                json=body,
                timeout=180.0,
            )
        except httpx.HTTPError as exc:
            self._record(
                purpose=tag,
                usage=None,
                parent_id=parent_id,
                labels=labels,
                success=False,
                thought_level=None,
                error=_error_class(exc),
                modality="imagine",
                model=image_model,
            )
            logger.exception("xAI Imagine request failed")
            raise RuntimeError(f"{request_failed}: {exc}") from exc

        if response.status_code == 401:
            raise RuntimeError("xAI Imagine unauthorized — check API key")
        if response.status_code >= 400:
            detail = response.text[:500] if response.text else response.reason_phrase
            logger.error("xAI Imagine error %s: %s", response.status_code, detail)
            self._record(
                purpose=tag,
                usage=None,
                parent_id=parent_id,
                labels=labels,
                success=False,
                thought_level=None,
                error=f"HTTP{response.status_code}",
                modality="imagine",
                model=image_model,
            )
            raise RuntimeError(f"{http_failed} ({response.status_code}): {detail}")

        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError("Imagine returned non-JSON response") from exc

        url, b64, file_id = _parse_imagine_result(payload)
        self._record(
            purpose=tag,
            usage=None,
            parent_id=parent_id,
            labels=labels,
            success=True,
            thought_level=None,
            modality="imagine",
            model=image_model,
        )
        return {
            "url": url,
            "b64_json": b64,
            "model": image_model,
            "file_id": file_id,
        }

    def generate_image(
        self,
        prompt: str,
        *,
        model: str | None = None,
        aspect_ratio: str | None = None,
        n: int = 1,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Generate an image via xAI Imagine (REST ``/v1/images/generations``)."""
        tag = self._require_purpose_if_metered(purpose)
        cleaned = (prompt or "").strip()
        if not cleaned:
            raise RuntimeError("Image prompt is empty")

        image_model = (model or self.image_model or DEFAULT_IMAGE_MODEL).strip()
        body: dict[str, Any] = {
            "model": image_model,
            "prompt": cleaned,
            "n": max(1, min(int(n or 1), 4)),
        }
        if aspect_ratio:
            body["aspect_ratio"] = aspect_ratio

        return self._submit_imagine(
            XAI_IMAGES_URL,
            body,
            image_model=image_model,
            tag=tag,
            parent_id=parent_id,
            labels=labels,
            request_failed="Image generation request failed",
            http_failed="Image generation failed",
        )

    def edit_image(
        self,
        prompt: str,
        image: str | dict[str, Any] | None = None,
        *,
        image_url: str | None = None,
        image_file_id: str | None = None,
        model: str | None = None,
        aspect_ratio: str | None = None,
        n: int = 1,
        response_format: str | None = None,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Edit an image via xAI Imagine JSON ``POST /v1/images/edits`` (not multipart)."""
        tag = self._require_purpose_if_metered(purpose)
        cleaned = (prompt or "").strip()
        if not cleaned:
            raise RuntimeError("Image prompt is empty")

        image_obj = _imagine_edit_image_ref(
            image, url=image_url, file_id=image_file_id
        )
        image_model = (model or self.image_model or DEFAULT_IMAGE_MODEL).strip()
        body: dict[str, Any] = {
            "model": image_model,
            "prompt": cleaned,
            "n": max(1, min(int(n or 1), 4)),
            "image": image_obj,
        }
        if aspect_ratio:
            body["aspect_ratio"] = aspect_ratio
        if response_format:
            body["response_format"] = response_format

        return self._submit_imagine(
            XAI_IMAGE_EDITS_URL,
            body,
            image_model=image_model,
            tag=tag,
            parent_id=parent_id,
            labels=labels,
            request_failed="Image edit request failed",
            http_failed="Image edit failed",
        )

    def _video_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _effective_video_model(self, model: str | None) -> str:
        return (model or self.video_model or DEFAULT_VIDEO_MODEL).strip()

    def _record_video_failed(
        self,
        *,
        tag: str | None,
        parent_id: str | None,
        labels: dict[str, str] | None,
        error: str,
        video_model: str,
        usage: dict[str, Any] | None = None,
    ) -> None:
        self._record(
            purpose=tag,
            usage=usage,
            parent_id=parent_id,
            labels=labels,
            success=False,
            thought_level=None,
            error=error,
            modality="video",
            model=video_model,
        )

    def generate_video(
        self,
        prompt: str | None = None,
        *,
        model: str | None = None,
        duration: int | None = None,
        aspect_ratio: str | None = None,
        resolution: str | None = None,
        image_url: str | None = None,
        image_file_id: str | None = None,
        image: dict[str, Any] | None = None,
        reference_images: list[Any] | None = None,
        reference_audios: list[Any] | None = None,
        wait: bool = True,
        timeout: float = _VIDEO_WAIT_TIMEOUT,
        interval: float = _VIDEO_WAIT_INTERVAL,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Generate a video via xAI Imagine (REST ``/v1/videos/generations``).

        Default ``wait=True`` polls until ``done``. Pass ``wait=False`` to return
        the start payload (``request_id``) and call :meth:`poll_video` yourself.
        """
        tag = self._require_purpose_if_metered(purpose)
        video_model = self._effective_video_model(model)
        image_obj = _video_media_ref(image, url=image_url, file_id=image_file_id)
        ref_images = _video_reference_images(reference_images)
        ref_audios = _video_reference_audios(reference_audios)
        if image_obj is not None and ref_images:
            raise ValueError("image and reference_images cannot be combined")

        cleaned = (prompt or "").strip()
        is_i2v = image_obj is not None
        is_r2v = bool(ref_images) or bool(ref_audios)
        if not is_i2v and not cleaned:
            raise RuntimeError("Video prompt is empty")
        if is_r2v and not cleaned:
            raise RuntimeError("Video prompt is empty")

        if duration is not None and not (1 <= int(duration) <= 15):
            raise ValueError("duration must be between 1 and 15 seconds")
        aspect = _optional_aspect_ratio(aspect_ratio)
        res = _optional_resolution(resolution)

        body: dict[str, Any] = {"model": video_model}
        if cleaned:
            body["prompt"] = cleaned
        if duration is not None:
            body["duration"] = int(duration)
        if aspect:
            body["aspect_ratio"] = aspect
        if res:
            body["resolution"] = res
        if image_obj is not None:
            body["image"] = image_obj
        if ref_images:
            body["reference_images"] = ref_images
        if ref_audios:
            body["reference_audios"] = ref_audios

        return self._start_and_maybe_wait_video(
            XAI_VIDEOS_URL,
            body,
            tag=tag,
            parent_id=parent_id,
            labels=labels,
            video_model=video_model,
            wait=wait,
            timeout=timeout,
            interval=interval,
            resolution=res,
            requested_duration=int(duration) if duration is not None else None,
            action="Video generation",
        )

    def extend_video(
        self,
        prompt: str,
        *,
        video_url: str | None = None,
        video_file_id: str | None = None,
        video: dict[str, Any] | None = None,
        model: str | None = None,
        duration: int | None = None,
        wait: bool = True,
        timeout: float = _VIDEO_WAIT_TIMEOUT,
        interval: float = _VIDEO_WAIT_INTERVAL,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Extend a video via xAI Imagine (REST ``/v1/videos/extensions``)."""
        tag = self._require_purpose_if_metered(purpose)
        video_model = self._effective_video_model(model)
        cleaned = (prompt or "").strip()
        if not cleaned:
            raise RuntimeError("Video prompt is empty")
        video_obj = _video_media_ref(video, url=video_url, file_id=video_file_id)
        if not video_obj:
            raise RuntimeError("Video url or file_id is required to extend")
        if duration is not None and not (2 <= int(duration) <= 10):
            raise ValueError("extend duration must be between 2 and 10 seconds")

        body: dict[str, Any] = {
            "model": video_model,
            "prompt": cleaned,
            "video": video_obj,
        }
        if duration is not None:
            body["duration"] = int(duration)

        return self._start_and_maybe_wait_video(
            XAI_VIDEO_EXTENSIONS_URL,
            body,
            tag=tag,
            parent_id=parent_id,
            labels=labels,
            video_model=video_model,
            wait=wait,
            timeout=timeout,
            interval=interval,
            resolution=None,
            requested_duration=int(duration) if duration is not None else None,
            action="Video extension",
        )

    def poll_video(self, request_id: str) -> dict[str, Any]:
        """Single GET of ``/v1/videos/{request_id}`` (no wait loop)."""
        rid = (request_id or "").strip()
        if not rid:
            raise RuntimeError("Video request_id is empty")
        payload = self._get_video_status(rid)
        return _normalize_video_payload(payload, request_id=rid)

    def download_video(self, url: str) -> bytes:
        """GET a generated video URL and return the bytes."""
        cleaned = (url or "").strip()
        if not cleaned:
            raise RuntimeError("Video URL is empty")
        try:
            response = httpx.get(
                cleaned,
                timeout=_VIDEO_DOWNLOAD_TIMEOUT,
                follow_redirects=True,
            )
        except httpx.HTTPError as exc:
            logger.exception("xAI video download failed")
            raise RuntimeError(f"Video download failed: {exc}") from exc
        if response.status_code == 401:
            raise RuntimeError("xAI video download unauthorized — check API key")
        if response.status_code >= 400:
            detail = response.text[:500] if response.text else response.reason_phrase
            raise RuntimeError(
                f"Video download failed ({response.status_code}): {detail}"
            )
        if not response.content:
            raise RuntimeError("Video download returned empty body")
        return response.content

    def _effective_voice_model(self, model: str | None) -> str:
        return (model or self.voice_model or DEFAULT_VOICE_MODEL).strip()

    def _require_realtime_api_key(self) -> str:
        key = (self.api_key or "").strip()
        if not key:
            raise RuntimeError(
                "xAI credentials not configured. Pass api_key= or inject a "
                "CredentialStore before opening a realtime session."
            )
        return key

    def open_realtime_session(
        self,
        *,
        model: str | None = None,
        voice: str | None = None,
        instructions: str | None = None,
        turn_detection: Any = ...,
        tools: list[dict[str, Any]] | None = None,
        audio: dict[str, Any] | None = None,
        reasoning_effort: str | None = None,
        session: dict[str, Any] | None = None,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> RealtimeSession:
        """Open a speech-to-speech WebSocket session (documented realtime protocol).

        Connects to ``wss://api.x.ai/v1/realtime?model=…`` with
        ``Authorization: Bearer <api_key>``, then sends ``session.update``.
        REST STT/TTS stay on :meth:`transcribe` / :meth:`synthesize_speech`.
        """
        tag = self._require_purpose_if_metered(purpose)
        key = self._require_realtime_api_key()
        voice_model = self._effective_voice_model(model)
        url = realtime_session_url(voice_model, base=XAI_REALTIME_URL)
        headers = {"Authorization": f"Bearer {key}"}

        session_body = _realtime_session_body(
            voice=voice,
            instructions=instructions,
            turn_detection=turn_detection,
            tools=tools,
            audio=audio,
            reasoning_effort=reasoning_effort,
            session=session,
        )

        try:
            ws = connect_realtime_websocket(
                url,
                additional_headers=headers,
                open_timeout=_REALTIME_OPEN_TIMEOUT,
                close_timeout=_REALTIME_CLOSE_TIMEOUT,
            )
        except Exception as exc:
            self._record(
                purpose=tag,
                usage=None,
                parent_id=parent_id,
                labels=labels,
                success=False,
                thought_level=None,
                error=_error_class(exc),
                modality="realtime",
                model=voice_model,
            )
            logger.exception("xAI realtime connect failed")
            raise RuntimeError(f"Realtime session connect failed: {exc}") from exc

        rt = RealtimeSession(
            ws,
            model=voice_model,
            purpose=tag,
            parent_id=parent_id,
            labels=labels,
            record=self._record,
            error_class=_error_class,
        )
        rt.update_session(session_body)
        return rt

    def open_stt_session(
        self,
        *,
        sample_rate: int = DEFAULT_STT_SAMPLE_RATE,
        encoding: str = DEFAULT_STT_ENCODING,
        interim_results: bool | None = None,
        endpointing: int | None = None,
        language: str | None = None,
        diarize: bool | None = None,
        filler_words: bool | None = None,
        multichannel: bool | None = None,
        channels: int | None = None,
        keyterm: str | Sequence[str] | None = None,
        smart_turn: float | None = None,
        smart_turn_timeout: int | None = None,
        vad_threshold: float | None = None,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> SttSession:
        """Open a streaming speech-to-text WebSocket (not speech-to-speech).

        Connects to ``wss://api.x.ai/v1/stt`` with query knobs and
        ``Authorization: Bearer <api_key>``, then waits for
        ``transcript.created`` before the caller sends audio. REST file
        transcription stays on :meth:`transcribe`. STS stays on
        :meth:`open_realtime_session`.
        """
        tag = self._require_purpose_if_metered(purpose)
        key = self._require_stt_api_key()
        url = stt_session_url(
            base=XAI_STT_WS_URL,
            sample_rate=sample_rate,
            encoding=encoding,
            interim_results=interim_results,
            endpointing=endpointing,
            language=language,
            diarize=diarize,
            filler_words=filler_words,
            multichannel=multichannel,
            channels=channels,
            keyterm=keyterm,
            smart_turn=smart_turn,
            smart_turn_timeout=smart_turn_timeout,
            vad_threshold=vad_threshold,
        )
        headers = {"Authorization": f"Bearer {key}"}

        try:
            ws = connect_stt_websocket(
                url,
                additional_headers=headers,
                open_timeout=_REALTIME_OPEN_TIMEOUT,
                close_timeout=_REALTIME_CLOSE_TIMEOUT,
            )
        except Exception as exc:
            self._record(
                purpose=tag,
                usage=None,
                parent_id=parent_id,
                labels=labels,
                success=False,
                thought_level=None,
                error=_error_class(exc),
                modality="stt",
                model="stt",
            )
            logger.exception("xAI STT stream connect failed")
            raise RuntimeError(f"STT session connect failed: {exc}") from exc

        session = SttSession(
            ws,
            purpose=tag,
            parent_id=parent_id,
            labels=labels,
            record=self._record,
            error_class=_error_class,
            model="stt",
        )
        try:
            session.wait_ready(timeout=_REALTIME_OPEN_TIMEOUT)
        except Exception:
            session.close(success=False)
            raise
        return session

    def _require_stt_api_key(self) -> str:
        key = (self.api_key or "").strip()
        if not key:
            raise RuntimeError(
                "xAI credentials not configured. Pass api_key= or inject a "
                "CredentialStore before opening an STT session."
            )
        return key

    def _start_and_maybe_wait_video(
        self,
        url: str,
        body: dict[str, Any],
        *,
        tag: str | None,
        parent_id: str | None,
        labels: dict[str, str] | None,
        video_model: str,
        wait: bool,
        timeout: float,
        interval: float,
        resolution: str | None,
        requested_duration: int | None,
        action: str,
    ) -> dict[str, Any]:
        headers = self._video_headers()
        try:
            response = httpx.post(
                url,
                headers=headers,
                json=body,
                timeout=_VIDEO_START_TIMEOUT,
            )
        except httpx.HTTPError as exc:
            self._record_video_failed(
                tag=tag,
                parent_id=parent_id,
                labels=labels,
                error=_error_class(exc),
                video_model=video_model,
            )
            logger.exception("xAI %s request failed", action)
            raise RuntimeError(f"{action} request failed: {exc}") from exc

        if response.status_code == 401:
            raise RuntimeError(f"xAI {action.lower()} unauthorized — check API key")
        if response.status_code >= 400:
            detail = response.text[:500] if response.text else response.reason_phrase
            logger.error("xAI %s error %s: %s", action, response.status_code, detail)
            self._record_video_failed(
                tag=tag,
                parent_id=parent_id,
                labels=labels,
                error=f"HTTP{response.status_code}",
                video_model=video_model,
            )
            raise RuntimeError(f"{action} failed ({response.status_code}): {detail}")

        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{action} returned non-JSON response") from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"{action} returned unexpected payload")

        request_id = str(payload.get("request_id") or "").strip()
        if not request_id:
            raise RuntimeError(f"{action} response missing request_id")

        start_usage = _video_meter_usage(
            None,
            requested_duration=requested_duration,
            resolution=resolution,
        )
        if not wait:
            self._record(
                purpose=tag,
                usage=start_usage,
                parent_id=parent_id,
                labels=labels,
                success=True,
                thought_level=None,
                modality="video",
                model=video_model,
            )
            return _normalize_video_payload(
                {"request_id": request_id, "status": "pending", "model": video_model},
                request_id=request_id,
            )

        return self._wait_for_video(
            request_id,
            tag=tag,
            parent_id=parent_id,
            labels=labels,
            video_model=video_model,
            timeout=timeout,
            interval=interval,
            resolution=resolution,
            requested_duration=requested_duration,
            action=action,
        )

    def _wait_for_video(
        self,
        request_id: str,
        *,
        tag: str | None,
        parent_id: str | None,
        labels: dict[str, str] | None,
        video_model: str,
        timeout: float,
        interval: float,
        resolution: str | None,
        requested_duration: int | None,
        action: str,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + max(0.0, float(timeout))
        poll_interval = max(0.0, float(interval))
        while True:
            try:
                payload = self._get_video_status(request_id)
            except Exception as exc:
                self._record_video_failed(
                    tag=tag,
                    parent_id=parent_id,
                    labels=labels,
                    error=_error_class(exc),
                    video_model=video_model,
                )
                raise

            status = str(payload.get("status") or "").strip().lower()
            if status == "done":
                usage = _video_meter_usage(
                    payload,
                    requested_duration=requested_duration,
                    resolution=resolution,
                )
                self._record(
                    purpose=tag,
                    usage=usage,
                    parent_id=parent_id,
                    labels=labels,
                    success=True,
                    thought_level=None,
                    modality="video",
                    model=str(payload.get("model") or video_model),
                )
                return _normalize_video_payload(payload, request_id=request_id)
            if status in {"failed", "expired"}:
                message = _video_error_message(payload) or status
                self._record_video_failed(
                    tag=tag,
                    parent_id=parent_id,
                    labels=labels,
                    error=f"video_{status}",
                    video_model=video_model,
                    usage=_video_meter_usage(
                        payload,
                        requested_duration=requested_duration,
                        resolution=resolution,
                    ),
                )
                raise RuntimeError(f"{action} {status}: {message}")
            if time.monotonic() >= deadline:
                self._record_video_failed(
                    tag=tag,
                    parent_id=parent_id,
                    labels=labels,
                    error="video_timeout",
                    video_model=video_model,
                )
                raise RuntimeError(f"{action} timed out waiting for request_id={request_id}")
            remaining = deadline - time.monotonic()
            sleep_for = poll_interval if poll_interval > 0 else 0.0
            if sleep_for > remaining:
                sleep_for = max(0.0, remaining)
            if sleep_for > 0:
                time.sleep(sleep_for)

    def _get_video_status(self, request_id: str) -> dict[str, Any]:
        url = XAI_VIDEO_STATUS_URL.format(request_id=request_id)
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            response = httpx.get(url, headers=headers, timeout=_VIDEO_POLL_TIMEOUT)
        except httpx.HTTPError as exc:
            logger.exception("xAI video poll request failed")
            raise RuntimeError(f"Video poll request failed: {exc}") from exc
        if response.status_code == 401:
            raise RuntimeError("xAI video poll unauthorized — check API key")
        if response.status_code >= 400:
            detail = response.text[:500] if response.text else response.reason_phrase
            logger.error("xAI video poll error %s: %s", response.status_code, detail)
            raise RuntimeError(f"Video poll failed ({response.status_code}): {detail}")
        if response.status_code == 202:
            if response.text.strip():
                try:
                    payload = response.json()
                    if isinstance(payload, dict):
                        return payload
                except json.JSONDecodeError:
                    pass
            return {"status": "pending", "request_id": request_id}
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError("Video poll returned non-JSON response") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Video poll returned unexpected payload")
        return payload


def _file_resource_url(file_id: str) -> str:
    cleaned = (file_id or "").strip()
    if not cleaned:
        raise RuntimeError("file_id is empty")
    return f"{XAI_FILES_URL}/{cleaned}"


def _response_resource_url(response_id: str) -> str:
    cleaned = (response_id or "").strip()
    if not cleaned:
        raise RuntimeError("Response id is empty")
    return f"{XAI_RESPONSES_URL}/{cleaned}"


def _normalize_response_input(value: Any) -> str | list[Any]:
    """Reject empty input before HTTP. OpenAPI ``ModelInput`` is string or list."""
    if isinstance(value, str):
        if not value.strip():
            raise RuntimeError("Response input is empty")
        return value
    if isinstance(value, list):
        if not value:
            raise RuntimeError("Response input is empty")
        return value
    raise RuntimeError("Response input must be a string or list")


def _normalize_response_tools(
    tools: list[dict[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    """Pass tools through when given. Omit (None) means never default-on."""
    if tools is None:
        return None
    if not isinstance(tools, list):
        raise RuntimeError("Response tools must be a list")
    if len(tools) > XAI_RESPONSES_MAX_TOOLS:
        raise RuntimeError(
            f"Response tools list exceeds {XAI_RESPONSES_MAX_TOOLS} items"
        )
    return tools


def _parse_response_payload(payload: Any) -> dict[str, Any]:
    """Return the documented REST object; require ``id``."""
    if not isinstance(payload, dict):
        raise RuntimeError("Responses response is not a JSON object")
    raw_id = payload.get("id")
    if raw_id is None or not str(raw_id).strip():
        raise RuntimeError("Responses response missing id")
    out = dict(payload)
    out["id"] = str(raw_id).strip()
    return out


def _parse_file_metadata(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RuntimeError("Files response is not a JSON object")
    raw_id = payload.get("id")
    if raw_id is None or not str(raw_id).strip():
        raise RuntimeError("Files response missing id")
    out: dict[str, Any] = {
        "id": str(raw_id).strip(),
        "filename": payload.get("filename"),
        "bytes": payload.get("bytes"),
        "created_at": payload.get("created_at"),
        "expires_at": payload.get("expires_at"),
        "object": payload.get("object"),
        "purpose": payload.get("purpose"),
    }
    for key in ("public_url", "public_url_expires_at"):
        if key in payload:
            out[key] = payload[key]
    return out


def _normalize_embed_texts(texts: str | list[str]) -> str | list[str]:
    """Reject empty input before HTTP. Documented max list length is 128."""
    if isinstance(texts, str):
        if not texts.strip():
            raise RuntimeError("Embed input is empty")
        return texts
    if isinstance(texts, list):
        if not texts:
            raise RuntimeError("Embed input is empty")
        if len(texts) > XAI_EMBED_MAX_INPUTS:
            raise RuntimeError(
                f"Embed input list exceeds {XAI_EMBED_MAX_INPUTS} items"
            )
        for item in texts:
            if not isinstance(item, str):
                raise RuntimeError("Embed input items must be strings")
            if not item.strip():
                raise RuntimeError("Embed input is empty")
        return texts
    raise RuntimeError("Embed input must be a string or list of strings")


def _parse_embed_usage(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return None
    out: dict[str, Any] = {}
    for key in ("prompt_tokens", "total_tokens"):
        if raw.get(key) is not None:
            out[key] = raw[key]
    return out or None


def _parse_embed_response(payload: Any, *, fallback_model: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RuntimeError("Embeddings response is not a JSON object")
    raw_data = payload.get("data")
    if not isinstance(raw_data, list) or not raw_data:
        raise RuntimeError("Embeddings response missing data")
    rows: list[dict[str, Any]] = []
    for item in raw_data:
        if not isinstance(item, dict):
            raise RuntimeError("Embeddings response data item is invalid")
        if "embedding" not in item:
            raise RuntimeError("Embeddings response missing embedding")
        index = item.get("index")
        row: dict[str, Any] = {
            "index": int(index) if index is not None else len(rows),
            "embedding": item.get("embedding"),
        }
        if "object" in item:
            row["object"] = item.get("object")
        rows.append(row)
    rows.sort(key=lambda row: int(row["index"]))
    model = payload.get("model")
    return {
        "object": payload.get("object") or "list",
        "model": str(model).strip() if model is not None and str(model).strip() else fallback_model,
        "data": rows,
        "usage": _parse_embed_usage(payload.get("usage")),
    }


def _normalize_tokenize_text(text: str) -> str:
    """Reject empty input before HTTP."""
    if not isinstance(text, str):
        raise RuntimeError("Tokenize text must be a string")
    if not text.strip():
        raise RuntimeError("Tokenize text is empty")
    return text


def _token_bytes_list(raw: Any) -> list[int] | None:
    if raw is None:
        return None
    if isinstance(raw, (bytes, bytearray)):
        return list(raw)
    if isinstance(raw, str):
        return [ord(ch) for ch in raw]
    if isinstance(raw, list):
        out: list[int] = []
        for item in raw:
            try:
                out.append(int(item))
            except (TypeError, ValueError) as exc:
                raise RuntimeError("Tokenize token_bytes item is invalid") from exc
        return out
    raise RuntimeError("Tokenize token_bytes is invalid")


def _parse_tokenize_token(item: Any) -> dict[str, Any]:
    """Map OpenAPI/proto token fields to JSON-dict ``{token_id, string, …}``."""
    if not isinstance(item, dict):
        raise RuntimeError("Tokenize token is invalid")
    raw_id = item.get("token_id")
    if raw_id is None:
        raise RuntimeError("Tokenize token missing token_id")
    try:
        token_id = int(raw_id)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Tokenize token_id is invalid") from exc
    string_val = item.get("string")
    if string_val is None:
        string_val = item.get("string_token")
    row: dict[str, Any] = {
        "token_id": token_id,
        "string": "" if string_val is None else str(string_val),
    }
    token_bytes = _token_bytes_list(item.get("token_bytes"))
    if token_bytes is not None:
        row["token_bytes"] = token_bytes
    return row


def _parse_tokenize_response(payload: Any, *, fallback_model: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RuntimeError("Tokenize response is not a JSON object")
    raw_tokens = payload.get("token_ids")
    if raw_tokens is None:
        raw_tokens = payload.get("tokens")
    if not isinstance(raw_tokens, list):
        raise RuntimeError("Tokenize response missing tokens")
    tokens = [_parse_tokenize_token(item) for item in raw_tokens]
    model = payload.get("model")
    return {
        "tokens": tokens,
        "count": len(tokens),
        "model": (
            str(model).strip()
            if model is not None and str(model).strip()
            else fallback_model
        ),
    }


def _imagine_file_id(
    item: dict[str, Any], payload: dict[str, Any] | None = None
) -> str | None:
    sources: list[dict[str, Any]] = [item]
    if isinstance(payload, dict):
        sources.append(payload)
    for source in sources:
        raw = source.get("file_id")
        if raw is not None and str(raw).strip():
            return str(raw).strip()
        output = source.get("file_output")
        if isinstance(output, dict):
            nested = output.get("file_id")
            if nested is not None and str(nested).strip():
                return str(nested).strip()
    return None


def _parse_imagine_result(payload: Any) -> tuple[str | None, str | None, str | None]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list) or not data:
        raise RuntimeError("Imagine response missing data")
    first = data[0] if isinstance(data[0], dict) else {}
    url = first.get("url")
    b64 = first.get("b64_json")
    file_id = _imagine_file_id(first, payload if isinstance(payload, dict) else None)
    if not url and not b64 and not file_id:
        raise RuntimeError("Imagine response missing url and b64_json")
    return (
        str(url) if url else None,
        str(b64) if b64 else None,
        file_id,
    )


def _imagine_edit_image_ref(
    explicit: str | dict[str, Any] | None,
    *,
    url: str | None = None,
    file_id: str | None = None,
) -> dict[str, Any]:
    source: dict[str, Any] = dict(explicit) if isinstance(explicit, dict) else {}
    if isinstance(explicit, str):
        raw = explicit.strip()
        if raw.startswith(("http://", "https://", "data:")):
            url = url or raw
        elif raw:
            file_id = file_id or raw
    url_val = url or source.get("url") or source.get("image_url")
    file_val = file_id or source.get("file_id")
    url_s = str(url_val).strip() if url_val else ""
    file_s = str(file_val).strip() if file_val else ""
    if url_s and file_s:
        raise ValueError("url and file_id are mutually exclusive")
    if url_s:
        return {"url": url_s, "type": "image_url"}
    if file_s:
        return {"file_id": file_s}
    raise RuntimeError("Image url or file_id is empty")


def _optional_aspect_ratio(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    if raw not in _VIDEO_ASPECT_RATIOS:
        raise ValueError(
            f"aspect_ratio must be one of {sorted(_VIDEO_ASPECT_RATIOS)}"
        )
    return raw


def _optional_resolution(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    if raw not in _VIDEO_RESOLUTIONS:
        raise ValueError(f"resolution must be one of {sorted(_VIDEO_RESOLUTIONS)}")
    return raw


def _video_media_ref(
    explicit: dict[str, Any] | None,
    *,
    url: str | None = None,
    file_id: str | None = None,
) -> dict[str, str] | None:
    source = dict(explicit) if isinstance(explicit, dict) else {}
    url_val = url or source.get("url") or source.get("image_url")
    file_val = file_id or source.get("file_id")
    url_s = str(url_val).strip() if url_val else ""
    file_s = str(file_val).strip() if file_val else ""
    if url_s and file_s:
        raise ValueError("url and file_id are mutually exclusive")
    if url_s:
        return {"url": url_s}
    if file_s:
        return {"file_id": file_s}
    return None


def _video_reference_images(items: list[Any] | None) -> list[dict[str, str]]:
    if not items:
        return []
    out: list[dict[str, str]] = []
    for item in items:
        if isinstance(item, str):
            ref = _video_media_ref(None, url=item)
        elif isinstance(item, dict):
            ref = _video_media_ref(item)
        else:
            raise ValueError("reference_images entries must be url strings or {url|file_id} dicts")
        if not ref:
            raise ValueError("reference_images entry missing url or file_id")
        out.append(ref)
    return out


def _video_reference_audios(items: list[Any] | None) -> list[dict[str, str]]:
    if not items:
        return []
    if len(items) > _VIDEO_MAX_REFERENCE_AUDIOS:
        raise ValueError(
            f"reference_audios accepts at most {_VIDEO_MAX_REFERENCE_AUDIOS} voices"
        )
    out: list[dict[str, str]] = []
    for item in items:
        if isinstance(item, str):
            voice = item.strip()
        elif isinstance(item, dict):
            voice = str(item.get("voice_id") or "").strip()
        else:
            raise ValueError("reference_audios entries must be voice_id strings or {voice_id} dicts")
        if not voice:
            raise ValueError("reference_audios entry missing voice_id")
        out.append({"voice_id": voice})
    return out


def _video_error_message(payload: dict[str, Any]) -> str | None:
    err = payload.get("error")
    if isinstance(err, dict):
        msg = err.get("message")
        if msg:
            return str(msg)
    message = payload.get("message")
    if message:
        return str(message)
    return None


def _video_meter_usage(
    payload: dict[str, Any] | None,
    *,
    requested_duration: int | None,
    resolution: str | None,
) -> dict[str, Any] | None:
    """Best-effort usage dict for the meter. Never raises."""
    try:
        out: dict[str, Any] = {}
        usage = payload.get("usage") if isinstance(payload, dict) else None
        if isinstance(usage, dict):
            for key in (
                "cost_in_usd_ticks",
                "input_tokens",
                "output_tokens",
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
            ):
                if usage.get(key) is not None:
                    out[key] = usage[key]
        video = payload.get("video") if isinstance(payload, dict) else None
        duration = None
        if isinstance(video, dict) and video.get("duration") is not None:
            duration = video.get("duration")
        if duration is None:
            duration = requested_duration
        if duration is not None:
            out["duration"] = duration
        if resolution:
            out["resolution"] = resolution
        return out or None
    except Exception:
        return None


def _normalize_video_payload(
    payload: dict[str, Any],
    *,
    request_id: str | None = None,
) -> dict[str, Any]:
    video = payload.get("video") if isinstance(payload.get("video"), dict) else {}
    rid = (request_id or payload.get("request_id") or "") or None
    if rid:
        rid = str(rid)
    return {
        "request_id": rid,
        "status": payload.get("status"),
        "url": video.get("url"),
        "duration": video.get("duration"),
        "model": payload.get("model"),
        "respect_moderation": video.get("respect_moderation"),
    }


def _realtime_session_body(
    *,
    voice: str | None,
    instructions: str | None,
    turn_detection: Any,
    tools: list[dict[str, Any]] | None,
    audio: dict[str, Any] | None,
    reasoning_effort: str | None,
    session: dict[str, Any] | None,
) -> dict[str, Any]:
    extras = dict(session) if isinstance(session, dict) else {}
    body: dict[str, Any] = {}
    if "voice" not in extras:
        body["voice"] = DEFAULT_REALTIME_VOICE
    if "turn_detection" not in extras and turn_detection is ...:
        body["turn_detection"] = {"type": "server_vad"}
    body.update(extras)
    if voice is not None:
        cleaned = str(voice).strip()
        if cleaned:
            body["voice"] = cleaned
    if instructions is not None:
        cleaned = str(instructions).strip()
        if cleaned:
            body["instructions"] = cleaned
    if turn_detection is not ...:
        if turn_detection is False:
            body["turn_detection"] = None
        else:
            body["turn_detection"] = turn_detection
    if tools is not None:
        body["tools"] = tools
    if audio is not None:
        body["audio"] = audio
    if reasoning_effort is not None:
        effort = str(reasoning_effort).strip()
        if effort:
            reasoning = dict(body.get("reasoning") or {})
            if isinstance(body.get("reasoning"), dict):
                reasoning = dict(body["reasoning"])
            reasoning["effort"] = effort
            body["reasoning"] = reasoning
    return body
