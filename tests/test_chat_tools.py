"""Contract tests: tools, multimodal parts, and chat_json schema knobs."""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from xaikit import MockChatProvider, XaiClient, default_retry_policy
from xaikit.provider import (
    _build_sdk_messages,
    _normalize_tool_calls,
    _parse_tool_arguments,
    _sdk_chat_kwargs,
    _sdk_response_format,
)
from xai_sdk.proto import chat_pb2


def _client(provider: MockChatProvider, **kwargs) -> XaiClient:
    return XaiClient(
        provider=provider,
        model="grok-3-mini",
        retry_policy=default_retry_policy(max_attempts=1),
        **kwargs,
    )


WEATHER_TOOL = {
    "name": "get_weather",
    "description": "Get the weather for a city.",
    "parameters": {
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
    },
}


def test_chat_forwards_tools_and_choice_to_mock() -> None:
    provider = MockChatProvider(
        replies={
            "content": "",
            "tool_calls": [
                {"id": "call_1", "name": "get_weather", "arguments": {"city": "NYC"}},
            ],
        }
    )
    client = _client(provider)

    resp = client.chat(
        [{"role": "user", "content": "weather in NYC?"}],
        tools=[WEATHER_TOOL],
        tool_choice="auto",
        parallel_tool_calls=False,
    )

    assert resp.tool_calls == [
        {"id": "call_1", "name": "get_weather", "arguments": {"city": "NYC"}},
    ]
    assert resp.finish_reason == "tool_calls"
    call = provider.calls[0]
    assert call["tools"] == [WEATHER_TOOL]
    assert call["tool_choice"] == "auto"
    assert call["parallel_tool_calls"] is False


def test_chat_does_not_execute_tools() -> None:
    provider = MockChatProvider(
        replies={
            "tool_calls": [
                {"id": "c1", "name": "get_weather", "arguments": {"city": "NYC"}},
            ],
        }
    )
    client = _client(provider)
    resp = client.chat(
        [{"role": "user", "content": "weather?"}],
        tools=[WEATHER_TOOL],
    )
    assert resp.tool_calls
    # Kit returns the call; it does not invoke get_weather.


def test_tool_result_and_assistant_tool_calls_recorded_on_follow_up() -> None:
    provider = MockChatProvider(replies="72F and sunny")
    client = _client(provider)
    messages = [
        {"role": "user", "content": "weather in NYC?"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_1", "name": "get_weather", "arguments": {"city": "NYC"}},
            ],
        },
        {
            "role": "tool",
            "content": "72F",
            "tool_call_id": "call_1",
            "name": "get_weather",
        },
    ]
    resp = client.chat(messages, tools=[WEATHER_TOOL])
    assert resp.content == "72F and sunny"
    recorded = provider.calls[0]["messages"]
    assert recorded[1]["tool_calls"][0]["name"] == "get_weather"
    assert recorded[2]["role"] == "tool"
    assert recorded[2]["tool_call_id"] == "call_1"
    assert recorded[2]["content"] == "72F"


def test_multimodal_image_and_file_parts_recorded() -> None:
    provider = MockChatProvider(replies="a red cube")
    client = _client(provider)
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "what is this?"},
                {"type": "image_url", "url": "https://example.com/cube.png"},
                {"type": "file", "file_id": "file-abc"},
            ],
        }
    ]
    resp = client.chat(messages)
    assert resp.content == "a red cube"
    parts = provider.calls[0]["messages"][0]["content"]
    assert parts[0] == {"type": "text", "text": "what is this?"}
    assert parts[1]["url"] == "https://example.com/cube.png"
    assert parts[2]["file_id"] == "file-abc"


def test_chat_json_records_schema_as_response_format() -> None:
    schema = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
    }
    provider = MockChatProvider(replies={"ok": True})
    client = _client(provider)
    data = client.chat_json("return json", schema=schema)
    assert data == {"ok": True}
    assert provider.calls[0]["response_format"] == schema


def test_chat_json_response_format_json_object_knob() -> None:
    provider = MockChatProvider(replies={"n": 1})
    client = _client(provider)
    client.chat_json("x", response_format="json_object")
    assert provider.calls[0]["response_format"] == "json_object"


def test_chat_json_schema_wins_over_response_format() -> None:
    schema = {"type": "object", "properties": {"a": {"type": "string"}}}
    provider = MockChatProvider(replies={"a": "b"})
    client = _client(provider)
    client.chat_json("x", schema=schema, response_format="json_object")
    assert provider.calls[0]["response_format"] == schema


class _Item(BaseModel):
    name: str = Field(description="item name")


def test_chat_json_pydantic_schema_recorded() -> None:
    provider = MockChatProvider(replies={"name": "cube"})
    client = _client(provider)
    data = client.chat_json("item", schema=_Item)
    assert data == {"name": "cube"}
    assert provider.calls[0]["response_format"] is _Item


def test_chat_json_still_strips_fences_when_schema_set() -> None:
    provider = MockChatProvider(replies='```json\n{"ok": true}\n```')
    client = _client(provider)
    data = client.chat_json("x", schema={"type": "object"})
    assert data == {"ok": True}


