"""Offline prove-out: MockChatProvider + UsageMeter + InMemory sink."""

from __future__ import annotations

import pytest

from xaikit import (
    InMemoryUsageSink,
    MockChatProvider,
    UsageMeter,
    XaiClient,
    default_price_table,
    default_retry_policy,
)


def test_metered_chat_records_by_purpose() -> None:
    sink = InMemoryUsageSink()
    meter = UsageMeter(sink=sink, price_table=default_price_table())
    provider = MockChatProvider(replies="hello from mock")
    client = XaiClient(
        provider=provider,
        model="grok-3-mini",
        usage_meter=meter,
        retry_policy=default_retry_policy(max_attempts=1),
    )

    resp = client.chat(
        [{"role": "user", "content": "hi"}],
        purpose="demo.chat",
        thought_level="low",
    )
    assert resp.content == "hello from mock"
    assert resp.model == "grok-3-mini"

    events = list(sink.iter_events())
    assert len(events) == 1
    assert events[0].purpose == "demo.chat"
    assert events[0].success is True
    assert events[0].thought_level == "low"
    assert events[0].prompt_tokens == 10
    assert events[0].estimated_usd is not None

    rollups = meter.rollup_by_purpose()
    assert len(rollups) == 1
    assert rollups[0].key == "demo.chat"
    assert rollups[0].event_count == 1


def test_purpose_required_when_meter_attached() -> None:
    meter = UsageMeter(sink=InMemoryUsageSink())
    client = XaiClient(
        provider=MockChatProvider(),
        model="grok-4.5",
        usage_meter=meter,
    )
    with pytest.raises(ValueError, match="purpose"):
        client.chat([{"role": "user", "content": "x"}])


def test_purpose_optional_without_meter() -> None:
    client = XaiClient(
        provider=MockChatProvider(replies="ok"),
        model="grok-4.5",
    )
    resp = client.chat([{"role": "user", "content": "x"}])
    assert resp.content == "ok"


def test_retry_fail_times_then_succeed() -> None:
    sink = InMemoryUsageSink()
    meter = UsageMeter(sink=sink)
    provider = MockChatProvider(replies="recovered", fail_times=2)
    client = XaiClient(
        provider=provider,
        model="grok-4.5",
        usage_meter=meter,
        retry_policy=default_retry_policy(max_attempts=3, backoff_seconds=0.0),
    )
    resp = client.chat(
        [{"role": "user", "content": "retry me"}],
        purpose="ops.retry",
    )
    assert resp.content == "recovered"
    assert len(provider.calls) == 3
    assert len(list(sink.iter_events())) == 1
    assert list(sink.iter_events())[0].success is True


def test_chat_json_and_labels() -> None:
    sink = InMemoryUsageSink()
    meter = UsageMeter(sink=sink)
    provider = MockChatProvider(replies={"ok": True, "n": 1})
    client = XaiClient(
        provider=provider,
        model="grok-4.5",
        usage_meter=meter,
        retry_policy=default_retry_policy(max_attempts=1),
    )
    data = client.chat_json(
        "return json",
        purpose="demo.structured",
        labels={"request_id": "abc"},
        parent_id="sess-1",
    )
    assert data == {"ok": True, "n": 1}
    ev = list(sink.iter_events())[0]
    assert ev.labels["request_id"] == "abc"
    assert ev.parent_id == "sess-1"
