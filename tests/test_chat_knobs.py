"""Contract tests: chat knobs reach MockChatProvider / SDK kwargs as documented."""

from __future__ import annotations

import pytest

from xaikit import (
    InMemoryUsageSink,
    MockChatProvider,
    UsageMeter,
    XaiClient,
    default_retry_policy,
    normalize_thought_level,
)
from xaikit.provider import _sdk_chat_kwargs


def _client(provider: MockChatProvider, **kwargs) -> XaiClient:
    return XaiClient(
        provider=provider,
        model="grok-3-mini",
        retry_policy=default_retry_policy(max_attempts=1),
        **kwargs,
    )


def test_chat_forwards_temperature_max_tokens_system_and_thought_level() -> None:
    provider = MockChatProvider(replies="ok")
    client = _client(provider)

    client.chat(
        [{"role": "user", "content": "hi"}],
        temperature=0.2,
        max_tokens=128,
        system_prompt="be brief",
        thought_level="high",
    )

    assert len(provider.calls) == 1
    call = provider.calls[0]
    assert call["kind"] == "complete"
    assert call["model"] == "grok-3-mini"
    assert call["temperature"] == 0.2
    assert call["max_tokens"] == 128
    assert call["system_prompt"] == "be brief"
    assert call["thought_level"] == "high"
    assert call["messages"] == [{"role": "user", "content": "hi"}]


def test_effort_alias_maps_like_thought_level_on_chat() -> None:
    provider = MockChatProvider(replies="ok")
    client = _client(provider)

    client.chat(
        [{"role": "user", "content": "hi"}],
        effort="medium",  # product alias → API low
    )

    assert provider.calls[0]["thought_level"] == "low"


def test_call_thought_level_overrides_client_default() -> None:
    provider = MockChatProvider(replies="ok")
    client = _client(provider, thought_level="low")

    client.chat([{"role": "user", "content": "hi"}], thought_level="high")
    assert provider.calls[0]["thought_level"] == "high"

    client.chat([{"role": "user", "content": "again"}])
    assert provider.calls[1]["thought_level"] == "low"


def test_chat_stream_forwards_same_knobs() -> None:
    provider = MockChatProvider(replies="streamed", stream_chunk_size=4)
    client = _client(provider)

    chunks = list(
        client.chat_stream(
            [{"role": "user", "content": "hi"}],
            temperature=0.1,
            max_tokens=64,
            system_prompt="sys",
            thought_level="high",
        )
    )
    assert "".join(c.delta for c in chunks) == "streamed"

    call = provider.calls[0]
    assert call["kind"] == "stream"
    assert call["temperature"] == 0.1
    assert call["max_tokens"] == 64
    assert call["system_prompt"] == "sys"
    assert call["thought_level"] == "high"


def test_chat_json_uses_json_system_prompt_and_lower_default_temperature() -> None:
    provider = MockChatProvider(replies={"ok": True})
    client = _client(provider)

    data = client.chat_json("return json", thought_level="low")
    assert data == {"ok": True}

    call = provider.calls[0]
    assert call["kind"] == "complete"
    assert call["temperature"] == 0.3
    assert call["thought_level"] == "low"
    assert "ONLY valid JSON" in (call["system_prompt"] or "")
    assert call["messages"] == [{"role": "user", "content": "return json"}]


def test_chat_json_custom_system_prompt_override() -> None:
    provider = MockChatProvider(replies={"n": 1})
    client = _client(provider)

    client.chat_json("x", system_prompt="custom json rules", temperature=0.0)
    assert provider.calls[0]["system_prompt"] == "custom json rules"
    assert provider.calls[0]["temperature"] == 0.0


def test_meter_records_purpose_labels_and_thought_level_from_knobs() -> None:
    sink = InMemoryUsageSink()
    meter = UsageMeter(sink=sink)
    provider = MockChatProvider(replies="ok")
    client = _client(provider, usage_meter=meter)

    client.chat(
        [{"role": "user", "content": "hi"}],
        purpose="demo.knobs",
        parent_id="parent-1",
        labels={"request_id": "r1"},
        effort="high",
    )

    ev = list(sink.iter_events())[0]
    assert ev.purpose == "demo.knobs"
    assert ev.parent_id == "parent-1"
    assert ev.labels["request_id"] == "r1"
    assert ev.thought_level == "high"
    assert ev.modality == "chat"
    assert provider.calls[0]["thought_level"] == "high"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("  ", None),
        ("low", "low"),
        ("HIGH", "high"),
        ("med", "low"),
        ("medium", "low"),
        ("mid", "low"),
        ("nope", None),
    ],
)
def test_normalize_thought_level_contract(raw: str | None, expected: str | None) -> None:
    assert normalize_thought_level(raw) == expected


def test_sdk_chat_kwargs_maps_thought_level_to_reasoning_effort() -> None:
    kwargs = _sdk_chat_kwargs(
        model="grok-4.5",
        temperature=0.5,
        max_tokens=256,
        thought_level="high",
    )
    assert kwargs == {
        "model": "grok-4.5",
        "temperature": 0.5,
        "max_tokens": 256,
        "reasoning_effort": "high",
    }

    omitted = _sdk_chat_kwargs(
        model="grok-4.5",
        temperature=0.7,
        max_tokens=None,
        thought_level=None,
    )
    assert "max_tokens" not in omitted
    assert "reasoning_effort" not in omitted
    assert "service_tier" not in omitted


def test_chat_forwards_service_tier_to_mock() -> None:
    provider = MockChatProvider(replies="ok")
    client = _client(provider)

    resp = client.chat(
        [{"role": "user", "content": "hi"}],
        service_tier="priority",
    )

    assert provider.calls[0]["service_tier"] == "priority"
    assert resp.service_tier == "priority"


def test_chat_omits_service_tier_when_none() -> None:
    provider = MockChatProvider(replies="ok")
    client = _client(provider)

    resp = client.chat([{"role": "user", "content": "hi"}])

    assert provider.calls[0]["service_tier"] is None
    assert resp.service_tier is None


def test_chat_json_and_stream_forward_service_tier() -> None:
    provider = MockChatProvider(replies={"ok": True})
    client = _client(provider)
    client.chat_json("return json", service_tier="default")
    assert provider.calls[0]["service_tier"] == "default"

    provider = MockChatProvider(replies="streamed", stream_chunk_size=4)
    client = _client(provider)
    list(
        client.chat_stream(
            [{"role": "user", "content": "hi"}],
            service_tier="priority",
        )
    )
    assert provider.calls[0]["service_tier"] == "priority"


def test_invalid_service_tier_rejected_before_provider() -> None:
    provider = MockChatProvider(replies="ok")
    client = _client(provider)
    with pytest.raises(ValueError, match="service_tier"):
        client.chat([{"role": "user", "content": "hi"}], service_tier="turbo")
    assert provider.calls == []


def test_sdk_chat_kwargs_includes_service_tier_when_set() -> None:
    kwargs = _sdk_chat_kwargs(
        model="grok-4.5",
        temperature=0.5,
        max_tokens=None,
        thought_level=None,
        service_tier="priority",
    )
    assert kwargs["service_tier"] == "priority"

    omitted = _sdk_chat_kwargs(
        model="grok-4.5",
        temperature=0.7,
        max_tokens=None,
        thought_level=None,
        service_tier=None,
    )
    assert "service_tier" not in omitted
