"""Offline prove-out: chat_stream + opt-in completion traces."""

from __future__ import annotations

import pytest

from xaikit import (
    CompletionTracer,
    InMemoryTraceSink,
    InMemoryUsageSink,
    MockChatProvider,
    UsageMeter,
    XaiClient,
    default_retry_policy,
)


def test_chat_stream_yields_incremental_deltas_and_meters() -> None:
    sink = InMemoryUsageSink()
    meter = UsageMeter(sink=sink)
    provider = MockChatProvider(replies="hello!", stream_chunk_size=3)
    client = XaiClient(
        provider=provider,
        model="grok-3-mini",
        usage_meter=meter,
        retry_policy=default_retry_policy(max_attempts=1),
    )

    deltas: list[str] = []
    accumulated = ""
    for chunk in client.chat_stream(
        [{"role": "user", "content": "hi"}],
        purpose="quill.stream",
    ):
        assert chunk.delta
        deltas.append(chunk.delta)
        accumulated = chunk.accumulated

    assert "".join(deltas) == "hello!"
    assert accumulated == "hello!"
    assert len(deltas) > 1  # real incremental stream, not one buffered chunk
    assert provider.calls[-1]["kind"] == "stream"

    events = list(sink.iter_events())
    assert len(events) == 1
    assert events[0].purpose == "quill.stream"
    assert events[0].success is True
    assert events[0].prompt_tokens == 10


def test_chat_stream_purpose_required_when_metered() -> None:
    client = XaiClient(
        provider=MockChatProvider(replies="x"),
        model="grok-4.5",
        usage_meter=UsageMeter(sink=InMemoryUsageSink()),
    )
    with pytest.raises(ValueError, match="purpose"):
        list(client.chat_stream([{"role": "user", "content": "x"}]))


def test_completion_tracer_records_prompt_and_response() -> None:
    trace_sink = InMemoryTraceSink()
    tracer = CompletionTracer(sink=trace_sink)
    client = XaiClient(
        provider=MockChatProvider(replies="traced reply"),
        model="grok-4.5",
        completion_tracer=tracer,
        retry_policy=default_retry_policy(max_attempts=1),
    )

    resp = client.chat(
        [{"role": "user", "content": "secret-ish prompt"}],
        system_prompt="be brief",
        purpose="dev.trace",
    )
    assert resp.content == "traced reply"

    events = list(trace_sink.iter_events())
    assert len(events) == 1
    ev = events[0]
    assert ev.success is True
    assert ev.messages == [{"role": "user", "content": "secret-ish prompt"}]
    assert ev.system_prompt == "be brief"
    assert ev.response == "traced reply"
    assert ev.purpose == "dev.trace"
    assert ev.model == "grok-4.5"


def test_completion_tracer_default_off() -> None:
    client = XaiClient(
        provider=MockChatProvider(replies="ok"),
        model="grok-4.5",
    )
    assert client.chat([{"role": "user", "content": "x"}]).content == "ok"
    assert client._completion_tracer is None


def test_stream_and_chat_json_also_trace() -> None:
    trace_sink = InMemoryTraceSink()
    tracer = CompletionTracer(sink=trace_sink)
    client = XaiClient(
        provider=MockChatProvider(replies={"ok": True}),
        model="grok-4.5",
        completion_tracer=tracer,
        retry_policy=default_retry_policy(max_attempts=1),
    )

    chunks = list(
        client.chat_stream(
            [{"role": "user", "content": "stream me"}],
            purpose="dev.stream",
        )
    )
    assert "".join(c.delta for c in chunks) == '{"ok": true}'

    data = client.chat_json("return json", purpose="dev.json")
    assert data == {"ok": True}

    events = list(trace_sink.iter_events())
    assert len(events) == 2
    assert events[0].response == '{"ok": true}'
    assert events[1].success is True
