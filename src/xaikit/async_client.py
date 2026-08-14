"""Async twin of :class:`xaikit.client.XaiClient` — same method names, real async I/O."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx
from xai_sdk import AsyncClient

from xaikit.batch import (
    batch_to_dict,
    call_batch_rpc_async,
    list_batches_to_dict,
    list_results_to_dict,
    normalize_batch_requests,
)
from xaikit.catalog import (
    BOOTSTRAP_MODEL,
    DEFAULT_IMAGE_MODEL,
    DEFAULT_VIDEO_MODEL,
    contract_imagine_aspect_ratio,
    imagine_generate_knobs,
    normalize_thought_level,
    resolve_model_selection,
)
from xaikit.client import (
    DEFAULT_FILE_PURPOSE,
    DEFAULT_TTS_VOICE_ID,
    XAI_CHAT_COMPLETIONS_URL,
    XAI_EMBEDDINGS_URL,
    XAI_FILE_MAX_BYTES,
    XAI_FILES_URL,
    XAI_IMAGE_EDITS_URL,
    XAI_IMAGES_URL,
    XAI_REALTIME_CLIENT_SECRETS_URL,
    XAI_RESPONSES_URL,
    XAI_STT_URL,
    XAI_TOKENIZE_URL,
    XAI_TTS_URL,
    XAI_TTS_VOICES_URL,
    XAI_VIDEO_EXTENSIONS_URL,
    XAI_VIDEO_STATUS_URL,
    XAI_VIDEOS_URL,
    XaiClient,
    _DEFERRED_CHAT_TIMEOUT,
    _EMBED_TIMEOUT,
    _FILES_EXPIRES_AFTER_MAX,
    _FILES_EXPIRES_AFTER_MIN,
    _FILES_TIMEOUT,
    _JSON_FENCE,
    _REALTIME_CLIENT_SECRETS_TIMEOUT,
    _REALTIME_CLOSE_TIMEOUT,
    _REALTIME_OPEN_TIMEOUT,
    _RESPONSES_TIMEOUT,
    _TOKENIZE_TIMEOUT,
    _TTS_VOICES_TIMEOUT,
    _VIDEO_DOWNLOAD_TIMEOUT,
    _VIDEO_POLL_TIMEOUT,
    _VIDEO_START_TIMEOUT,
    _VIDEO_WAIT_INTERVAL,
    _VIDEO_WAIT_TIMEOUT,
    _deferred_chat_resource_url,
    _error_class,
    _file_resource_url,
    _imagine_edit_source_fields,
    _is_unauthorized_status,
    _normalize_embed_texts,
    _normalize_realtime_client_secret_expires_after,
    _normalize_response_input,
    _normalize_response_tools,
    _normalize_service_tier,
    _normalize_tokenize_text,
    _normalize_video_payload,
    _contract_video_resolution,
    _optional_aspect_ratio,
    _parse_deferred_create,
    _parse_embed_response,
    _parse_file_metadata,
    _parse_imagine_result,
    _parse_response_payload,
    _parse_tokenize_response,
    _realtime_session_body,
    _response_resource_url,
    _tts_voice_resource_url,
    _video_error_message,
    _video_media_ref,
    _video_meter_usage,
    _video_reference_audios,
    _video_reference_images,
)
from xaikit.collections import (
    call_collections_rpc_async,
    collection_to_dict,
    document_to_dict,
    list_collections_to_dict,
    normalize_collection_ids,
    search_to_dict,
)
from xaikit.credentials import CredentialStore
from xaikit.provider import AsyncChatProvider, AsyncSdkChatProvider, ChatProvider
from xaikit.realtime import (
    DEFAULT_VOICE_MODEL,
    XAI_REALTIME_URL,
    AsyncRealtimeSession,
    connect_realtime_websocket_async,
    realtime_session_url,
)
from xaikit.retry import RetryPolicy, async_call_with_retry, default_retry_policy
from xaikit.stt_stream import (
    DEFAULT_STT_ENCODING,
    DEFAULT_STT_SAMPLE_RATE,
    XAI_STT_WS_URL,
    AsyncSttSession,
    connect_stt_websocket_async,
    stt_session_url,
)
from xaikit.traces import CompletionTracer
from xaikit.tts_stream import (
    DEFAULT_TTS_CODEC,
    DEFAULT_TTS_WS_LANGUAGE,
    XAI_TTS_WS_URL,
    AsyncTtsSession,
    connect_tts_websocket_async,
    tts_rest_accept,
    tts_rest_body,
    tts_session_url,
)
from xaikit.types import CompletionResponse, StreamChunk
from xaikit.usage import UsageMeter

logger = logging.getLogger(__name__)


def _is_async_callable(fn: Any) -> bool:
    if fn is None:
        return False
    if inspect.iscoroutinefunction(fn) or inspect.isasyncgenfunction(fn):
        return True
    call = getattr(fn, "__call__", None)
    return inspect.iscoroutinefunction(call) or inspect.isasyncgenfunction(call)


class AsyncXaiClient(XaiClient):
    """Async twin of :class:`XaiClient` — same public method names, all awaitable."""

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
        provider: ChatProvider | AsyncChatProvider | None = None,
        retry_policy: RetryPolicy | None = None,
        credential_store: CredentialStore | None = None,
        subject: str | None = None,
        image_model: str | None = None,
        video_model: str | None = None,
        voice_model: str | None = None,
        bootstrap_model: str = BOOTSTRAP_MODEL,
        completion_tracer: CompletionTracer | None = None,
    ) -> None:
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
            self._provider = provider
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
            management_api_key = (os.environ.get("XAI_MANAGEMENT_KEY") or "").strip() or None
            self._client = AsyncClient(
                api_key=key,
                management_api_key=management_api_key,
            )
            self._provider = AsyncSdkChatProvider(self._client)

        self._usage_meter = usage_meter
        self._completion_tracer = completion_tracer
        self._retry_policy = (
            retry_policy if retry_policy is not None else default_retry_policy()
        )
        self.image_model = (image_model or DEFAULT_IMAGE_MODEL).strip()
        self.video_model = (video_model or DEFAULT_VIDEO_MODEL).strip()
        self.voice_model = (voice_model or DEFAULT_VOICE_MODEL).strip()
        self._http: httpx.AsyncClient | None = None
        self._owns_http = False

    async def __aenter__(self) -> AsyncXaiClient:
        if self._http is None:
            self._http = httpx.AsyncClient()
            self._owns_http = True
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._http is not None and self._owns_http:
            await self._http.aclose()
            self._http = None
            self._owns_http = False
        sdk = self._client
        if sdk is not None:
            closer = getattr(sdk, "close", None)
            if callable(closer):
                result = closer()
                if inspect.isawaitable(result):
                    await result

    async def _http_request(
        self,
        method: str,
        url: str,
        *,
        timeout: float,
        **kwargs: Any,
    ) -> httpx.Response:
        if self._http is not None:
            return await self._http.request(method, url, timeout=timeout, **kwargs)
        async with httpx.AsyncClient(timeout=timeout) as client:
            return await client.request(method, url, **kwargs)

    async def _rest(
        self,
        method: str,
        url: str,
        *,
        timeout: float,
        headers: dict[str, str],
        unauthorized: str,
        fail_prefix: str,
        record_fail: Any = None,
        extra_status: dict[int, tuple[str, bool]] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        try:
            response = await self._http_request(
                method, url, timeout=timeout, headers=headers, **kwargs
            )
        except httpx.HTTPError as exc:
            if record_fail is not None:
                record_fail(_error_class(exc))
            logger.exception("%s request failed", fail_prefix)
            raise RuntimeError(f"{fail_prefix} request failed: {exc}") from exc

        if response.status_code == 401:
            raise RuntimeError(unauthorized)
        extra = extra_status or {}
        if response.status_code in extra:
            message, do_record = extra[response.status_code]
            if do_record and record_fail is not None:
                record_fail(f"HTTP{response.status_code}")
            raise RuntimeError(message)
        if response.status_code >= 400:
            detail = response.text[:500] if response.text else response.reason_phrase
            logger.error("%s error %s: %s", fail_prefix, response.status_code, detail)
            if record_fail is not None:
                record_fail(f"HTTP{response.status_code}")
            raise RuntimeError(
                f"{fail_prefix} failed ({response.status_code}): {detail}"
            )
        return response

    async def _provider_complete(self, **kwargs: Any) -> Any:
        provider = self._provider
        fn = getattr(provider, "async_complete", None)
        if callable(fn):
            return await fn(**kwargs)
        complete = getattr(provider, "complete", None)
        if _is_async_callable(complete):
            return await complete(**kwargs)
        raise TypeError(
            "AsyncXaiClient requires a provider with async_complete or async complete()"
        )

    def _provider_stream(self, **kwargs: Any) -> Any:
        provider = self._provider
        fn = getattr(provider, "async_stream", None)
        if callable(fn):
            return fn(**kwargs)
        stream = getattr(provider, "stream", None)
        if not callable(stream):
            raise TypeError(
                "AsyncXaiClient requires a provider with async_stream or async stream()"
            )
        if _is_async_callable(stream) or inspect.isasyncgenfunction(stream):
            return stream(**kwargs)
        # AsyncChatProvider types stream as a plain def returning AsyncIterator.
        result = stream(**kwargs)
        if hasattr(result, "__aiter__"):
            return result
        raise TypeError(
            "AsyncXaiClient requires a provider with async_stream or async stream()"
        )

    async def _complete(
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
        service_tier: str | None = None,
    ):
        async def _call():
            return await self._provider_complete(
                messages=messages,
                model=self.model,
                temperature=temperature,
                max_tokens=max_tokens,
                thought_level=thought_level,
                system_prompt=system_prompt,
                tools=tools,
                tool_choice=tool_choice,
                parallel_tool_calls=parallel_tool_calls,
                response_format=response_format,
                service_tier=service_tier,
            )

        return await async_call_with_retry(
            _call,
            policy=self._retry_policy,
            label="xai.complete",
        )

    async def _open_stream(
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
        service_tier: str | None = None,
    ):
        async def _call():
            return self._provider_stream(
                messages=messages,
                model=self.model,
                temperature=temperature,
                max_tokens=max_tokens,
                thought_level=thought_level,
                system_prompt=system_prompt,
                tools=tools,
                tool_choice=tool_choice,
                parallel_tool_calls=parallel_tool_calls,
                response_format=response_format,
                service_tier=service_tier,
            )

        return await async_call_with_retry(
            _call,
            policy=self._retry_policy,
            label="xai.stream",
        )

    async def chat(
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
        service_tier: str | None = None,
    ) -> CompletionResponse:
        tag = self._require_purpose_if_metered(purpose)
        level = self._effective_thought_level(thought_level, effort=effort)
        tier = _normalize_service_tier(service_tier)
        usage: dict[str, Any] | None = None
        try:
            resp = await self._complete(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                thought_level=level,
                system_prompt=system_prompt,
                tools=tools,
                tool_choice=tool_choice,
                parallel_tool_calls=parallel_tool_calls,
                service_tier=tier,
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
                service_tier=getattr(resp, "service_tier", None) or tier,
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

    async def chat_json(
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
        service_tier: str | None = None,
    ) -> dict[str, Any]:
        tag = self._require_purpose_if_metered(purpose)
        level = self._effective_thought_level(thought_level, effort=effort)
        messages = [{"role": "user", "content": user_prompt}]
        sys = system_prompt or (
            "You return ONLY valid JSON (no markdown fences) matching the requested shape."
        )
        fmt = schema if schema is not None else response_format
        tier = _normalize_service_tier(service_tier)
        usage: dict[str, Any] | None = None
        try:
            resp = await self._complete(
                messages,
                temperature=temperature,
                thought_level=level,
                system_prompt=sys,
                response_format=fmt,
                service_tier=tier,
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

    async def chat_stream(
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
        service_tier: str | None = None,
    ) -> AsyncIterator[StreamChunk]:
        tag = self._require_purpose_if_metered(purpose)
        level = self._effective_thought_level(thought_level, effort=effort)
        tier = _normalize_service_tier(service_tier)
        usage: dict[str, Any] | None = None
        accumulated = ""
        try:
            stream = await self._open_stream(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                thought_level=level,
                system_prompt=system_prompt,
                tools=tools,
                tool_choice=tool_choice,
                parallel_tool_calls=parallel_tool_calls,
                service_tier=tier,
            )
            async for piece in stream:
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

    async def create_deferred_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        system_prompt: str | None = None,
        thought_level: str | None = None,
        effort: str | None = None,
        service_tier: str | None = None,
    ) -> dict[str, Any]:
        tag = self._require_purpose_if_metered(purpose)
        if not isinstance(messages, list) or not messages:
            raise RuntimeError("Chat messages are empty")
        pin = (model or "").strip() or (self.model or "").strip()
        if not pin:
            raise RuntimeError("model is required for create_deferred_chat")
        tier = _normalize_service_tier(service_tier)
        level = self._effective_thought_level(thought_level, effort=effort, model=pin)
        rest_messages = list(messages)
        if system_prompt:
            rest_messages.insert(0, {"role": "system", "content": system_prompt})
        body: dict[str, Any] = {
            "model": pin,
            "messages": rest_messages,
            "deferred": True,
            "temperature": temperature,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if level:
            body["reasoning_effort"] = level
        if tier is not None:
            body["service_tier"] = tier
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        response = await self._rest(
            "POST",
            XAI_CHAT_COMPLETIONS_URL,
            timeout=_DEFERRED_CHAT_TIMEOUT,
            headers=headers,
            unauthorized="xAI deferred chat unauthorized — check API key",
            fail_prefix="Deferred chat",
            record_fail=lambda err: self._record_deferred_chat(
                tag=tag, parent_id=parent_id, labels=labels, success=False, error=err, model=pin
            ),
            json=body,
        )
        if response.status_code != 200:
            raise RuntimeError(f"Deferred chat create failed ({response.status_code})")
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError("Deferred chat create returned non-JSON response") from exc
        out = _parse_deferred_create(payload)
        self._record_deferred_chat(
            tag=tag, parent_id=parent_id, labels=labels, success=True, model=pin
        )
        return out

    async def get_deferred_chat(
        self,
        request_id: str,
        *,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        tag = self._require_purpose_if_metered(purpose)
        url = _deferred_chat_resource_url(request_id)
        pin = (self.model or "").strip() or "chat"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        response = await self._rest(
            "GET",
            url,
            timeout=_DEFERRED_CHAT_TIMEOUT,
            headers=headers,
            unauthorized="xAI deferred chat unauthorized — check API key",
            fail_prefix="Deferred chat",
            record_fail=lambda err: self._record_deferred_chat(
                tag=tag, parent_id=parent_id, labels=labels, success=False, error=err, model=pin
            ),
        )
        if response.status_code == 202:
            self._record_deferred_chat(
                tag=tag, parent_id=parent_id, labels=labels, success=True, model=pin
            )
            return {"status": "pending"}
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError("Deferred chat get returned non-JSON response") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Deferred chat get returned unexpected payload")
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else None
        out = dict(payload)
        out["status"] = "complete"
        self._record_deferred_chat(
            tag=tag,
            parent_id=parent_id,
            labels=labels,
            success=True,
            usage=usage,
            model=str(payload.get("model") or pin),
        )
        return out

    async def transcribe(
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
        tag = self._require_purpose_if_metered(purpose)
        if not file_bytes:
            raise RuntimeError("Audio file is empty")
        data = {"format": "true", "language": language}
        files = {
            "file": (filename, file_bytes, content_type or "application/octet-stream"),
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}

        def _fail(err: str) -> None:
            self._record(
                purpose=tag,
                usage=None,
                parent_id=parent_id,
                labels=labels,
                success=False,
                thought_level=None,
                error=err,
                modality="stt",
                model="stt",
            )

        response = await self._rest(
            "POST",
            XAI_STT_URL,
            timeout=120.0,
            headers=headers,
            unauthorized="xAI STT unauthorized — check API key",
            fail_prefix="STT",
            record_fail=_fail,
            extra_status={413: ("Audio file too large for STT", False)},
            data=data,
            files=files,
        )
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

    async def synthesize_speech(
        self,
        text: str,
        *,
        voice_id: str = DEFAULT_TTS_VOICE_ID,
        language: str = "en",
        codec: str | None = None,
        sample_rate: int | None = None,
        bit_rate: int | None = None,
        output_format: dict[str, Any] | None = None,
        speed: float | None = None,
        optimize_streaming_latency: int | None = None,
        text_normalization: bool | None = None,
        with_timestamps: bool | None = None,
        replace: dict[str, str] | None = None,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> tuple[bytes, str]:
        tag = self._require_purpose_if_metered(purpose)
        body = tts_rest_body(
            text,
            voice_id=voice_id or DEFAULT_TTS_VOICE_ID,
            language=language or "en",
            codec=codec,
            sample_rate=sample_rate,
            bit_rate=bit_rate,
            output_format=output_format,
            speed=speed,
            optimize_streaming_latency=optimize_streaming_latency,
            text_normalization=text_normalization,
            with_timestamps=with_timestamps,
            replace=replace,
        )
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": tts_rest_accept(with_timestamps=with_timestamps),
        }

        def _fail(err: str) -> None:
            self._record(
                purpose=tag,
                usage=None,
                parent_id=parent_id,
                labels=labels,
                success=False,
                thought_level=None,
                error=err,
                modality="tts",
                model="tts",
            )

        response = await self._rest(
            "POST",
            XAI_TTS_URL,
            timeout=120.0,
            headers=headers,
            unauthorized="xAI TTS unauthorized — check API key",
            fail_prefix="TTS",
            record_fail=_fail,
            json=body,
        )
        audio = response.content
        if not audio:
            raise RuntimeError("TTS returned empty audio")
        content_type = response.headers.get("content-type") or ""
        content_type = content_type.split(";")[0].strip()
        if not content_type:
            content_type = "application/json" if with_timestamps else "audio/mpeg"
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

    async def list_tts_voices(
        self,
        *,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        tag = self._require_purpose_if_metered(purpose)
        key = self._require_tts_api_key()
        headers = {"Authorization": f"Bearer {key}"}
        response = await self._rest(
            "GET",
            XAI_TTS_VOICES_URL,
            timeout=_TTS_VOICES_TIMEOUT,
            headers=headers,
            unauthorized="xAI TTS voices unauthorized — check API key",
            fail_prefix="TTS voices",
            record_fail=lambda err: self._record_tts_voices(
                tag=tag, parent_id=parent_id, labels=labels, success=False, error=err
            ),
        )
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError("TTS voices returned non-JSON response") from exc
        voices = payload.get("voices") if isinstance(payload, dict) else None
        if not isinstance(voices, list) or not voices:
            raise RuntimeError("TTS voices response missing voices list")
        self._record_tts_voices(tag=tag, parent_id=parent_id, labels=labels, success=True)
        return voices

    async def get_tts_voice(
        self,
        voice_id: str,
        *,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        tag = self._require_purpose_if_metered(purpose)
        url = _tts_voice_resource_url(voice_id)
        key = self._require_tts_api_key()
        headers = {"Authorization": f"Bearer {key}"}
        response = await self._rest(
            "GET",
            url,
            timeout=_TTS_VOICES_TIMEOUT,
            headers=headers,
            unauthorized="xAI TTS voices unauthorized — check API key",
            fail_prefix="TTS voices",
            record_fail=lambda err: self._record_tts_voices(
                tag=tag, parent_id=parent_id, labels=labels, success=False, error=err
            ),
        )
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError("TTS voice returned non-JSON response") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("TTS voice returned unexpected payload")
        self._record_tts_voices(tag=tag, parent_id=parent_id, labels=labels, success=True)
        return payload

    async def upload_file(
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
        tag = self._require_purpose_if_metered(purpose)
        name = (filename or "").strip()
        if not name:
            raise RuntimeError("Filename is empty")
        if not data:
            raise RuntimeError("File data is empty")
        if len(data) > XAI_FILE_MAX_BYTES:
            raise RuntimeError(f"File exceeds {XAI_FILE_MAX_BYTES} byte Files API limit")
        if expires_after is not None and not (
            _FILES_EXPIRES_AFTER_MIN <= expires_after <= _FILES_EXPIRES_AFTER_MAX
        ):
            raise RuntimeError("expires_after must be between 3600 and 2592000 seconds")
        form: dict[str, str] = {}
        if expires_after is not None:
            form["expires_after"] = str(expires_after)
        form["purpose"] = (file_purpose or "").strip() or DEFAULT_FILE_PURPOSE
        files = {"file": (name, data, content_type or "application/octet-stream")}
        headers = {"Authorization": f"Bearer {self.api_key}"}
        response = await self._rest(
            "POST",
            XAI_FILES_URL,
            timeout=_FILES_TIMEOUT,
            headers=headers,
            unauthorized="xAI Files unauthorized — check API key",
            fail_prefix="Files",
            record_fail=lambda err: self._record_files(
                tag=tag, parent_id=parent_id, labels=labels, success=False, error=err
            ),
            extra_status={413: ("File too large for Files API", True)},
            data=form,
            files=files,
        )
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError("Files upload returned non-JSON response") from exc
        out = _parse_file_metadata(payload)
        self._record_files(tag=tag, parent_id=parent_id, labels=labels, success=True)
        return out

    async def get_file(
        self,
        file_id: str,
        *,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        tag = self._require_purpose_if_metered(purpose)
        url = _file_resource_url(file_id)
        headers = {"Authorization": f"Bearer {self.api_key}"}
        response = await self._rest(
            "GET",
            url,
            timeout=_FILES_TIMEOUT,
            headers=headers,
            unauthorized="xAI Files unauthorized — check API key",
            fail_prefix="Files",
            record_fail=lambda err: self._record_files(
                tag=tag, parent_id=parent_id, labels=labels, success=False, error=err
            ),
        )
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError("Files get returned non-JSON response") from exc
        out = _parse_file_metadata(payload)
        self._record_files(tag=tag, parent_id=parent_id, labels=labels, success=True)
        return out

    async def delete_file(
        self,
        file_id: str,
        *,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        tag = self._require_purpose_if_metered(purpose)
        url = _file_resource_url(file_id)
        headers = {"Authorization": f"Bearer {self.api_key}"}
        response = await self._rest(
            "DELETE",
            url,
            timeout=_FILES_TIMEOUT,
            headers=headers,
            unauthorized="xAI Files unauthorized — check API key",
            fail_prefix="Files",
            record_fail=lambda err: self._record_files(
                tag=tag, parent_id=parent_id, labels=labels, success=False, error=err
            ),
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
        self._record_files(tag=tag, parent_id=parent_id, labels=labels, success=True)
        return out

    async def embed(
        self,
        texts: str | list[str],
        *,
        model: str,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
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
        response = await self._rest(
            "POST",
            XAI_EMBEDDINGS_URL,
            timeout=_EMBED_TIMEOUT,
            headers=headers,
            unauthorized="xAI embeddings unauthorized — check API key",
            fail_prefix="Embeddings",
            record_fail=lambda err: self._record_embed(
                tag=tag, model=pin, parent_id=parent_id, labels=labels, success=False, error=err
            ),
            json=body,
        )
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

    async def tokenize(
        self,
        text: str,
        *,
        model: str | None = None,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
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
        response = await self._rest(
            "POST",
            XAI_TOKENIZE_URL,
            timeout=_TOKENIZE_TIMEOUT,
            headers=headers,
            unauthorized="xAI tokenize unauthorized — check API key",
            fail_prefix="Tokenize",
            record_fail=lambda err: self._record_tokenize(
                tag=tag, model=pin, parent_id=parent_id, labels=labels, success=False, error=err
            ),
            json=body,
        )
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

    async def create_response(
        self,
        input: str | list[Any],
        *,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        service_tier: str | None = None,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        tag = self._require_purpose_if_metered(purpose)
        pin = (model or "").strip() or (self.model or "").strip()
        if not pin:
            raise RuntimeError("model is required for create_response")
        payload_input = _normalize_response_input(input)
        body: dict[str, Any] = {"model": pin, "input": payload_input}
        normalized_tools = _normalize_response_tools(tools)
        if normalized_tools is not None:
            body["tools"] = normalized_tools
        tier = _normalize_service_tier(service_tier)
        if tier is not None:
            body["service_tier"] = tier
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        response = await self._rest(
            "POST",
            XAI_RESPONSES_URL,
            timeout=_RESPONSES_TIMEOUT,
            headers=headers,
            unauthorized="xAI responses unauthorized — check API key",
            fail_prefix="Responses",
            record_fail=lambda err: self._record_responses(
                tag=tag, model=pin, parent_id=parent_id, labels=labels, success=False, error=err
            ),
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

    async def get_response(
        self,
        response_id: str,
        *,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        tag = self._require_purpose_if_metered(purpose)
        url = _response_resource_url(response_id)
        pin = (self.model or "").strip() or "responses"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        response = await self._rest(
            "GET",
            url,
            timeout=_RESPONSES_TIMEOUT,
            headers=headers,
            unauthorized="xAI responses unauthorized — check API key",
            fail_prefix="Responses",
            record_fail=lambda err: self._record_responses(
                tag=tag, model=pin, parent_id=parent_id, labels=labels, success=False, error=err
            ),
        )
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError("Responses get returned non-JSON response") from exc
        out = _parse_response_payload(payload)
        self._record_responses(
            tag=tag,
            model=str(out.get("model") or pin),
            parent_id=parent_id,
            labels=labels,
            success=True,
        )
        return out

    async def _batch_rpc(
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
            return await call_batch_rpc_async(
                operation,
                sdk_client=self._client,
                **kwargs,
            )
        except Exception as exc:
            self._record_batch(
                tag=tag, parent_id=parent_id, labels=labels, success=False, error=_error_class(exc)
            )
            logger.exception("xAI batch %s failed", operation)
            raise RuntimeError(f"{failed}: {exc}") from exc

    async def create_batch(
        self,
        name: str,
        *,
        input_file_id: str | None = None,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        tag = self._require_purpose_if_metered(purpose)
        cleaned = (name or "").strip()
        if not cleaned:
            raise RuntimeError("Batch name is empty")
        file_id = (input_file_id or "").strip() or None
        raw = await self._batch_rpc(
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
                tag=tag, parent_id=parent_id, labels=labels, success=False, error=_error_class(exc)
            )
            raise RuntimeError(f"Batch create failed: {exc}") from exc
        self._record_batch(tag=tag, parent_id=parent_id, labels=labels, success=True)
        return out

    async def add_batch_requests(
        self,
        batch_id: str,
        requests: list[dict[str, Any]],
        *,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        tag = self._require_purpose_if_metered(purpose)
        bid = (batch_id or "").strip()
        if not bid:
            raise RuntimeError("Batch id is empty")
        normalized = normalize_batch_requests(requests, default_model=self.model)
        raw = await self._batch_rpc(
            "add",
            tag=tag,
            parent_id=parent_id,
            labels=labels,
            failed="Batch add failed",
            batch_id=bid,
            requests=normalized,
        )
        if raw is None:
            out: dict[str, Any] = {"id": bid}
        elif isinstance(raw, dict):
            out = dict(raw)
            out.setdefault("id", bid)
        else:
            out = {"id": bid}
        self._record_batch(tag=tag, parent_id=parent_id, labels=labels, success=True)
        return out

    async def get_batch(
        self,
        batch_id: str,
        *,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        tag = self._require_purpose_if_metered(purpose)
        bid = (batch_id or "").strip()
        if not bid:
            raise RuntimeError("Batch id is empty")
        raw = await self._batch_rpc(
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
                tag=tag, parent_id=parent_id, labels=labels, success=False, error=_error_class(exc)
            )
            raise RuntimeError(f"Batch get failed: {exc}") from exc
        self._record_batch(tag=tag, parent_id=parent_id, labels=labels, success=True)
        return out

    async def cancel_batch(
        self,
        batch_id: str,
        *,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        tag = self._require_purpose_if_metered(purpose)
        bid = (batch_id or "").strip()
        if not bid:
            raise RuntimeError("Batch id is empty")
        raw = await self._batch_rpc(
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
                tag=tag, parent_id=parent_id, labels=labels, success=False, error=_error_class(exc)
            )
            raise RuntimeError(f"Batch cancel failed: {exc}") from exc
        self._record_batch(tag=tag, parent_id=parent_id, labels=labels, success=True)
        return out

    async def list_batches(
        self,
        *,
        limit: int | None = None,
        pagination_token: str | None = None,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        tag = self._require_purpose_if_metered(purpose)
        raw = await self._batch_rpc(
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
                tag=tag, parent_id=parent_id, labels=labels, success=False, error=_error_class(exc)
            )
            raise RuntimeError(f"Batch list failed: {exc}") from exc
        self._record_batch(tag=tag, parent_id=parent_id, labels=labels, success=True)
        return out

    async def list_batch_results(
        self,
        batch_id: str,
        *,
        limit: int | None = None,
        pagination_token: str | None = None,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        tag = self._require_purpose_if_metered(purpose)
        bid = (batch_id or "").strip()
        if not bid:
            raise RuntimeError("Batch id is empty")
        raw = await self._batch_rpc(
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
                tag=tag, parent_id=parent_id, labels=labels, success=False, error=_error_class(exc)
            )
            raise RuntimeError(f"Batch list results failed: {exc}") from exc
        self._record_batch(tag=tag, parent_id=parent_id, labels=labels, success=True)
        return out

    async def _collections_rpc(
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
            return await call_collections_rpc_async(
                operation,
                sdk_client=self._client,
                **kwargs,
            )
        except Exception as exc:
            self._record_collections(
                tag=tag, parent_id=parent_id, labels=labels, success=False, error=_error_class(exc)
            )
            logger.exception("xAI collections %s failed", operation)
            raise RuntimeError(f"{failed}: {exc}") from exc

    async def create_collection(
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
        tag = self._require_purpose_if_metered(purpose)
        cleaned = (name or "").strip()
        if not cleaned:
            raise RuntimeError("Collection name is empty")
        pin = (model_name or "").strip() or None
        desc = (description or "").strip() or None
        raw = await self._collections_rpc(
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
                tag=tag, parent_id=parent_id, labels=labels, success=False, error=_error_class(exc)
            )
            raise RuntimeError(f"Collection create failed: {exc}") from exc
        self._record_collections(tag=tag, parent_id=parent_id, labels=labels, success=True)
        return out

    async def get_collection(
        self,
        collection_id: str,
        *,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        tag = self._require_purpose_if_metered(purpose)
        cid = (collection_id or "").strip()
        if not cid:
            raise RuntimeError("Collection id is empty")
        raw = await self._collections_rpc(
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
                tag=tag, parent_id=parent_id, labels=labels, success=False, error=_error_class(exc)
            )
            raise RuntimeError(f"Collection get failed: {exc}") from exc
        self._record_collections(tag=tag, parent_id=parent_id, labels=labels, success=True)
        return out

    async def list_collections(
        self,
        *,
        limit: int | None = None,
        pagination_token: str | None = None,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        tag = self._require_purpose_if_metered(purpose)
        raw = await self._collections_rpc(
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
                tag=tag, parent_id=parent_id, labels=labels, success=False, error=_error_class(exc)
            )
            raise RuntimeError(f"Collection list failed: {exc}") from exc
        self._record_collections(tag=tag, parent_id=parent_id, labels=labels, success=True)
        return out

    async def delete_collection(
        self,
        collection_id: str,
        *,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        tag = self._require_purpose_if_metered(purpose)
        cid = (collection_id or "").strip()
        if not cid:
            raise RuntimeError("Collection id is empty")
        raw = await self._collections_rpc(
            "delete",
            tag=tag,
            parent_id=parent_id,
            labels=labels,
            failed="Collection delete failed",
            collection_id=cid,
        )
        if isinstance(raw, dict):
            out = dict(raw)
            out.setdefault("id", cid)
            out.setdefault("deleted", True)
        else:
            out = {"id": cid, "deleted": True}
        self._record_collections(tag=tag, parent_id=parent_id, labels=labels, success=True)
        return out

    async def upload_document(
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
        tag = self._require_purpose_if_metered(purpose)
        cid = (collection_id or "").strip()
        if not cid:
            raise RuntimeError("Collection id is empty")
        filename = (name or "").strip()
        if not filename:
            raise RuntimeError("Document name is empty")
        if not data:
            raise RuntimeError("Document data is empty")
        raw = await self._collections_rpc(
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
                tag=tag, parent_id=parent_id, labels=labels, success=False, error=_error_class(exc)
            )
            raise RuntimeError(f"Document upload failed: {exc}") from exc
        self._record_collections(tag=tag, parent_id=parent_id, labels=labels, success=True)
        return out

    async def search_collections(
        self,
        query: str,
        collection_ids: str | list[str] | tuple[str, ...],
        *,
        limit: int | None = None,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        tag = self._require_purpose_if_metered(purpose)
        cleaned = (query or "").strip()
        if not cleaned:
            raise RuntimeError("Search query is empty")
        ids = normalize_collection_ids(collection_ids)
        raw = await self._collections_rpc(
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
                tag=tag, parent_id=parent_id, labels=labels, success=False, error=_error_class(exc)
            )
            raise RuntimeError(f"Collection search failed: {exc}") from exc
        self._record_collections(tag=tag, parent_id=parent_id, labels=labels, success=True)
        return out

    async def _submit_imagine(
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

        def _fail(err: str) -> None:
            self._record(
                purpose=tag,
                usage=None,
                parent_id=parent_id,
                labels=labels,
                success=False,
                thought_level=None,
                error=err,
                modality="imagine",
                model=image_model,
            )

        response = await self._rest(
            "POST",
            endpoint,
            timeout=180.0,
            headers=headers,
            unauthorized="xAI Imagine unauthorized — check API key",
            fail_prefix=http_failed.replace(" failed", "") if http_failed.endswith(" failed") else "Imagine",
            record_fail=_fail,
            json=body,
        )
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

    async def generate_image(
        self,
        prompt: str,
        *,
        model: str | None = None,
        aspect_ratio: str | None = None,
        n: int = 1,
        resolution: str | None = None,
        quality: str | None = None,
        response_format: str | None = None,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
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
        body.update(
            imagine_generate_knobs(
                image_model,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                quality=quality,
                response_format=response_format,
            )
        )
        return await self._submit_imagine(
            XAI_IMAGES_URL,
            body,
            image_model=image_model,
            tag=tag,
            parent_id=parent_id,
            labels=labels,
            request_failed="Image generation request failed",
            http_failed="Image generation failed",
        )

    async def edit_image(
        self,
        prompt: str,
        image: str | dict[str, Any] | None = None,
        *,
        image_url: str | None = None,
        image_file_id: str | None = None,
        images: Sequence[Any] | None = None,
        model: str | None = None,
        aspect_ratio: str | None = None,
        n: int = 1,
        response_format: str | None = None,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
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
        body.update(
            _imagine_edit_source_fields(
                image, url=image_url, file_id=image_file_id, images=images
            )
        )
        aspect = contract_imagine_aspect_ratio(aspect_ratio)
        if aspect:
            body["aspect_ratio"] = aspect
        if response_format:
            body["response_format"] = response_format
        return await self._submit_imagine(
            XAI_IMAGE_EDITS_URL,
            body,
            image_model=image_model,
            tag=tag,
            parent_id=parent_id,
            labels=labels,
            request_failed="Image edit request failed",
            http_failed="Image edit failed",
        )

    async def generate_video(
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
        res = _contract_video_resolution(resolution, video_model, is_r2v=is_r2v)
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
        return await self._start_and_maybe_wait_video(
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

    async def extend_video(
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
        return await self._start_and_maybe_wait_video(
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

    async def poll_video(self, request_id: str) -> dict[str, Any]:
        rid = (request_id or "").strip()
        if not rid:
            raise RuntimeError("Video request_id is empty")
        payload = await self._get_video_status(rid)
        return _normalize_video_payload(payload, request_id=rid)

    async def download_video(self, url: str) -> bytes:
        cleaned = (url or "").strip()
        if not cleaned:
            raise RuntimeError("Video URL is empty")
        try:
            response = await self._http_request(
                "GET", cleaned, timeout=_VIDEO_DOWNLOAD_TIMEOUT, follow_redirects=True
            )
        except httpx.HTTPError as exc:
            logger.exception("xAI video download failed")
            raise RuntimeError(f"Video download failed: {exc}") from exc
        if response.status_code == 401:
            raise RuntimeError("xAI video download unauthorized — check API key")
        if response.status_code >= 400:
            detail = response.text[:500] if response.text else response.reason_phrase
            raise RuntimeError(f"Video download failed ({response.status_code}): {detail}")
        if not response.content:
            raise RuntimeError("Video download returned empty body")
        return response.content

    async def open_realtime_session(
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
    ) -> AsyncRealtimeSession:
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
            ws = await connect_realtime_websocket_async(
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
        rt = AsyncRealtimeSession(
            ws,
            model=voice_model,
            purpose=tag,
            parent_id=parent_id,
            labels=labels,
            record=self._record,
            error_class=_error_class,
        )
        await rt.update_session(session_body)
        return rt

    async def create_realtime_client_secret(
        self,
        *,
        expires_after: int = 300,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        tag = self._require_purpose_if_metered(purpose)
        key = self._require_realtime_api_key()
        seconds = _normalize_realtime_client_secret_expires_after(expires_after)
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {"expires_after": {"seconds": seconds}}
        response = await self._rest(
            "POST",
            XAI_REALTIME_CLIENT_SECRETS_URL,
            timeout=_REALTIME_CLIENT_SECRETS_TIMEOUT,
            headers=headers,
            unauthorized="xAI realtime client secret unauthorized — check API key",
            fail_prefix="Realtime client secret",
            record_fail=lambda err: self._record_realtime_client_secret(
                tag=tag, parent_id=parent_id, labels=labels, success=False, error=err
            ),
            json=body,
        )
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError("Realtime client secret returned non-JSON response") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Realtime client secret returned non-object JSON")
        self._record_realtime_client_secret(
            tag=tag, parent_id=parent_id, labels=labels, success=True
        )
        return payload

    async def open_stt_session(
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
    ) -> AsyncSttSession:
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
            ws = await connect_stt_websocket_async(
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
        session = AsyncSttSession(
            ws,
            purpose=tag,
            parent_id=parent_id,
            labels=labels,
            record=self._record,
            error_class=_error_class,
            model="stt",
        )
        try:
            await session.wait_ready(timeout=_REALTIME_OPEN_TIMEOUT)
        except Exception:
            await session.close(success=False)
            raise
        return session

    async def open_tts_session(
        self,
        *,
        voice: str = DEFAULT_TTS_VOICE_ID,
        language: str = DEFAULT_TTS_WS_LANGUAGE,
        codec: str = DEFAULT_TTS_CODEC,
        sample_rate: int | None = None,
        bit_rate: int | None = None,
        speed: float | None = None,
        optimize_streaming_latency: int | None = None,
        text_normalization: bool | None = None,
        with_timestamps: bool | None = None,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> AsyncTtsSession:
        tag = self._require_purpose_if_metered(purpose)
        key = self._require_tts_api_key()
        url = tts_session_url(
            base=XAI_TTS_WS_URL,
            voice=voice,
            language=language,
            codec=codec,
            sample_rate=sample_rate,
            bit_rate=bit_rate,
            speed=speed,
            optimize_streaming_latency=optimize_streaming_latency,
            text_normalization=text_normalization,
            with_timestamps=with_timestamps,
        )
        headers = {"Authorization": f"Bearer {key}"}
        try:
            ws = await connect_tts_websocket_async(
                url,
                additional_headers=headers,
                open_timeout=_REALTIME_OPEN_TIMEOUT,
                close_timeout=_REALTIME_CLOSE_TIMEOUT,
            )
        except Exception as exc:
            if _is_unauthorized_status(exc):
                raise RuntimeError("xAI TTS unauthorized — check API key") from exc
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
                apply_price_table=False,
            )
            logger.exception("xAI TTS stream connect failed")
            raise RuntimeError(f"TTS session connect failed: {exc}") from exc
        return AsyncTtsSession(
            ws,
            purpose=tag,
            parent_id=parent_id,
            labels=labels,
            record=self._record,
            error_class=_error_class,
            model="tts",
        )

    async def _start_and_maybe_wait_video(
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
        response = await self._rest(
            "POST",
            url,
            timeout=_VIDEO_START_TIMEOUT,
            headers=headers,
            unauthorized=f"xAI {action.lower()} unauthorized — check API key",
            fail_prefix=action,
            record_fail=lambda err: self._record_video_failed(
                tag=tag, parent_id=parent_id, labels=labels, error=err, video_model=video_model
            ),
            json=body,
        )
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
            None, requested_duration=requested_duration, resolution=resolution
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
        return await self._wait_for_video(
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

    async def _wait_for_video(
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
        deadline = asyncio.get_running_loop().time() + max(0.0, float(timeout))
        poll_interval = max(0.0, float(interval))
        while True:
            try:
                payload = await self._get_video_status(request_id)
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
                    payload, requested_duration=requested_duration, resolution=resolution
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
                        payload, requested_duration=requested_duration, resolution=resolution
                    ),
                )
                raise RuntimeError(f"{action} {status}: {message}")
            now = asyncio.get_running_loop().time()
            if now >= deadline:
                self._record_video_failed(
                    tag=tag,
                    parent_id=parent_id,
                    labels=labels,
                    error="video_timeout",
                    video_model=video_model,
                )
                raise RuntimeError(f"{action} timed out waiting for request_id={request_id}")
            remaining = deadline - now
            sleep_for = poll_interval if poll_interval > 0 else 0.0
            if sleep_for > remaining:
                sleep_for = max(0.0, remaining)
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)

    async def _get_video_status(self, request_id: str) -> dict[str, Any]:
        url = XAI_VIDEO_STATUS_URL.format(request_id=request_id)
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            response = await self._http_request(
                "GET", url, timeout=_VIDEO_POLL_TIMEOUT, headers=headers
            )
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
