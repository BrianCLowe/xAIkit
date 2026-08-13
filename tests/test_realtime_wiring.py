"""Contract tests: realtime voice WebSocket wiring (URL, auth, events, metering)."""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest

from xaikit import (
    DEFAULT_VOICE_MODEL,
    InMemoryUsageSink,
    MockChatProvider,
    RealtimeSession,
    UsageMeter,
    XAI_REALTIME_URL,
    XaiClient,
    decode_realtime_audio,
    default_price_table,
    default_retry_policy,
)
from xaikit.realtime import RealtimeClosed


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
        self.sent: list[str] = []
        self.incoming: list[str | bytes] = list(incoming or [])
        self.closed = False
        self.close_calls = 0
        self.empty_is_close = empty_is_close

    def send(self, message: str | bytes) -> None:
        if self.closed:
            raise RealtimeClosed("socket closed")
        self.sent.append(message if isinstance(message, str) else message.decode("utf-8"))

    def recv(self, timeout: float | None = None) -> str | bytes:
        if self.closed:
            raise RealtimeClosed("socket closed")
        if not self.incoming:
            if self.empty_is_close:
                raise RealtimeClosed("socket closed")
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

        monkeypatch.setattr("xaikit.client.connect_realtime_websocket", _connect)
        return self.ws


def _sent_events(ws: FakeWebSocket) -> list[dict[str, Any]]:
    return [json.loads(raw) for raw in ws.sent]


def test_open_realtime_connects_with_auth_header_and_session_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    meter = UsageMeter(sink=sink)
    client = _client(usage_meter=meter)
    cap = _WsCapture()
    ws = cap.install(monkeypatch)

    session = client.open_realtime_session(
        voice="ara",
        instructions="You are a helpful assistant.",
        purpose="demo.realtime",
        parent_id="p1",
        labels={"request_id": "r1"},
    )

    assert isinstance(session, RealtimeSession)
    assert len(cap.calls) == 1
    call = cap.calls[0]
    assert call["uri"] == f"{XAI_REALTIME_URL}?model={DEFAULT_VOICE_MODEL}"
    assert call["additional_headers"]["Authorization"] == "Bearer test-key"
    assert call["open_timeout"] == 30.0

    events = _sent_events(ws)
    assert events[0]["type"] == "session.update"
    assert events[0]["session"]["voice"] == "ara"
    assert events[0]["session"]["instructions"] == "You are a helpful assistant."
    assert events[0]["session"]["turn_detection"] == {"type": "server_vad"}

    session.close()
    ev = list(sink.iter_events())[0]
    assert ev.purpose == "demo.realtime"
    assert ev.modality == "realtime"
    assert ev.model == DEFAULT_VOICE_MODEL
    assert ev.success is True
    assert ev.parent_id == "p1"
    assert ev.labels["request_id"] == "r1"
    assert ev.estimated_usd is not None
    assert ws.closed is True


def test_open_realtime_rejects_empty_credentials_before_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    client.api_key = "  "
    cap = _WsCapture()
    cap.install(monkeypatch)

    with pytest.raises(RuntimeError, match="credentials"):
        client.open_realtime_session()

    assert cap.calls == []


def test_open_realtime_requires_purpose_when_metered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(usage_meter=UsageMeter(sink=InMemoryUsageSink()))
    cap = _WsCapture()
    cap.install(monkeypatch)

    with pytest.raises(ValueError, match="purpose"):
        client.open_realtime_session()

    assert cap.calls == []


def test_send_audio_and_text_use_documented_event_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _WsCapture()
    ws = cap.install(monkeypatch)
    pcm = b"\x01\x02\x03\x04"

    with client.open_realtime_session() as session:
        session.send_audio(pcm)
        session.send_text("Hello there")
        session.commit_audio()
        session.clear_audio()

    events = _sent_events(ws)
    kinds = [e["type"] for e in events]
    assert kinds[0] == "session.update"
    assert events[1] == {
        "type": "input_audio_buffer.append",
        "audio": base64.b64encode(pcm).decode("ascii"),
    }
    assert events[2]["type"] == "conversation.item.create"
    assert events[2]["item"]["content"][0] == {"type": "input_text", "text": "Hello there"}
    assert events[3] == {"type": "response.create"}
    assert events[4] == {"type": "input_audio_buffer.commit"}
    assert events[5] == {"type": "input_audio_buffer.clear"}


def test_session_update_forwards_audio_tools_and_reasoning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _WsCapture()
    ws = cap.install(monkeypatch)
    audio = {
        "input": {"format": {"type": "audio/pcm", "rate": 16000}},
        "output": {"format": {"type": "audio/pcm", "rate": 16000}},
    }

    session = client.open_realtime_session(
        tools=[{"type": "web_search"}],
        audio=audio,
        reasoning_effort="none",
        turn_detection=None,
    )
    body = _sent_events(ws)[0]["session"]
    assert body["tools"] == [{"type": "web_search"}]
    assert body["audio"] == audio
    assert body["reasoning"] == {"effort": "none"}
    assert body["turn_detection"] is None
    session.close()


