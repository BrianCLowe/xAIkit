"""xAI streaming speech-to-text WebSocket helpers (unary-transcribe, not STS).

Wraps the documented ``wss://api.x.ai/v1/stt`` protocol. Configuration is URL
query parameters (no setup message). Audio is raw binary frames, not base64.
Tests inject a fake socket by monkeypatching :func:`connect_stt_websocket`.
"""

from __future__ import annotations

import json
import logging
import time
from collections import deque
import asyncio
import inspect
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from typing import Any, NoReturn
from urllib.parse import urlencode, urlsplit, urlunsplit

logger = logging.getLogger(__name__)

XAI_STT_WS_URL = "wss://api.x.ai/v1/stt"
DEFAULT_STT_SAMPLE_RATE = 16000
DEFAULT_STT_ENCODING = "pcm"
STT_ENCODINGS = frozenset({"pcm", "mulaw", "alaw"})

_NORMAL_CLOSE_CODES = frozenset({1000, 1001})


class SttClosed(Exception):
    """Peer closed the WebSocket without a transport error."""


def _is_timeout(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    return type(exc).__name__ in {"TimeoutError", "TimeoutException"}


def _is_normal_close(exc: BaseException) -> bool:
    name = type(exc).__name__
    if name in {"ConnectionClosedOK", "SttClosed"}:
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


def stt_session_url(
    *,
    base: str = XAI_STT_WS_URL,
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
) -> str:
    """``wss://api.x.ai/v1/stt?sample_rate=…&encoding=…`` plus optional knobs."""
    enc = (encoding or DEFAULT_STT_ENCODING).strip().lower()
    if enc not in STT_ENCODINGS:
        raise RuntimeError(
            f"STT encoding must be one of {sorted(STT_ENCODINGS)}, got {encoding!r}"
        )
    try:
        rate = int(sample_rate)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("STT sample_rate must be an integer") from exc
    if rate <= 0:
        raise RuntimeError("STT sample_rate must be positive")

    parts = urlsplit(base)
    pairs: list[tuple[str, str]] = []
    if parts.query:
        for item in parts.query.split("&"):
            if not item:
                continue
            if "=" in item:
                k, v = item.split("=", 1)
            else:
                k, v = item, ""
            if k in {"sample_rate", "encoding"}:
                continue
            pairs.append((k, v))
    pairs.append(("sample_rate", str(rate)))
    pairs.append(("encoding", enc))

    def _add_bool(name: str, value: bool | None) -> None:
        if value is not None:
            pairs.append((name, _qs_bool(bool(value))))

    _add_bool("interim_results", interim_results)
    if endpointing is not None:
        pairs.append(("endpointing", str(int(endpointing))))
    if language is not None:
        cleaned = str(language).strip()
        if cleaned:
            pairs.append(("language", cleaned))
    _add_bool("diarize", diarize)
    _add_bool("filler_words", filler_words)
    _add_bool("multichannel", multichannel)
    if channels is not None:
        pairs.append(("channels", str(int(channels))))
    if keyterm is not None:
        terms: Sequence[str]
        if isinstance(keyterm, str):
            terms = (keyterm,)
        else:
            terms = keyterm
        for term in terms:
            cleaned = str(term).strip()
            if cleaned:
                pairs.append(("keyterm", cleaned))
    if smart_turn is not None:
        pairs.append(("smart_turn", str(float(smart_turn))))
    if smart_turn_timeout is not None:
        pairs.append(("smart_turn_timeout", str(int(smart_turn_timeout))))
    if vad_threshold is not None:
        pairs.append(("vad_threshold", str(float(vad_threshold))))

    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(pairs), parts.fragment)
    )


def connect_stt_websocket(uri: str, **kwargs: Any) -> Any:
    """Open a sync WebSocket. Tests monkeypatch this (like ``httpx.post``)."""
    from websockets.sync.client import connect

    return connect(uri, **kwargs)


async def connect_stt_websocket_async(uri: str, **kwargs: Any) -> Any:
    """Open an async WebSocket. Tests monkeypatch this (like ``httpx.AsyncClient``)."""
    from websockets.asyncio.client import connect

    return await connect(uri, **kwargs)


