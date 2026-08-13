"""xAI streaming text-to-speech WebSocket helpers (not STS).

Wraps the documented ``wss://api.x.ai/v1/tts`` protocol. Configuration is URL
query parameters. Client frames are JSON ``text.delta`` / ``text.done`` /
``text.clear``; server audio is base64 ``audio.delta``. Tests inject a fake
socket by monkeypatching :func:`connect_tts_websocket`.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from collections.abc import Callable, Iterator, Mapping
from typing import Any, NoReturn
from urllib.parse import urlencode, urlsplit, urlunsplit

logger = logging.getLogger(__name__)

XAI_TTS_WS_URL = "wss://api.x.ai/v1/tts"
DEFAULT_TTS_WS_VOICE = "eve"
DEFAULT_TTS_WS_LANGUAGE = "en"
DEFAULT_TTS_CODEC = "mp3"
TTS_CODECS = frozenset({"mp3", "wav", "pcm", "mulaw", "ulaw", "alaw"})
TTS_SAMPLE_RATES = frozenset({8000, 16000, 22050, 24000, 44100, 48000})
TTS_MAX_DELTA_CHARS = 15000

_NORMAL_CLOSE_CODES = frozenset({1000, 1001})
_AUDIO_DELTA_TYPE = "audio.delta"


class TtsClosed(Exception):
    """Peer closed the WebSocket without a transport error."""


def _is_timeout(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    return type(exc).__name__ in {"TimeoutError", "TimeoutException"}


def _is_normal_close(exc: BaseException) -> bool:
    name = type(exc).__name__
    if name in {"ConnectionClosedOK", "TtsClosed"}:
        return True
    code = getattr(exc, "code", None)
    if code is None:
        rcvd = getattr(exc, "rcvd", None)
        code = getattr(rcvd, "code", None)
    if name in {"ConnectionClosed", "ConnectionClosedOK", "ConnectionClosedError"}:
        return name != "ConnectionClosedError" and (
            code is None or code in _NORMAL_CLOSE_CODES
        )
    return False


def _qs_bool(value: bool) -> str:
    return "true" if value else "false"


def tts_session_url(
    *,
    base: str = XAI_TTS_WS_URL,
    voice: str = DEFAULT_TTS_WS_VOICE,
    language: str = DEFAULT_TTS_WS_LANGUAGE,
    codec: str = DEFAULT_TTS_CODEC,
    sample_rate: int | None = None,
    bit_rate: int | None = None,
    speed: float | None = None,
    optimize_streaming_latency: int | None = None,
    text_normalization: bool | None = None,
    with_timestamps: bool | None = None,
) -> str:
    """``wss://api.x.ai/v1/tts?language=…&voice=…&codec=…`` plus optional knobs."""
    codec_clean = (codec or DEFAULT_TTS_CODEC).strip().lower()
    if codec_clean not in TTS_CODECS:
        raise RuntimeError(
            f"TTS codec must be one of {sorted(TTS_CODECS)}, got {codec!r}"
        )
    voice_clean = (voice or DEFAULT_TTS_WS_VOICE).strip() or DEFAULT_TTS_WS_VOICE
    language_clean = (language or DEFAULT_TTS_WS_LANGUAGE).strip() or DEFAULT_TTS_WS_LANGUAGE

    parts = urlsplit(base)
    pairs: list[tuple[str, str]] = []
    skip = {
        "voice",
        "language",
        "codec",
        "sample_rate",
        "bit_rate",
        "speed",
        "optimize_streaming_latency",
        "text_normalization",
        "with_timestamps",
    }
    if parts.query:
        for item in parts.query.split("&"):
            if not item:
                continue
            if "=" in item:
                k, v = item.split("=", 1)
            else:
                k, v = item, ""
            if k in skip:
                continue
            pairs.append((k, v))
    pairs.append(("language", language_clean))
    pairs.append(("voice", voice_clean))
    pairs.append(("codec", codec_clean))

    if sample_rate is not None:
        try:
            rate = int(sample_rate)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("TTS sample_rate must be an integer") from exc
        if rate not in TTS_SAMPLE_RATES:
            raise RuntimeError(
                f"TTS sample_rate must be one of {sorted(TTS_SAMPLE_RATES)}, got {sample_rate!r}"
            )
        pairs.append(("sample_rate", str(rate)))
    if bit_rate is not None:
        pairs.append(("bit_rate", str(int(bit_rate))))
    if speed is not None:
        pairs.append(("speed", str(float(speed))))
    if optimize_streaming_latency is not None:
        pairs.append(
            ("optimize_streaming_latency", str(int(optimize_streaming_latency)))
        )
    if text_normalization is not None:
        pairs.append(("text_normalization", _qs_bool(bool(text_normalization))))
    if with_timestamps is not None:
        pairs.append(("with_timestamps", _qs_bool(bool(with_timestamps))))

    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(pairs), parts.fragment)
    )


