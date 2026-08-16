"""Contract tests: chat knobs reach MockChatProvider / SDK kwargs as documented."""

from __future__ import annotations

import pytest

from xaikit import (
    InMemoryUsageSink,
    MockChatProvider,
    UsageMeter,
    XaiClient,
    contract_thought_level,
    default_retry_policy,
    effort_options,
    feature_options,
    normalize_thought_level,
)
from xaikit.provider import _sdk_chat_kwargs


def _client(provider: MockChatProvider, **kwargs) -> XaiClient:
    kwargs.setdefault("model", "grok-3-mini")
    return XaiClient(
        provider=provider,
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
        effort="medium",  # grok-3-mini is low|high only → contracts to low
    )

    assert provider.calls[0]["thought_level"] == "low"


def test_medium_and_xhigh_pass_through_on_grok_46() -> None:
    provider = MockChatProvider(replies="ok")
    client = _client(provider, model="grok-4.6")

    client.chat([{"role": "user", "content": "hi"}], thought_level="medium")
    client.chat([{"role": "user", "content": "hi"}], thought_level="xhigh")

    assert provider.calls[0]["thought_level"] == "medium"
    assert provider.calls[1]["thought_level"] == "xhigh"


def test_xhigh_contracts_to_high_on_grok_45() -> None:
    provider = MockChatProvider(replies="ok")
    client = _client(provider, model="grok-4.5")

    client.chat([{"role": "user", "content": "hi"}], thought_level="xhigh")
    assert provider.calls[0]["thought_level"] == "high"


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
        ("med", "medium"),
        ("medium", "medium"),
        ("mid", "medium"),
        ("xhigh", "xhigh"),
        ("x-high", "xhigh"),
        ("extra_high", "xhigh"),
        ("max", "xhigh"),
        ("nope", None),
    ],
)
def test_normalize_thought_level_contract(raw: str | None, expected: str | None) -> None:
    assert normalize_thought_level(raw) == expected


@pytest.mark.parametrize(
    ("level", "model", "expected"),
    [
        ("xhigh", "grok-4.6", "xhigh"),
        ("medium", "grok-4.6", "medium"),
        ("xhigh", "grok-4.5", "high"),
        ("medium", "grok-4.5", "medium"),
        ("xhigh", "grok-4.20-0309-reasoning", "high"),
        ("medium", "grok-4.20-0309-reasoning", "low"),
        ("xhigh", "grok-4.20-0309-non-reasoning", None),
        ("low", "grok-4.20-0309-non-reasoning", None),
        ("xhigh", "grok-4.20-multi-agent-0309", "xhigh"),
        ("medium", "grok-3-mini", "low"),
        ("xhigh", None, "xhigh"),
    ],
)
def test_contract_thought_level_by_model(
    level: str, model: str | None, expected: str | None
) -> None:
    assert contract_thought_level(level, model) == expected


def test_effort_options_full_set_and_per_model() -> None:
    assert effort_options() == ["low", "medium", "high", "xhigh"]
    assert effort_options("grok-4.6") == ["low", "medium", "high", "xhigh"]
    assert effort_options("grok-4.5") == ["low", "medium", "high"]
    assert effort_options("grok-4.20-0309-non-reasoning") == []
    assert effort_options("grok-3-mini") == ["low", "high"]


def test_feature_options_chat_and_video_per_sku() -> None:
    flagship = [
        "web_search",
        "x_search",
        "code_execution",
        "file_attachments",
        "collections_search",
        "image_understanding",
        "x_video_understanding",
        "mcp",
    ]
    assert feature_options() == flagship
    assert feature_options("grok-4.6") == flagship
    assert feature_options("grok-4.7") == flagship
    assert feature_options("grok-4.5") == []
    assert feature_options("grok-4.20-0309-non-reasoning") == []
    assert feature_options("grok-imagine-video") == [
        "video_extend",
        "video_edit",
        "r2v",
    ]
    assert feature_options("grok-imagine-video-1.5") == ["1080p", "r2v"]
    assert "video_extend" not in feature_options("grok-imagine-video-1.5")
    assert feature_options("unknown-sku") == []


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

    xhigh_46 = _sdk_chat_kwargs(
        model="grok-4.6",
        temperature=0.5,
        max_tokens=None,
        thought_level="xhigh",
    )
    assert xhigh_46["reasoning_effort"] == "xhigh"

    xhigh_45 = _sdk_chat_kwargs(
        model="grok-4.5",
        temperature=0.5,
        max_tokens=None,
        thought_level="xhigh",
    )
    assert xhigh_45["reasoning_effort"] == "high"

    omitted_nr = _sdk_chat_kwargs(
        model="grok-4.20-0309-non-reasoning",
        temperature=0.5,
        max_tokens=None,
        thought_level="high",
    )
    assert "reasoning_effort" not in omitted_nr


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
