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
import asyncio
import inspect
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from typing import Any, NoReturn
from urllib.parse import urlencode, urlsplit, urlunsplit

logger = logging.getLogger(__name__)

XAI_TTS_WS_URL = "wss://api.x.ai/v1/tts"
DEFAULT_TTS_WS_VOICE = "eve"
DEFAULT_TTS_WS_LANGUAGE = "en"
DEFAULT_TTS_CODEC = "mp3"
TTS_CODECS = frozenset({"mp3", "wav", "pcm", "mulaw", "ulaw", "alaw"})
TTS_SAMPLE_RATES = frozenset({8000, 16000, 22050, 24000, 44100, 48000})
TTS_BIT_RATES = frozenset({32000, 64000, 96000, 128000, 192000})
TTS_SPEED_MIN = 0.7
TTS_SPEED_MAX = 1.5
TTS_OPTIMIZE_LATENCY = frozenset({0, 1, 2})
TTS_MAX_DELTA_CHARS = 15000
_TTS_REST_ACCEPT_AUDIO = "audio/mpeg, application/octet-stream, */*"
_TTS_REST_ACCEPT_TIMESTAMPS = (
    "application/json, audio/mpeg, application/octet-stream, */*"
)

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


def normalize_tts_codec(
    codec: str | None,
    *,
    default: str | None = None,
) -> str | None:
    """Keep official codecs (incl. ``ulaw`` as the streaming ``mulaw`` alias)."""
    raw = (codec or "").strip().lower()
    if not raw:
        raw = (default or "").strip().lower()
    if not raw:
        return None
    if raw not in TTS_CODECS:
        raise RuntimeError(
            f"TTS codec must be one of {sorted(TTS_CODECS)}, got {codec!r}"
        )
    return raw


def normalize_tts_sample_rate(sample_rate: int | None) -> int | None:
    if sample_rate is None:
        return None
    try:
        rate = int(sample_rate)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("TTS sample_rate must be an integer") from exc
    if rate not in TTS_SAMPLE_RATES:
        raise RuntimeError(
            f"TTS sample_rate must be one of {sorted(TTS_SAMPLE_RATES)}, got {sample_rate!r}"
        )
    return rate


def normalize_tts_bit_rate(
    bit_rate: int | None,
    *,
    codec: str | None = None,
) -> int | None:
    """MP3-only bit rates from the unary TTS docs. Omit when unset."""
    if bit_rate is None:
        return None
    try:
        rate = int(bit_rate)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("TTS bit_rate must be an integer") from exc
    if rate not in TTS_BIT_RATES:
        raise RuntimeError(
            f"TTS bit_rate must be one of {sorted(TTS_BIT_RATES)}, got {bit_rate!r}"
        )
    codec_clean = (codec or "mp3").strip().lower() or "mp3"
    if codec_clean != "mp3":
        raise RuntimeError("TTS bit_rate is only valid for codec 'mp3'")
    return rate


def normalize_tts_speed(speed: float | None) -> float | None:
    if speed is None:
        return None
    try:
        value = float(speed)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("TTS speed must be a number") from exc
    if value < TTS_SPEED_MIN or value > TTS_SPEED_MAX:
        raise RuntimeError(
            f"TTS speed must be between {TTS_SPEED_MIN} and {TTS_SPEED_MAX}, got {speed!r}"
        )
    return value


def normalize_tts_optimize_latency(value: int | None) -> int | None:
    if value is None:
        return None
    try:
        level = int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("TTS optimize_streaming_latency must be an integer") from exc
    if level not in TTS_OPTIMIZE_LATENCY:
        raise RuntimeError(
            f"TTS optimize_streaming_latency must be one of "
            f"{sorted(TTS_OPTIMIZE_LATENCY)}, got {value!r}"
        )
    return level


def normalize_tts_replace(
    replace: Mapping[str, str] | None,
) -> dict[str, str] | None:
    if replace is None:
        return None
    if not isinstance(replace, Mapping):
        raise RuntimeError(
            "TTS replace must be an object map of phrase to spoken substitution"
        )
    out: dict[str, str] = {}
    for key, val in replace.items():
        if not isinstance(key, str) or not isinstance(val, str):
            raise RuntimeError("TTS replace keys and values must be strings")
        phrase = key.strip()
        if not phrase:
            continue
        out[phrase] = val
    return out or None