def test_send_audio_and_text_reject_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client()
    cap = _WsCapture()
    cap.install(monkeypatch)
    session = client.open_realtime_session()

    with pytest.raises(RuntimeError, match="empty"):
        session.send_audio(b"")
    with pytest.raises(RuntimeError, match="empty"):
        session.send_text("  ")
    session.close()


def test_recv_timeout_does_not_fail_session_and_can_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    meter = UsageMeter(sink=sink)
    client = _client(usage_meter=meter)
    cap = _WsCapture()
    ws = cap.install(monkeypatch)
    session = client.open_realtime_session(purpose="demo.realtime.timeout")

    with pytest.raises(TimeoutError):
        session.recv(timeout=0.01)
    assert list(sink.iter_events()) == []
    assert ws.closed is False

    ws.incoming.append(json.dumps({"type": "session.updated"}))
    event = session.recv()
    assert event["type"] == "session.updated"
    session.close()
    ev = list(sink.iter_events())[0]
    assert ev.success is True
    assert ev.modality == "realtime"


def test_events_normal_close_records_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    meter = UsageMeter(sink=sink)
    incoming = [json.dumps({"type": "session.updated"})]
    client = _client(usage_meter=meter)
    cap = _WsCapture(incoming, empty_is_close=True)
    cap.install(monkeypatch)

    session = client.open_realtime_session(purpose="demo.realtime.events")
    got = list(session.events())
    assert len(got) == 1
    assert got[0]["type"] == "session.updated"
    assert list(sink.iter_events()) == []
    session.close()
    ev = list(sink.iter_events())[0]
    assert ev.success is True
    assert ev.modality == "realtime"


def test_recv_output_audio_delta_and_decode(monkeypatch: pytest.MonkeyPatch) -> None:
    pcm = b"pcm-bytes"
    incoming = [
        json.dumps(
            {
                "type": "response.output_audio.delta",
                "delta": base64.b64encode(pcm).decode("ascii"),
            }
        )
    ]
    client = _client()
    cap = _WsCapture(incoming)
    cap.install(monkeypatch)

    session = client.open_realtime_session()
    event = session.recv()
    assert event["type"] == "response.output_audio.delta"
    assert decode_realtime_audio(event) == pcm
    session.close()


def test_connect_failure_records_failed_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    sink = InMemoryUsageSink()
    meter = UsageMeter(sink=sink)
    client = _client(usage_meter=meter)

    def _boom(*_a: Any, **_k: Any) -> Any:
        raise OSError("offline")

    monkeypatch.setattr("xaikit.client.connect_realtime_websocket", _boom)
    with pytest.raises(RuntimeError, match="Realtime session connect failed"):
        client.open_realtime_session(purpose="demo.realtime.fail")

    ev = list(sink.iter_events())[0]
    assert ev.success is False
    assert ev.modality == "realtime"
    assert ev.purpose == "demo.realtime.fail"


def test_send_failure_records_failed_usage_and_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    meter = UsageMeter(sink=sink)
    client = _client(usage_meter=meter)
    cap = _WsCapture()
    ws = cap.install(monkeypatch)

    session = client.open_realtime_session(purpose="demo.realtime.sendfail")

    def _boom(_message: str | bytes) -> None:
        raise OSError("broken pipe")

    ws.send = _boom  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="Realtime send failed"):
        session.send_text("hi")

    ev = list(sink.iter_events())[0]
    assert ev.success is False
    assert ev.modality == "realtime"
    assert ev.purpose == "demo.realtime.sendfail"


def test_open_realtime_per_call_model_override(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(voice_model="client-default-voice")
    cap = _WsCapture()
    cap.install(monkeypatch)

    session = client.open_realtime_session(model="grok-voice-think-fast-1.0")
    assert cap.calls[0]["uri"].endswith("model=grok-voice-think-fast-1.0")
    assert session.model == "grok-voice-think-fast-1.0"
    session.close()


def test_open_realtime_default_model_constant() -> None:
    client = _client()
    assert client.voice_model == DEFAULT_VOICE_MODEL
    assert DEFAULT_VOICE_MODEL == "grok-voice-latest"


def test_default_price_table_voice_per_minute_rates() -> None:
    table = default_price_table()
    latest = table.price_for("grok-voice-latest")
    assert latest.per_minute_usd == 0.08
    assert table.estimate_usd(
        "grok-voice-latest", duration_seconds=60
    ) == pytest.approx(0.08)
    v1 = table.price_for("grok-voice-think-fast-1.0")
    assert v1.per_minute_usd == 0.05
    assert table.estimate_usd(
        "grok-voice-think-fast-1.0", duration_seconds=30
    ) == pytest.approx(0.025)
    v2 = table.price_for("grok-voice-think-fast-2.0")
    assert v2.per_minute_usd == 0.08
