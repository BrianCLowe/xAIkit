"""xAI realtime voice (speech-to-speech) WebSocket helpers.

Wraps the documented Voice / Realtime protocol. ``xai_sdk`` does not model this
surface; tests inject a fake socket by monkeypatching
:func:`connect_realtime_websocket`.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

logger = logging.getLogger(__name__)

XAI_REALTIME_URL = "wss://api.x.ai/v1/realtime"
DEFAULT_VOICE_MODEL = "grok-voice-latest"
DEFAULT_REALTIME_VOICE = "eve"

_AUDIO_DELTA_TYPES = frozenset(
    {"response.output_audio.delta", "response.audio.delta"}
)


def realtime_session_url(
    model: str,
    *,
    base: str = XAI_REALTIME_URL,
) -> str:
    """``wss://api.x.ai/v1/realtime?model=…`` (keeps any existing query)."""
    mid = (model or "").strip() or DEFAULT_VOICE_MODEL
    parts = urlsplit(base)
    query = dict(p.split("=", 1) if "=" in p else (p, "") for p in parts.query.split("&") if p)
    query["model"] = mid
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


def connect_realtime_websocket(uri: str, **kwargs: Any) -> Any:
    """Open a sync WebSocket. Tests monkeypatch this (like ``httpx.post``)."""
    from websockets.sync.client import connect

    return connect(uri, **kwargs)


def decode_realtime_audio(event: dict[str, Any]) -> bytes | None:
    """Decode base64 PCM from an output-audio delta event, else ``None``."""
    if not isinstance(event, dict):
        return None
    if event.get("type") not in _AUDIO_DELTA_TYPES:
        return None
    raw = event.get("delta")
    if raw is None:
        raw = event.get("audio")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return base64.b64decode(raw)
    except Exception:
        return None


def _b64_audio(audio: bytes | str) -> str:
    if isinstance(audio, str):
        cleaned = audio.strip()
        if not cleaned:
            raise RuntimeError("Realtime audio is empty")
        return cleaned
    if not audio:
        raise RuntimeError("Realtime audio is empty")
    return base64.b64encode(audio).decode("ascii")


