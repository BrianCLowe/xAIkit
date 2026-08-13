"""Contract tests: streaming STT WebSocket wiring (URL, auth, binary, metering)."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from xaikit import (
    InMemoryUsageSink,
    MockChatProvider,
    SttSession,
    UsageMeter,
    XAI_STT_WS_URL,
    XaiClient,
    default_price_table,
    default_retry_policy,
)
from xaikit.stt_stream import SttClosed


def _client(*, usage_meter: UsageMeter | None = None, **kwargs: Any) -> XaiClient:
    return XaiClient(
        provider=MockChatProvider(),
        model="grok-3-mini",
        api_key="test-key",
        usage_meter=usage_meter,
        retry_policy=default_retry_policy(max_attempts=1),
        **kwargs,
    )


def _created() -> str:
    return json.dumps({"type": "transcript.created"})


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
            raise SttClosed("socket closed")
        self.ops.append("send")
        self.sent.append(message)

    def recv(self, timeout: float | None = None) -> str | bytes:
        if self.closed:
            raise SttClosed("socket closed")
        self.ops.append("recv")
        if not self.incoming:
            if self.empty_is_close:
                raise SttClosed("socket closed")
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

        monkeypatch.setattr("xaikit.client.connect_stt_websocket", _connect)
        return self.ws


def test_open_stt_connects_with_auth_header_query_and_meters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    meter = UsageMeter(sink=sink)
    client = _client(usage_meter=meter)
    cap = _WsCapture([_created()])
    ws = cap.install(monkeypatch)

    session = client.open_stt_session(
        language="en",
        interim_results=True,
        keyterm=["Understand The Universe", "Grok"],
        purpose="demo.stt.stream",
        parent_id="p1",
        labels={"request_id": "r1"},
    )

    assert isinstance(session, SttSession)
    assert len(cap.calls) == 1
    call = cap.calls[0]
    parts = urlsplit(call["uri"])
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == XAI_STT_WS_URL
    query = parse_qs(parts.query)
    assert query["sample_rate"] == ["16000"]
    assert query["encoding"] == ["pcm"]
    assert query["language"] == ["en"]
    assert query["interim_results"] == ["true"]
    assert query["keyterm"] == ["Understand The Universe", "Grok"]
    assert call["additional_headers"]["Authorization"] == "Bearer test-key"
    assert call["open_timeout"] == 30.0

    session.close()
    ev = list(sink.iter_events())[0]
    assert ev.purpose == "demo.stt.stream"
    assert ev.modality == "stt"
    assert ev.model == "stt"
    assert ev.success is True
    assert ev.parent_id == "p1"
    assert ev.labels["request_id"] == "r1"
    assert ev.estimated_usd is not None
    assert ws.closed is True


def test_wait_for_created_before_sending_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _WsCapture([_created()])
    ws = cap.install(monkeypatch)
    pcm = b"\x01\x02\x03\x04"

    session = client.open_stt_session()
    assert ws.ops == ["recv"]
    assert not ws.sent

    session.send_audio(pcm)
    assert ws.ops[0] == "recv"
    assert "send" in ws.ops
    assert ws.ops.index("recv") < ws.ops.index("send")
    assert ws.sent[0] == pcm
    assert isinstance(ws.sent[0], bytes)
    session.close()


def test_send_audio_is_raw_binary_not_base64(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _WsCapture([_created()])
    ws = cap.install(monkeypatch)
    pcm = b"\x00\xff\x10\x20"

    with client.open_stt_session() as session:
        session.send_audio(pcm)
        session.finalize()
        session.audio_done()

    assert ws.sent[0] == pcm
    assert json.loads(ws.sent[1]) == {"type": "finalize"}
    assert json.loads(ws.sent[2]) == {"type": "audio.done"}


def test_send_audio_rejects_empty_before_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _WsCapture([_created()])
    ws = cap.install(monkeypatch)
    session = client.open_stt_session()

    with pytest.raises(RuntimeError, match="empty"):
        session.send_audio(b"")
    assert ws.sent == []
    session.close()


def test_open_stt_requires_purpose_when_metered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(usage_meter=UsageMeter(sink=InMemoryUsageSink()))
    cap = _WsCapture([_created()])
    cap.install(monkeypatch)

    with pytest.raises(ValueError, match="purpose"):
        client.open_stt_session()

    assert cap.calls == []


def test_open_stt_rejects_empty_credentials_before_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    client.api_key = "  "
    cap = _WsCapture([_created()])
    cap.install(monkeypatch)

    with pytest.raises(RuntimeError, match="credentials"):
        client.open_stt_session()

    assert cap.calls == []


def test_server_error_event_raises_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    meter = UsageMeter(sink=sink)
    client = _client(usage_meter=meter)
    incoming = [
        _created(),
        json.dumps({"type": "error", "message": "bad audio"}),
    ]
    cap = _WsCapture(incoming)
    cap.install(monkeypatch)

    session = client.open_stt_session(purpose="demo.stt.err")
    session.recv()  # transcript.created (stashed at handshake)
    with pytest.raises(RuntimeError, match="STT stream error"):
        session.recv()

    ev = list(sink.iter_events())[0]
    assert ev.success is False
    assert ev.modality == "stt"
    assert ev.purpose == "demo.stt.err"


def test_connect_failure_records_failed_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    sink = InMemoryUsageSink()
    meter = UsageMeter(sink=sink)
    client = _client(usage_meter=meter)

    def _boom(*_a: Any, **_k: Any) -> Any:
        raise OSError("offline")

    monkeypatch.setattr("xaikit.client.connect_stt_websocket", _boom)
    with pytest.raises(RuntimeError, match="STT session connect failed"):
        client.open_stt_session(purpose="demo.stt.fail")

    ev = list(sink.iter_events())[0]
    assert ev.success is False
    assert ev.modality == "stt"
    assert ev.purpose == "demo.stt.fail"


def test_events_yield_partial_then_done(monkeypatch: pytest.MonkeyPatch) -> None:
    incoming = [
        _created(),
        json.dumps(
            {
                "type": "transcript.partial",
                "text": "hello",
                "is_final": False,
                "speech_final": False,
            }
        ),
        json.dumps(
            {
                "type": "transcript.done",
                "text": "hello",
                "duration": 0.4,
            }
        ),
    ]
    client = _client()
    cap = _WsCapture(incoming, empty_is_close=True)
    cap.install(monkeypatch)

    session = client.open_stt_session()
    got = list(session.events())
    kinds = [e["type"] for e in got]
    assert kinds == [
        "transcript.created",
        "transcript.partial",
        "transcript.done",
    ]
    session.close()


def test_finalize_with_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client()
    cap = _WsCapture([_created()])
    ws = cap.install(monkeypatch)
    session = client.open_stt_session(multichannel=True, channels=2)
    session.finalize(channel=0)
    assert json.loads(ws.sent[0]) == {"type": "finalize", "channel": 0}
    session.close()


def test_default_price_table_streaming_stt_per_hour_rate() -> None:
    table = default_price_table()
    stt = table.price_for("stt")
    assert stt.per_minute_usd == pytest.approx(0.20 / 60.0)
    assert table.estimate_usd("stt", duration_seconds=3600) == pytest.approx(0.20)
    assert table.estimate_usd("stt", duration_seconds=60) == pytest.approx(
        0.20 / 60.0, abs=1e-8
    )