def connect_tts_websocket(uri: str, **kwargs: Any) -> Any:
    """Open a sync WebSocket. Tests monkeypatch this (like ``httpx.post``)."""
    from websockets.sync.client import connect

    return connect(uri, **kwargs)


def decode_tts_audio(event: dict[str, Any]) -> bytes | None:
    """Decode base64 audio from an ``audio.delta`` event, else ``None``."""
    if not isinstance(event, dict):
        return None
    if event.get("type") != _AUDIO_DELTA_TYPE:
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


class TtsSession:
    """One streaming-TTS connection (sync, context-manager). Not STS."""

    def __init__(
        self,
        ws: Any,
        *,
        purpose: str | None,
        parent_id: str | None,
        labels: dict[str, str] | None,
        record: Callable[..., None],
        error_class: Callable[[BaseException], str],
        model: str = "tts",
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

    def __enter__(self) -> TtsSession:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        closed_ok = exc_type is not None and issubclass(exc_type, TtsClosed)
        ok = exc_type is None or closed_ok
        err = None if ok else (self._error_class(exc) if exc is not None else None)
        try:
            self.close(success=ok, error=err)
        except Exception:
            if ok:
                raise
            logger.exception("TTS session close failed after error")
        return closed_ok

    def send_text(self, delta: str) -> None:
        """Send a ``text.delta`` JSON frame. Individual deltas cap at 15,000 chars."""
        if not isinstance(delta, str):
            raise RuntimeError("TTS text must be a string")
        if not delta:
            raise RuntimeError("TTS text is empty")
        if len(delta) > TTS_MAX_DELTA_CHARS:
            raise RuntimeError(
                f"TTS text.delta exceeds {TTS_MAX_DELTA_CHARS} characters"
            )
        self._send_json({"type": "text.delta", "delta": delta})

    def text_done(self) -> None:
        """Signal end of the current utterance (``text.done``)."""
        self._send_json({"type": "text.done"})

    def text_clear(self) -> None:
        """Cancel the current utterance (``text.clear``)."""
        self._send_json({"type": "text.clear"})

    def update_session(self, replace: Mapping[str, str]) -> None:
        """Send ``session.update`` with a pronunciation ``replace`` map."""
        if not isinstance(replace, Mapping) or not replace:
            raise RuntimeError("TTS replace map is empty")
        payload = {str(k): str(v) for k, v in replace.items()}
        self._send_json({"type": "session.update", "replace": payload})

    def recv(self, *, timeout: float | None = None) -> dict[str, Any]:
        """Receive the next server JSON event.

        A ``timeout`` expiry raises ``TimeoutError`` without metering or
        closing — the caller may retry. A normal WebSocket close raises
        ``TtsClosed`` without recording a failed usage event; call
        :meth:`close` to meter success. Transport errors still fail the session.
        Server ``error`` events raise ``RuntimeError``.
        """
        return self._recv_raw(timeout=timeout)

    def events(self) -> Iterator[dict[str, Any]]:
        """Yield server JSON events until the socket closes (normal close is success)."""
        while True:
            try:
                yield self.recv()
            except TtsClosed:
                return

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
            logger.exception("TTS websocket close failed")
            if success:
                success = False
                error = error or self._error_class(exc)
        self._finish_meter(success=success, error=error, duration=duration)
        if close_exc is not None and original_success:
            raise RuntimeError(f"TTS session close failed: {close_exc}") from close_exc

    def _send_json(self, event: dict[str, Any]) -> None:
        try:
            self._ws.send(json.dumps(event))
        except Exception as exc:
            self._fail(exc, "TTS send failed")

    def _recv_raw(self, timeout: float | None = None) -> dict[str, Any]:
        try:
            if timeout is None:
                message = self._ws.recv()
            else:
                message = self._ws.recv(timeout=timeout)
        except TimeoutError:
            raise
        except TtsClosed:
            raise
        except Exception as exc:
            if _is_timeout(exc):
                raise TimeoutError(str(exc) or "TTS recv timed out") from exc
            if _is_normal_close(exc):
                raise TtsClosed(str(exc) or "TTS connection closed") from exc
            self._fail(exc, "TTS recv failed")
        if isinstance(message, bytes):
            try:
                message = message.decode("utf-8")
            except UnicodeDecodeError as exc:
                self._fail(exc, "TTS recv returned non-JSON")
        if isinstance(message, dict):
            payload = message
        else:
            try:
                payload = json.loads(message)
            except (TypeError, json.JSONDecodeError) as exc:
                self._fail(exc, "TTS recv returned non-JSON")
        if not isinstance(payload, dict):
            raise RuntimeError("TTS recv returned unexpected payload")
        kind = payload.get("type")
        if kind == "error":
            detail = payload.get("message") or payload.get("error") or "unknown error"
            self._fail(RuntimeError(str(detail)), "TTS stream error")
        return payload

    def _fail(self, exc: BaseException, prefix: str) -> NoReturn:
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
                logger.exception("TTS websocket close failed after send/recv error")
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
            modality="tts",
            model=self.model,
            apply_price_table=False,
        )