class SttSession:
    """One streaming-STT connection (sync, context-manager). Not STS."""

    def __init__(
        self,
        ws: Any,
        *,
        purpose: str | None,
        parent_id: str | None,
        labels: dict[str, str] | None,
        record: Callable[..., None],
        error_class: Callable[[BaseException], str],
        model: str = "stt",
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
        self._ready = False
        self._pending: deque[dict[str, Any]] = deque()

    def __enter__(self) -> SttSession:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        closed_ok = exc_type is not None and issubclass(exc_type, SttClosed)
        ok = exc_type is None or closed_ok
        err = None if ok else (self._error_class(exc) if exc is not None else None)
        try:
            self.close(success=ok, error=err)
        except Exception:
            if ok:
                raise
            logger.exception("STT session close failed after error")
        # After audio.done the server closes the socket; that is success.
        return closed_ok

    def wait_ready(self, *, timeout: float = 30.0) -> dict[str, Any]:
        """Block until the server sends ``transcript.created`` (required before audio)."""
        if self._ready:
            for event in self._pending:
                if event.get("type") == "transcript.created":
                    return event
            return {"type": "transcript.created"}
        deadline = time.monotonic() + max(0.0, timeout)
        event: dict[str, Any] | None = None
        while not self._ready:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._fail(
                    TimeoutError("timed out waiting for transcript.created"),
                    "STT session ready timed out",
                )
            try:
                event = self._recv_raw(timeout=remaining)
            except TimeoutError as exc:
                self._fail(exc, "STT session ready timed out")
            except SttClosed as exc:
                self._fail(exc, "STT session closed before transcript.created")
            self._pending.append(event)
        assert event is not None
        return event

    def send_audio(self, audio: bytes) -> None:
        """Send a raw binary audio frame (PCM / µ-law / A-law). Not base64."""
        if not isinstance(audio, (bytes, bytearray, memoryview)):
            raise RuntimeError("STT audio must be bytes")
        payload = bytes(audio)
        if not payload:
            raise RuntimeError("STT audio is empty")
        self.wait_ready()
        try:
            self._ws.send(payload)
        except Exception as exc:
            self._fail(exc, "STT send failed")

    def finalize(self, channel: int | None = None) -> None:
        """Force the current utterance to ``speech_final`` (push-to-talk)."""
        event: dict[str, Any] = {"type": "finalize"}
        if channel is not None:
            event["channel"] = int(channel)
        self._send_json(event)

    def audio_done(self) -> None:
        """Signal end of audio; server replies with ``transcript.done`` then closes."""
        self._send_json({"type": "audio.done"})

    def recv(self, *, timeout: float | None = None) -> dict[str, Any]:
        """Receive the next server JSON event.

        A ``timeout`` expiry raises ``TimeoutError`` without metering or
        closing — the caller may retry. A normal WebSocket close raises
        ``SttClosed`` without recording a failed usage event; call
        :meth:`close` to meter success. Transport errors still fail the session.
        Server ``error`` events raise ``RuntimeError``.
        """
        if self._pending:
            return self._pending.popleft()
        return self._recv_raw(timeout=timeout)

    def events(self) -> Iterator[dict[str, Any]]:
        """Yield server JSON events until the socket closes (normal close is success)."""
        while True:
            try:
                yield self.recv()
            except SttClosed:
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
            logger.exception("STT websocket close failed")
            if success:
                success = False
                error = error or self._error_class(exc)
        self._finish_meter(success=success, error=error, duration=duration)
        if close_exc is not None and original_success:
            raise RuntimeError(f"STT session close failed: {close_exc}") from close_exc

    def _send_json(self, event: dict[str, Any]) -> None:
        self.wait_ready()
        try:
            self._ws.send(json.dumps(event))
        except Exception as exc:
            self._fail(exc, "STT send failed")

    def _recv_raw(self, timeout: float | None = None) -> dict[str, Any]:
        try:
            if timeout is None:
                message = self._ws.recv()
            else:
                message = self._ws.recv(timeout=timeout)
        except TimeoutError:
            raise
        except SttClosed:
            raise
        except Exception as exc:
            if _is_timeout(exc):
                raise TimeoutError(str(exc) or "STT recv timed out") from exc
            if _is_normal_close(exc):
                raise SttClosed(str(exc) or "STT connection closed") from exc
            self._fail(exc, "STT recv failed")
        if isinstance(message, bytes):
            try:
                message = message.decode("utf-8")
            except UnicodeDecodeError as exc:
                self._fail(exc, "STT recv returned non-JSON")
        if isinstance(message, dict):
            payload = message
        else:
            try:
                payload = json.loads(message)
            except (TypeError, json.JSONDecodeError) as exc:
                self._fail(exc, "STT recv returned non-JSON")
        if not isinstance(payload, dict):
            raise RuntimeError("STT recv returned unexpected payload")
        kind = payload.get("type")
        if kind == "error":
            detail = payload.get("message") or payload.get("error") or "unknown error"
            self._fail(RuntimeError(str(detail)), "STT stream error")
        if kind == "transcript.created":
            self._ready = True
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
                logger.exception("STT websocket close failed after send/recv error")
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
            modality="stt",
            model=self.model,
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


class AsyncSttSession:
    """One streaming-STT connection (async, async-context-manager). Not STS."""

    def __init__(
        self,
        ws: Any,
        *,
        purpose: str | None,
        parent_id: str | None,
        labels: dict[str, str] | None,
        record: Callable[..., None],
        error_class: Callable[[BaseException], str],
        model: str = "stt",
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
        self._ready = False
        self._pending: deque[dict[str, Any]] = deque()

    async def __aenter__(self) -> AsyncSttSession:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        closed_ok = exc_type is not None and issubclass(exc_type, SttClosed)
        ok = exc_type is None or closed_ok
        err = None if ok else (self._error_class(exc) if exc is not None else None)
        try:
            await self.close(success=ok, error=err)
        except Exception:
            if ok:
                raise
            logger.exception("STT session close failed after error")
        return closed_ok

    async def wait_ready(self, *, timeout: float = 30.0) -> dict[str, Any]:
        """Wait until the server sends ``transcript.created`` (required before audio)."""
        if self._ready:
            for event in self._pending:
                if event.get("type") == "transcript.created":
                    return event
            return {"type": "transcript.created"}
        deadline = time.monotonic() + max(0.0, timeout)
        event: dict[str, Any] | None = None
        while not self._ready:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                await self._fail(
                    TimeoutError("timed out waiting for transcript.created"),
                    "STT session ready timed out",
                )
            try:
                event = await self._recv_raw(timeout=remaining)
            except TimeoutError as exc:
                await self._fail(exc, "STT session ready timed out")
            except SttClosed as exc:
                await self._fail(exc, "STT session closed before transcript.created")
            self._pending.append(event)
        assert event is not None
        return event

    async def send_audio(self, audio: bytes) -> None:
        """Send a raw binary audio frame (PCM / µ-law / A-law). Not base64."""
        if not isinstance(audio, (bytes, bytearray, memoryview)):
            raise RuntimeError("STT audio must be bytes")
        payload = bytes(audio)
        if not payload:
            raise RuntimeError("STT audio is empty")
        await self.wait_ready()
        try:
            await _await_maybe(self._ws.send(payload))
        except Exception as exc:
            await self._fail(exc, "STT send failed")

    async def finalize(self, channel: int | None = None) -> None:
        """Force the current utterance to ``speech_final`` (push-to-talk)."""
        event: dict[str, Any] = {"type": "finalize"}
        if channel is not None:
            event["channel"] = int(channel)
        await self._send_json(event)

    async def audio_done(self) -> None:
        """Signal end of audio; server replies with ``transcript.done`` then closes."""
        await self._send_json({"type": "audio.done"})

    async def recv(self, *, timeout: float | None = None) -> dict[str, Any]:
        """Receive the next server JSON event."""
        if self._pending:
            return self._pending.popleft()
        return await self._recv_raw(timeout=timeout)

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        """Yield server JSON events until the socket closes (normal close is success)."""
        while True:
            try:
                yield await self.recv()
            except SttClosed:
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
            logger.exception("STT websocket close failed")
            if success:
                success = False
                error = error or self._error_class(exc)
        self._finish_meter(success=success, error=error, duration=duration)
        if close_exc is not None and original_success:
            raise RuntimeError(f"STT session close failed: {close_exc}") from close_exc

    async def _send_json(self, event: dict[str, Any]) -> None:
        await self.wait_ready()
        try:
            await _await_maybe(self._ws.send(json.dumps(event)))
        except Exception as exc:
            await self._fail(exc, "STT send failed")

    async def _recv_raw(self, timeout: float | None = None) -> dict[str, Any]:
        try:
            message = await _ws_recv(self._ws, timeout=timeout)
        except TimeoutError:
            raise
        except SttClosed:
            raise
        except Exception as exc:
            if _is_timeout(exc):
                raise TimeoutError(str(exc) or "STT recv timed out") from exc
            if _is_normal_close(exc):
                raise SttClosed(str(exc) or "STT connection closed") from exc
            await self._fail(exc, "STT recv failed")
        if isinstance(message, bytes):
            try:
                message = message.decode("utf-8")
            except UnicodeDecodeError as exc:
                await self._fail(exc, "STT recv returned non-JSON")
        if isinstance(message, dict):
            payload = message
        else:
            try:
                payload = json.loads(message)
            except (TypeError, json.JSONDecodeError) as exc:
                await self._fail(exc, "STT recv returned non-JSON")
        if not isinstance(payload, dict):
            raise RuntimeError("STT recv returned unexpected payload")
        kind = payload.get("type")
        if kind == "error":
            detail = payload.get("message") or payload.get("error") or "unknown error"
            await self._fail(RuntimeError(str(detail)), "STT stream error")
        if kind == "transcript.created":
            self._ready = True
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
                logger.exception("STT websocket close failed after send/recv error")
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
            modality="stt",
            model=self.model,
        )
