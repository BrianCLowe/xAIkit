"""xAI (Grok) client — typed transport for XaiKit.

Domain schemas stay in consuming apps; this module is transport only.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from typing import Any

import httpx
from xai_sdk import Client

from xaikit.catalog import (
    BOOTSTRAP_MODEL,
    normalize_thought_level,
    resolve_model_selection,
)
from xaikit.credentials import CredentialStore
from xaikit.provider import ChatProvider, SdkChatProvider
from xaikit.retry import RetryPolicy, call_with_retry, default_retry_policy
from xaikit.traces import CompletionTracer
from xaikit.types import CompletionResponse, StreamChunk
from xaikit.usage import UsageMeter

logger = logging.getLogger(__name__)

_JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

XAI_STT_URL = "https://api.x.ai/v1/stt"
XAI_TTS_URL = "https://api.x.ai/v1/tts"
XAI_IMAGES_URL = "https://api.x.ai/v1/images/generations"
DEFAULT_TTS_VOICE_ID = "eve"
DEFAULT_IMAGE_MODEL = "grok-imagine-image-quality"


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
            self._client = Client(api_key=key)
            self._provider = SdkChatProvider(self._client)

        self._usage_meter = usage_meter
        self._completion_tracer = completion_tracer
        self._retry_policy = (
            retry_policy if retry_policy is not None else default_retry_policy()
        )
        self.image_model = (image_model or DEFAULT_IMAGE_MODEL).strip()

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
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int | None = None,
        thought_level: str | None,
        system_prompt: str | None = None,
    ):
        def _call():
            return self._provider.complete(
                messages,
                model=self.model,
                temperature=temperature,
                max_tokens=max_tokens,
                thought_level=thought_level,
                system_prompt=system_prompt,
            )

        return call_with_retry(
            _call,
            policy=self._retry_policy,
            label="xai.complete",
        )

    def _open_stream(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int | None = None,
        thought_level: str | None,
        system_prompt: str | None = None,
    ):
        def _call():
            return self._provider.stream(
                messages,
                model=self.model,
                temperature=temperature,
                max_tokens=max_tokens,
                thought_level=thought_level,
                system_prompt=system_prompt,
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
        messages: list[dict[str, str]],
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
            )
        except Exception:
            logger.exception("Failed to record usage event (purpose=%s)", purpose)

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        system_prompt: str | None = None,
        thought_level: str | None = None,
        effort: str | None = None,
    ) -> CompletionResponse:
        """Non-streaming chat completion."""
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
    ) -> dict[str, Any]:
        """Return a parsed JSON object from a JSON-only model response."""
        tag = self._require_purpose_if_metered(purpose)
        level = self._effective_thought_level(thought_level, effort=effort)
        messages = [{"role": "user", "content": user_prompt}]
        sys = system_prompt or (
            "You return ONLY valid JSON (no markdown fences) matching the requested shape."
        )
        usage: dict[str, Any] | None = None
        try:
            resp = self._complete(
                messages,
                temperature=temperature,
                thought_level=level,
                system_prompt=sys,
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
        messages: list[dict[str, str]],
        *,
        purpose: str | None = None,
        parent_id: str | None = None,
        labels: dict[str, str] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        system_prompt: str | None = None,
        thought_level: str | None = None,
        effort: str | None = None,
    ) -> Iterator[StreamChunk]:
        """Incremental chat completion — yields deltas as the provider streams them.

        Usage is recorded once when the stream completes successfully (or fails).
        Mid-stream provider failures are not retried; only opening the stream is.
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
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "model": image_model,
            "prompt": cleaned,
            "n": max(1, min(int(n or 1), 4)),
        }
        if aspect_ratio:
            body["aspect_ratio"] = aspect_ratio

        try:
            response = httpx.post(
                XAI_IMAGES_URL,
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
            raise RuntimeError(f"Image generation request failed: {exc}") from exc

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
            raise RuntimeError(
                f"Image generation failed ({response.status_code}): {detail}"
            )

        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError("Imagine returned non-JSON response") from exc

        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list) or not data:
            raise RuntimeError("Imagine response missing data")

        first = data[0] if isinstance(data[0], dict) else {}
        url = first.get("url")
        b64 = first.get("b64_json")
        if not url and not b64:
            raise RuntimeError("Imagine response missing url and b64_json")

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
            "url": str(url) if url else None,
            "b64_json": str(b64) if b64 else None,
            "model": image_model,
        }