class RealtimeSession:
    """One duplex realtime-voice connection (sync, context-manager)."""

    def __init__(
        self,
        ws: Any,
        *,
        model: str,
        purpose: str | None,
        parent_id: str | None,
        labels: dict[str, str] | None,
        record: Callable[..., None],
        error_class: Callable[[BaseException], str],
    ) -> None:
        self._ws = ws
        self.model = model
        self._purpose = purpose
        self._parent_id = parent_id
        self._labels = labels
        self._record = record
        self._error_class = error_class
        self._t0 = time.monotonic()
        self._closed = False
        self._metered = False

    def __enter__(self) -> RealtimeSession:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        ok = exc_type is None
        err = self._error_class(exc) if exc is not None else None
        try:
            self.close(success=ok, error=err)
        except Exception:
            if ok:
                raise
            logger.exception("Realtime session close failed after error")
        return None

    def send_event(self, event: dict[str, Any]) -> None:
        """Send a raw JSON client event."""
        if not isinstance(event, dict) or not event:
            raise RuntimeError("Realtime event is empty")
        self._send_json(event)

    def update_session(self, session: dict[str, Any]) -> None:
        """Send ``session.update`` with the given session object."""
        if not isinstance(session, dict):
            raise RuntimeError("Realtime session update is empty")
        self._send_json({"type": "session.update", "session": session})

    def send_audio(self, audio: bytes | str, *, commit: bool = False) -> None:
        """Append inbound audio (``input_audio_buffer.append``).

        *audio* is raw codec bytes (base64-encoded on the wire) or an already
        base64 string. With server VAD, omit *commit*. Manual turn detection
        can pass ``commit=True`` or call :meth:`commit_audio`.
        """
        payload = {
            "type": "input_audio_buffer.append",
            "audio": _b64_audio(audio),
        }
        self._send_json(payload)
        if commit:
            self.commit_audio()

    def commit_audio(self) -> None:
        """Commit the input buffer (manual turn detection)."""
        self._send_json({"type": "input_audio_buffer.commit"})

    def clear_audio(self) -> None:
        """Discard uncommitted input audio."""
        self._send_json({"type": "input_audio_buffer.clear"})

    def send_text(self, text: str, *, create_response: bool = True) -> None:
        """Send a user text item, then optionally ``response.create``."""
        cleaned = (text or "").strip()
        if not cleaned:
            raise RuntimeError("Realtime text is empty")
        self._send_json(
            {
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": cleaned}],
                },
            }
        )
        if create_response:
            self.create_response()

    def create_response(self) -> None:
        """Ask the server to produce an assistant response."""
        self._send_json({"type": "response.create"})

    def cancel_response(self) -> None:
        """Cancel an in-progress response (manual / non-VAD)."""
        self._send_json({"type": "response.cancel"})

    def recv(self, *, timeout: float | None = None) -> dict[str, Any] | bytes:
        """Receive the next server event (JSON dict) or binary audio frame."""
        try:
            if timeout is None:
                message = self._ws.recv()
            else:
                message = self._ws.recv(timeout=timeout)
        except Exception as exc:
            self._fail(exc, "Realtime recv failed")
        if isinstance(message, bytes):
            return message
        if isinstance(message, dict):
            return message
        try:
            payload = json.loads(message)
        except (TypeError, json.JSONDecodeError) as exc:
            self._fail(exc, "Realtime recv returned non-JSON")
        if not isinstance(payload, dict):
            raise RuntimeError("Realtime recv returned unexpected payload")
        return payload

    def events(self) -> Iterator[dict[str, Any] | bytes]:
        """Yield server events until the socket closes."""
        while True:
            try:
                yield self.recv()
            except RuntimeError as exc:
                cause = exc.__cause__
                name = type(cause).__name__ if cause is not None else type(exc).__name__
                if "Closed" in name or "closed" in str(exc).lower():
                    return
                raise

    def close(
        self,
        *,
        success: bool = True,
        error: str | None = None,
    ) -> None:
        """Close the socket and record usage once (success or failure)."""
        if self._closed:
            return
        self._closed = True
        duration = max(0.0, time.monotonic() - self._t0)
        original_success = success
        close_exc: BaseException | None = None
        try:
            closer = getattr(self._ws, "close", None)
            if callable(closer):
                closer()
        except Exception as exc:
            close_exc = exc
            logger.exception("Realtime websocket close failed")
            if success:
                success = False
                error = error or self._error_class(exc)
        self._finish_meter(success=success, error=error, duration=duration)
        if close_exc is not None and original_success:
            raise RuntimeError(f"Realtime session close failed: {close_exc}") from close_exc

    def _send_json(self, event: dict[str, Any]) -> None:
        try:
            self._ws.send(json.dumps(event))
        except Exception as exc:
            self._fail(exc, "Realtime send failed")

    def _fail(self, exc: BaseException, prefix: str) -> None:
        err = self._error_class(exc)
        duration = max(0.0, time.monotonic() - self._t0)
        self._finish_meter(success=False, error=err, duration=duration)
        if not self._closed:
            self._closed = True
            try:
                closer = getattr(self._ws, "close", None)
                if callable(closer):
                    closer()
            except Exception:
                logger.exception("Realtime websocket close failed after send/recv error")
        raise RuntimeError(f"{prefix}: {exc}") from exc

    def _finish_meter(
        self,
        *,
        success: bool,
        error: str | None,
        duration: float,
    ) -> None:
        if self._metered:
            return
        self._metered = True
        self._record(
            purpose=self._purpose,
            usage={"duration": duration},
            parent_id=self._parent_id,
            labels=self._labels,
            success=success,
            thought_level=None,
            error=error,
            modality="realtime",
            model=self.model,
        )
