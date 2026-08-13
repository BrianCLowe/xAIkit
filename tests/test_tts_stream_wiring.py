"""Contract tests: streaming TTS WebSocket wiring (URL, auth, JSON, metering)."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from xaikit import (
    InMemoryUsageSink,
    MockChatProvider,
    TtsClosed,
    TtsSession,
    UsageMeter,
    XAI_TTS_WS_URL,
    XaiClient,
    decode_tts_audio,
    default_retry_policy,
)
from xaikit.tts_stream import TTS_MAX_DELTA_CHARS


def _client(*, usage_meter: UsageMeter | None = None, **kwargs: Any) -> XaiClient:
    return XaiClient(
        provider=MockChatProvider(),
        model="grok-3-mini",
        api_key="test-key",
        usage_meter=usage_meter,
        retry_policy=default_retry_policy(max_attempts=1),
        **kwargs,
    )


class FakeWebSocket:
    def __init__(
        self,
        incoming: list[str | bytes] | None = None,
        *,
        empty_is_close: bool = False,
    ) -> None:
        self.sent: list[str | bytes] = []
        self.incoming: list[str | bytes] = list(incoming or [])
        self.closed = False
        self.close_calls = 0
        self.empty_is_close = empty_is_close
        self.ops: list[str] = []

    def send(self, message: str | bytes) -> None:
        if self.closed:
            raise TtsClosed("socket closed")
        self.ops.append("send")
        self.sent.append(message)

    def recv(self, timeout: float | None = None) -> str | bytes:
        if self.closed:
            raise TtsClosed("socket closed")
        self.ops.append("recv")
        if not self.incoming:
            if self.empty_is_close:
                raise TtsClosed("socket closed")
            raise TimeoutError("no messages")
        return self.incoming.pop(0)

    def close(self) -> None:
        self.closed = True
        self.close_calls += 1


class _WsCapture:
    def __init__(
        self,
        incoming: list[str | bytes] | None = None,
        *,
        empty_is_close: bool = False,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.ws = FakeWebSocket(incoming, empty_is_close=empty_is_close)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> FakeWebSocket:
        def _connect(uri: str, **kwargs: Any) -> FakeWebSocket:
            self.calls.append({"uri": uri, **kwargs})
            return self.ws

        monkeypatch.setattr("xaikit.client.connect_tts_websocket", _connect)
        return self.ws


def test_open_tts_connects_with_auth_header_query_and_meters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    meter = UsageMeter(sink=sink)
    client = _client(usage_meter=meter)
    recorded: list[dict[str, Any]] = []
    orig = client._record

    def _spy(**kwargs: Any) -> None:
        recorded.append(kwargs)
        orig(**kwargs)

    client._record = _spy  # type: ignore[method-assign]
    cap = _WsCapture()
    ws = cap.install(monkeypatch)

    session = client.open_tts_session(
        voice="ara",
        language="en",
        codec="pcm",
        sample_rate=16000,
        bit_rate=128000,
        speed=1.1,
        optimize_streaming_latency=1,
        text_normalization=True,
        with_timestamps=False,
        purpose="demo.tts.stream",
        parent_id="p1",
        labels={"request_id": "r1"},
    )

    assert isinstance(session, TtsSession)
    assert len(cap.calls) == 1
    call = cap.calls[0]
    parts = urlsplit(call["uri"])
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == XAI_TTS_WS_URL
    query = parse_qs(parts.query)
    assert query["voice"] == ["ara"]
    assert query["language"] == ["en"]
    assert query["codec"] == ["pcm"]
    assert query["sample_rate"] == ["16000"]
    assert query["bit_rate"] == ["128000"]
    assert query["speed"] == ["1.1"]
    assert query["optimize_streaming_latency"] == ["1"]
    assert query["text_normalization"] == ["true"]
    assert query["with_timestamps"] == ["false"]
    assert call["additional_headers"]["Authorization"] == "Bearer test-key"
    assert call["open_timeout"] == 30.0

    session.close()
    ev = list(sink.iter_events())[0]
    assert ev.purpose == "demo.tts.stream"
    assert ev.modality == "tts"
    assert ev.model == "tts"
    assert ev.success is True
    assert ev.parent_id == "p1"
    assert ev.labels["request_id"] == "r1"
    assert ev.estimated_usd is None
    assert recorded[-1]["usage"]["duration"] >= 0.0
    assert recorded[-1]["apply_price_table"] is False
    assert ws.closed is True


def test_open_tts_defaults_omit_optional_query_knobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _WsCapture()
    cap.install(monkeypatch)

    session = client.open_tts_session()
    query = parse_qs(urlsplit(cap.calls[0]["uri"]).query)
    assert query["voice"] == ["eve"]
    assert query["language"] == ["en"]
    assert query["codec"] == ["mp3"]
    assert "sample_rate" not in query
    assert "bit_rate" not in query
    assert "speed" not in query
    assert "optimize_streaming_latency" not in query
    assert "text_normalization" not in query
    assert "with_timestamps" not in query
    session.close()


def test_send_text_done_clear_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _WsCapture()
    ws = cap.install(monkeypatch)

    with client.open_tts_session() as session:
        session.send_text("Hello from turn one.")
        session.text_done()
        session.text_clear()

    assert json.loads(ws.sent[0]) == {
        "type": "text.delta",
        "delta": "Hello from turn one.",
    }
    assert json.loads(ws.sent[1]) == {"type": "text.done"}
    assert json.loads(ws.sent[2]) == {"type": "text.clear"}


def test_send_text_rejects_empty_before_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _WsCapture()
    ws = cap.install(monkeypatch)
    session = client.open_tts_session()

    with pytest.raises(RuntimeError, match="empty"):
        session.send_text("")
    assert ws.sent == []
    session.close()


def test_send_text_rejects_oversized_delta_before_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _WsCapture()
    ws = cap.install(monkeypatch)
    session = client.open_tts_session()

    with pytest.raises(RuntimeError, match="15000"):
        session.send_text("x" * (TTS_MAX_DELTA_CHARS + 1))
    assert ws.sent == []
    session.close()


def test_open_tts_requires_purpose_when_metered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(usage_meter=UsageMeter(sink=InMemoryUsageSink()))
    cap = _WsCapture()
    cap.install(monkeypatch)

    with pytest.raises(ValueError, match="purpose"):
        client.open_tts_session()

    assert cap.calls == []


def test_open_tts_rejects_empty_credentials_before_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    client.api_key = "  "
    cap = _WsCapture()
    cap.install(monkeypatch)

    with pytest.raises(RuntimeError, match="credentials"):
        client.open_tts_session()

    assert cap.calls == []


def test_open_tts_rejects_invalid_codec_before_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _WsCapture()
    cap.install(monkeypatch)

    with pytest.raises(RuntimeError, match="codec"):
        client.open_tts_session(codec="ogg")

    assert cap.calls == []


def test_open_tts_rejects_invalid_sample_rate_before_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _WsCapture()
    cap.install(monkeypatch)

    with pytest.raises(RuntimeError, match="sample_rate"):
        client.open_tts_session(sample_rate=12000)

    assert cap.calls == []


def test_connect_failure_records_failed_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    sink = InMemoryUsageSink()
    meter = UsageMeter(sink=sink)
    client = _client(usage_meter=meter)

    def _boom(*_a: Any, **_k: Any) -> Any:
        raise OSError("offline")

    monkeypatch.setattr("xaikit.client.connect_tts_websocket", _boom)
    with pytest.raises(RuntimeError, match="TTS session connect failed"):
        client.open_tts_session(purpose="demo.tts.fail")

    ev = list(sink.iter_events())[0]
    assert ev.success is False
    assert ev.modality == "tts"
    assert ev.model == "tts"
    assert ev.purpose == "demo.tts.fail"
    assert ev.estimated_usd is None


def test_connect_401_skips_meter_then_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    sink = InMemoryUsageSink()
    client = _client(usage_meter=UsageMeter(sink=sink))

    class _Unauthorized(Exception):
        status_code = 401

    def _boom(*_a: Any, **_k: Any) -> Any:
        raise _Unauthorized("HTTP 401")

    monkeypatch.setattr("xaikit.client.connect_tts_websocket", _boom)
    with pytest.raises(RuntimeError, match="unauthorized"):
        client.open_tts_session(purpose="demo.tts.401")

    assert list(sink.iter_events()) == []


def test_open_tts_does_not_call_chat_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = MockChatProvider()
    client = XaiClient(
        provider=provider,
        model="grok-3-mini",
        api_key="test-key",
        retry_policy=default_retry_policy(max_attempts=1),
    )
    cap = _WsCapture()
    cap.install(monkeypatch)
    with client.open_tts_session() as session:
        session.send_text("hi")
        session.text_done()
    assert provider.calls == []


def test_server_error_event_raises_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    meter = UsageMeter(sink=sink)
    client = _client(usage_meter=meter)
    incoming = [json.dumps({"type": "error", "message": "bad text"})]
    cap = _WsCapture(incoming)
    cap.install(monkeypatch)

    session = client.open_tts_session(purpose="demo.tts.err")
    with pytest.raises(RuntimeError, match="TTS stream error"):
        session.recv()

    ev = list(sink.iter_events())[0]
    assert ev.success is False
    assert ev.modality == "tts"
    assert ev.purpose == "demo.tts.err"
    assert ev.estimated_usd is None


def test_events_yield_audio_delta_then_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incoming = [
        json.dumps({"type": "audio.delta", "delta": "aGVsbG8="}),
        json.dumps({"type": "audio.done", "trace_id": "t1"}),
    ]
    client = _client()
    cap = _WsCapture(incoming, empty_is_close=True)
    cap.install(monkeypatch)

    session = client.open_tts_session()
    got = list(session.events())
    kinds = [e["type"] for e in got]
    assert kinds == ["audio.delta", "audio.done"]
    assert decode_tts_audio(got[0]) == b"hello"
    session.close()


def test_decode_tts_audio_ignores_non_delta() -> None:
    assert decode_tts_audio({"type": "audio.done"}) is None
    assert decode_tts_audio({"type": "audio.delta", "delta": ""}) is None