def _merge_tts_output_format(
    output_format: Mapping[str, Any] | None,
    *,
    codec: str | None,
    sample_rate: int | None,
    bit_rate: int | None,
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    if output_format is not None:
        if not isinstance(output_format, Mapping):
            raise RuntimeError("TTS output_format must be an object")
        if output_format.get("codec") is not None:
            merged["codec"] = output_format["codec"]
        if output_format.get("sample_rate") is not None:
            merged["sample_rate"] = output_format["sample_rate"]
        if output_format.get("bit_rate") is not None:
            merged["bit_rate"] = output_format["bit_rate"]
    if codec is not None:
        merged["codec"] = codec
    if sample_rate is not None:
        merged["sample_rate"] = sample_rate
    if bit_rate is not None:
        merged["bit_rate"] = bit_rate
    return merged


def tts_rest_accept(*, with_timestamps: bool | None = None) -> str:
    """Accept header for unary TTS. Default path stays audio (today's wire)."""
    if with_timestamps:
        return _TTS_REST_ACCEPT_TIMESTAMPS
    return _TTS_REST_ACCEPT_AUDIO


def tts_rest_body(
    text: str,
    *,
    voice_id: str,
    language: str,
    codec: str | None = None,
    sample_rate: int | None = None,
    bit_rate: int | None = None,
    output_format: Mapping[str, Any] | None = None,
    speed: float | None = None,
    optimize_streaming_latency: int | None = None,
    text_normalization: bool | None = None,
    with_timestamps: bool | None = None,
    replace: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Unary TTS JSON body. Unset optional knobs are omitted.

    Flat ``codec`` / ``sample_rate`` / ``bit_rate`` match streaming callers and
    nest as ``output_format`` on the wire. ``output_format=`` is also accepted;
    flat knobs win on conflict.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        raise RuntimeError("TTS text is empty")
    if len(cleaned) > TTS_MAX_DELTA_CHARS:
        raise RuntimeError(f"TTS text exceeds {TTS_MAX_DELTA_CHARS} characters")

    body: dict[str, Any] = {
        "text": cleaned,
        "voice_id": voice_id,
        "language": language,
    }

    fmt = _merge_tts_output_format(
        output_format,
        codec=codec,
        sample_rate=sample_rate,
        bit_rate=bit_rate,
    )
    codec_clean = normalize_tts_codec(fmt.get("codec"))
    rate_clean = normalize_tts_sample_rate(fmt.get("sample_rate"))
    bit_clean = normalize_tts_bit_rate(fmt.get("bit_rate"), codec=codec_clean)
    nested: dict[str, Any] = {}
    if codec_clean is not None:
        nested["codec"] = codec_clean
    if rate_clean is not None:
        nested["sample_rate"] = rate_clean
    if bit_clean is not None:
        nested["bit_rate"] = bit_clean
    if nested:
        body["output_format"] = nested

    speed_clean = normalize_tts_speed(speed)
    if speed_clean is not None:
        body["speed"] = speed_clean
    latency_clean = normalize_tts_optimize_latency(optimize_streaming_latency)
    if latency_clean is not None:
        body["optimize_streaming_latency"] = latency_clean
    if text_normalization is not None:
        body["text_normalization"] = bool(text_normalization)
    if with_timestamps is not None:
        body["with_timestamps"] = bool(with_timestamps)
    replace_clean = normalize_tts_replace(replace)
    if replace_clean is not None:
        body["replace"] = replace_clean
    return body


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
    codec_clean = normalize_tts_codec(codec, default=DEFAULT_TTS_CODEC)
    if codec_clean is None:
        codec_clean = DEFAULT_TTS_CODEC
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

    rate = normalize_tts_sample_rate(sample_rate)
    if rate is not None:
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


async def connect_tts_websocket_async(uri: str, **kwargs: Any) -> Any:
    """Open an async WebSocket. Tests monkeypatch this (like ``httpx.AsyncClient``)."""
    from websockets.asyncio.client import connect

    return await connect(uri, **kwargs)


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


async def _await_maybe(result: Any) -> Any:
    if inspect.isawaitable(result):
        return await result
    return result


async def _ws_recv(ws: Any, *, timeout: float | None) -> Any:
    recv = ws.recv
    used_native_timeout = False
    if timeout is None:
        result = recv()
    else:
        try:
            result = recv(timeout=timeout)
            used_native_timeout = True
        except TypeError:
            result = recv()
    if inspect.isawaitable(result):
        if timeout is not None and not used_native_timeout:
            return await asyncio.wait_for(result, timeout=timeout)
        return await result
    return result


class AsyncTtsSession:
    """One streaming-TTS connection (async, async-context-manager). Not STS."""

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

    async def __aenter__(self) -> AsyncTtsSession:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        closed_ok = exc_type is not None and issubclass(exc_type, TtsClosed)
        ok = exc_type is None or closed_ok
        err = None if ok else (self._error_class(exc) if exc is not None else None)
        try:
            await self.close(success=ok, error=err)
        except Exception:
            if ok:
                raise
            logger.exception("TTS session close failed after error")
        return closed_ok

    async def send_text(self, delta: str) -> None:
        """Send a ``text.delta`` JSON frame. Individual deltas cap at 15,000 chars."""
        if not isinstance(delta, str):
            raise RuntimeError("TTS text must be a string")
        if not delta:
            raise RuntimeError("TTS text is empty")
        if len(delta) > TTS_MAX_DELTA_CHARS:
            raise RuntimeError(
                f"TTS text.delta exceeds {TTS_MAX_DELTA_CHARS} characters"
            )
        await self._send_json({"type": "text.delta", "delta": delta})

    async def text_done(self) -> None:
        """Signal end of the current utterance (``text.done``)."""
        await self._send_json({"type": "text.done"})

    async def text_clear(self) -> None:
        """Cancel the current utterance (``text.clear``)."""
        await self._send_json({"type": "text.clear"})

    async def update_session(self, replace: Mapping[str, str]) -> None:
        """Send ``session.update`` with a pronunciation ``replace`` map."""
        if not isinstance(replace, Mapping) or not replace:
            raise RuntimeError("TTS replace map is empty")
        payload = {str(k): str(v) for k, v in replace.items()}
        await self._send_json({"type": "session.update", "replace": payload})

    async def recv(self, *, timeout: float | None = None) -> dict[str, Any]:
        """Receive the next server JSON event."""
        return await self._recv_raw(timeout=timeout)

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        """Yield server JSON events until the socket closes (normal close is success)."""
        while True:
            try:
                yield await self.recv()
            except TtsClosed:
                return

    async def close(
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
                await _await_maybe(closer())
        except Exception as exc:
            close_exc = exc
            logger.exception("TTS websocket close failed")
            if success:
                success = False
                error = error or self._error_class(exc)
        self._finish_meter(success=success, error=error, duration=duration)
        if close_exc is not None and original_success:
            raise RuntimeError(f"TTS session close failed: {close_exc}") from close_exc

    async def _send_json(self, event: dict[str, Any]) -> None:
        try:
            await _await_maybe(self._ws.send(json.dumps(event)))
        except Exception as exc:
            await self._fail(exc, "TTS send failed")

    async def _recv_raw(self, timeout: float | None = None) -> dict[str, Any]:
        try:
            message = await _ws_recv(self._ws, timeout=timeout)
        except TimeoutError:
            raise
        except TtsClosed:
            raise
        except Exception as exc:
            if _is_timeout(exc):
                raise TimeoutError(str(exc) or "TTS recv timed out") from exc
            if _is_normal_close(exc):
                raise TtsClosed(str(exc) or "TTS connection closed") from exc
            await self._fail(exc, "TTS recv failed")
        if isinstance(message, bytes):
            try:
                message = message.decode("utf-8")
            except UnicodeDecodeError as exc:
                await self._fail(exc, "TTS recv returned non-JSON")
        if isinstance(message, dict):
            payload = message
        else:
            try:
                payload = json.loads(message)
            except (TypeError, json.JSONDecodeError) as exc:
                await self._fail(exc, "TTS recv returned non-JSON")
        if not isinstance(payload, dict):
            raise RuntimeError("TTS recv returned unexpected payload")
        kind = payload.get("type")
        if kind == "error":
            detail = payload.get("message") or payload.get("error") or "unknown error"
            await self._fail(RuntimeError(str(detail)), "TTS stream error")
        return payload

    async def _fail(self, exc: BaseException, prefix: str) -> NoReturn:
        err = self._error_class(exc)
        duration = max(0.0, time.monotonic() - self._t0)
        self._finish_meter(success=False, error=err, duration=duration)
        if not self._closed:
            self._closed = True
            try:
                closer = getattr(self._ws, "close", None)
                if callable(closer):
                    await _await_maybe(closer())
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