def test_chat_stream_forwards_tools_and_accumulates_tool_calls() -> None:
    provider = MockChatProvider(
        replies={
            "content": "",
            "tool_calls": [
                {"id": "c1", "name": "get_weather", "arguments": '{"city": "NYC"}'},
            ],
        }
    )
    client = _client(provider)
    chunks = list(
        client.chat_stream(
            [{"role": "user", "content": "weather?"}],
            tools=[WEATHER_TOOL],
            tool_choice={"name": "get_weather"},
        )
    )
    assert chunks[-1].tool_calls == [
        {"id": "c1", "name": "get_weather", "arguments": {"city": "NYC"}},
    ]
    assert chunks[-1].tool_call_delta == chunks[-1].tool_calls
    call = provider.calls[0]
    assert call["kind"] == "stream"
    assert call["tools"] == [WEATHER_TOOL]
    assert call["tool_choice"] == {"name": "get_weather"}


def test_sdk_chat_kwargs_omits_new_knobs_when_unset() -> None:
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


def test_sdk_chat_kwargs_maps_tools_choice_and_schema() -> None:
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    kwargs = _sdk_chat_kwargs(
        model="grok-4.5",
        temperature=0.2,
        max_tokens=None,
        thought_level=None,
        tools=[WEATHER_TOOL],
        tool_choice="required",
        parallel_tool_calls=False,
        response_format=schema,
    )
    assert kwargs["tools"][0].function.name == "get_weather"
    params = json.loads(kwargs["tools"][0].function.parameters)
    assert params["required"] == ["city"]
    assert kwargs["tool_choice"] == "required"
    assert kwargs["parallel_tool_calls"] is False
    fmt = kwargs["response_format"]
    assert fmt.format_type == chat_pb2.FORMAT_TYPE_JSON_SCHEMA
    assert json.loads(fmt.schema) == schema


def test_sdk_tool_choice_named_dict_uses_required_tool() -> None:
    kwargs = _sdk_chat_kwargs(
        model="grok-4.5",
        temperature=0.7,
        max_tokens=None,
        thought_level=None,
        tool_choice={"name": "get_weather"},
    )
    assert kwargs["tool_choice"].function_name == "get_weather"


def test_build_sdk_messages_parts_tool_role_and_assistant_tool_calls() -> None:
    msgs = _build_sdk_messages(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "what is this?"},
                    {"type": "image_url", "url": "https://example.com/a.png"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc", "detail": "high"}},
                    {"type": "file", "file_id": "file-1"},
                ],
            },
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "c1", "name": "get_weather", "arguments": {"city": "NYC"}},
                ],
            },
            {"role": "tool", "content": "72F", "tool_call_id": "c1"},
        ],
        system_prompt="be brief",
    )
    assert msgs[0].role == chat_pb2.ROLE_SYSTEM
    user_msg = msgs[1]
    assert user_msg.role == chat_pb2.ROLE_USER
    assert user_msg.content[0].text == "what is this?"
    assert user_msg.content[1].image_url.image_url == "https://example.com/a.png"
    assert user_msg.content[2].image_url.image_url == "data:image/png;base64,abc"
    assert user_msg.content[3].file.file_id == "file-1"
    assistant_msg = msgs[2]
    assert assistant_msg.role == chat_pb2.ROLE_ASSISTANT
    assert assistant_msg.tool_calls[0].id == "c1"
    assert assistant_msg.tool_calls[0].function.name == "get_weather"
    assert json.loads(assistant_msg.tool_calls[0].function.arguments) == {"city": "NYC"}
    tool_msg = msgs[3]
    assert tool_msg.role == chat_pb2.ROLE_TOOL
    assert tool_msg.tool_call_id == "c1"
    assert tool_msg.content[0].text == "72F"


def test_sdk_response_format_json_object_and_pydantic() -> None:
    assert _sdk_response_format("json_object") == "json_object"
    assert _sdk_response_format(_Item) is _Item
    openai_style = {
        "type": "json_schema",
        "json_schema": {"name": "item", "schema": {"type": "object"}},
    }
    fmt = _sdk_response_format(openai_style)
    assert fmt.format_type == chat_pb2.FORMAT_TYPE_JSON_SCHEMA
    assert json.loads(fmt.schema) == {"type": "object"}


def test_parse_tool_arguments_blank_stays_string_not_empty_object() -> None:
    assert _parse_tool_arguments(None) == ""
    assert _parse_tool_arguments("") == ""
    assert _parse_tool_arguments("   ") == ""
    assert _parse_tool_arguments("{}") == {}
    assert _parse_tool_arguments('{"city":') == '{"city":'
    assert _parse_tool_arguments({"city": "NYC"}) == {"city": "NYC"}


def test_normalize_incomplete_stream_tool_call_keeps_blank_arguments() -> None:
    out = _normalize_tool_calls(
        [{"id": "c1", "name": "get_weather", "arguments": ""}]
    )
    assert out == [{"id": "c1", "name": "get_weather", "arguments": ""}]
