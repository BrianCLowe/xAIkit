"""Contract tests: Responses REST wiring (URL, auth, JSON body, metering)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from xaikit import (
    InMemoryUsageSink,
    MockChatProvider,
    UsageMeter,
    XAI_RESPONSES_URL,
    XaiClient,
    default_retry_policy,
)
from xaikit.client import XAI_RESPONSES_MAX_TOOLS


def _client(*, usage_meter: UsageMeter | None = None, **kwargs: Any) -> XaiClient:
    return XaiClient(
        provider=MockChatProvider(),
        model="grok-3-mini",
        api_key="test-key",
        usage_meter=usage_meter,
        retry_policy=default_retry_policy(max_attempts=1),
        **kwargs,
    )


def _response_json(
    *,
    response_id: str = "resp_abc123",
    model: str = "grok-3-mini",
    text: str = "303",
) -> dict[str, Any]:
    return {
        "id": response_id,
        "object": "response",
        "model": model,
        "status": "completed",
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            }
        ],
        "tools": [],
        "usage": {
            "input_tokens": 32,
            "output_tokens": 9,
            "total_tokens": 41,
        },
    }


class _Capture:
    def __init__(self) -> None:
        self.posts: list[dict[str, Any]] = []
        self.gets: list[dict[str, Any]] = []

    def install_post(
        self, monkeypatch: pytest.MonkeyPatch, response: httpx.Response
    ) -> None:
        def _post(url: str, **kwargs: Any) -> httpx.Response:
            self.posts.append({"url": url, **kwargs})
            if response.request is not None:
                return response
            return httpx.Response(
                response.status_code,
                headers=response.headers,
                content=response.content,
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr("xaikit.client.httpx.post", _post)

    def install_get(
        self, monkeypatch: pytest.MonkeyPatch, response: httpx.Response
    ) -> None:
        def _get(url: str, **kwargs: Any) -> httpx.Response:
            self.gets.append({"url": url, **kwargs})
            if response.request is not None:
                return response
            return httpx.Response(
                response.status_code,
                headers=response.headers,
                content=response.content,
                request=httpx.Request("GET", url),
            )

        monkeypatch.setattr("xaikit.client.httpx.get", _get)


def test_create_response_posts_json_with_auth_body_and_meters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    meter = UsageMeter(sink=sink)
    client = _client(usage_meter=meter)
    cap = _Capture()
    cap.install_post(
        monkeypatch,
        httpx.Response(
            200,
            json=_response_json(),
            request=httpx.Request("POST", XAI_RESPONSES_URL),
        ),
    )

    out = client.create_response(
        "What is 101*3?",
        purpose="demo.responses",
        parent_id="p1",
        labels={"request_id": "r1"},
    )

    assert out["id"] == "resp_abc123"
    assert out["object"] == "response"
    assert out["output"][0]["content"][0]["text"] == "303"
    assert out["usage"]["input_tokens"] == 32
    assert len(cap.posts) == 1
    call = cap.posts[0]
    assert call["url"] == XAI_RESPONSES_URL
    assert call["headers"]["Authorization"] == "Bearer test-key"
    assert call["headers"]["Content-Type"] == "application/json"
    assert call["json"] == {
        "model": "grok-3-mini",
        "input": "What is 101*3?",
    }
    assert "tools" not in call["json"]
    assert call["timeout"] == 120.0

    ev = list(sink.iter_events())[0]
    assert ev.purpose == "demo.responses"
    assert ev.modality == "responses"
    assert ev.model == "grok-3-mini"
    assert ev.success is True
    assert ev.prompt_tokens == 32
    assert ev.completion_tokens == 9
    assert ev.estimated_usd is None
    assert ev.parent_id == "p1"
    assert ev.labels["request_id"] == "r1"


def test_create_response_does_not_call_chat_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = MockChatProvider()
    client = XaiClient(
        provider=provider,
        model="grok-3-mini",
        api_key="test-key",
        retry_policy=default_retry_policy(max_attempts=1),
    )
    cap = _Capture()
    cap.install_post(
        monkeypatch,
        httpx.Response(
            200,
            json=_response_json(),
            request=httpx.Request("POST", XAI_RESPONSES_URL),
        ),
    )
    client.create_response("hello")
    assert provider.calls == []


def test_create_response_sends_opt_in_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install_post(
        monkeypatch,
        httpx.Response(
            200,
            json=_response_json(),
            request=httpx.Request("POST", XAI_RESPONSES_URL),
        ),
    )
    tools = [
        {"type": "web_search"},
        {"type": "x_search"},
        {"type": "code_interpreter"},
        {"type": "file_search", "vector_store_ids": ["col_1"]},
        {"type": "image_generation"},
    ]
    client.create_response("latest news", tools=tools)
    assert cap.posts[0]["json"]["tools"] == tools


def test_create_response_list_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install_post(
        monkeypatch,
        httpx.Response(
            200,
            json=_response_json(),
            request=httpx.Request("POST", XAI_RESPONSES_URL),
        ),
    )
    messages = [{"role": "user", "content": "What is 101*3?"}]
    client.create_response(messages, model="grok-4.5")
    assert cap.posts[0]["json"] == {
        "model": "grok-4.5",
        "input": messages,
    }


def test_create_response_rejects_empty_string_without_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install_post(
        monkeypatch,
        httpx.Response(
            200,
            json=_response_json(),
            request=httpx.Request("POST", XAI_RESPONSES_URL),
        ),
    )
    with pytest.raises(RuntimeError, match="empty"):
        client.create_response("   ")
    assert cap.posts == []


def test_create_response_rejects_empty_list_without_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install_post(
        monkeypatch,
        httpx.Response(
            200,
            json=_response_json(),
            request=httpx.Request("POST", XAI_RESPONSES_URL),
        ),
    )
    with pytest.raises(RuntimeError, match="empty"):
        client.create_response([])
    assert cap.posts == []


def test_create_response_rejects_oversized_tools_without_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install_post(
        monkeypatch,
        httpx.Response(
            200,
            json=_response_json(),
            request=httpx.Request("POST", XAI_RESPONSES_URL),
        ),
    )
    with pytest.raises(RuntimeError, match="128"):
        client.create_response(
            "hi",
            tools=[{"type": "web_search"}] * (XAI_RESPONSES_MAX_TOOLS + 1),
        )
    assert cap.posts == []


def test_create_response_requires_purpose_when_metered() -> None:
    client = _client(usage_meter=UsageMeter(sink=InMemoryUsageSink()))
    with pytest.raises(ValueError, match="purpose"):
        client.create_response("hello")


def test_create_response_http_error_records_failed_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    client = _client(usage_meter=UsageMeter(sink=sink))

    def _boom(*_a: Any, **_k: Any) -> httpx.Response:
        raise httpx.ConnectError("offline")

    monkeypatch.setattr("xaikit.client.httpx.post", _boom)
    with pytest.raises(RuntimeError, match="Responses request failed"):
        client.create_response("hello", purpose="demo.responses.fail")

    ev = list(sink.iter_events())[0]
    assert ev.success is False
    assert ev.modality == "responses"
    assert ev.purpose == "demo.responses.fail"
    assert ev.model == "grok-3-mini"
    assert ev.estimated_usd is None


def test_create_response_http_status_error_records_failed_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    client = _client(usage_meter=UsageMeter(sink=sink))
    cap = _Capture()
    cap.install_post(
        monkeypatch,
        httpx.Response(
            400,
            text="bad request",
            request=httpx.Request("POST", XAI_RESPONSES_URL),
        ),
    )
    with pytest.raises(RuntimeError, match="Responses failed \\(400\\)"):
        client.create_response("hello", purpose="demo.responses.http")
    ev = list(sink.iter_events())[0]
    assert ev.success is False
    assert ev.modality == "responses"


def test_get_response_gets_by_id_and_meters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    client = _client(usage_meter=UsageMeter(sink=sink))
    cap = _Capture()
    url = f"{XAI_RESPONSES_URL}/resp_abc123"
    cap.install_get(
        monkeypatch,
        httpx.Response(
            200,
            json=_response_json(),
            request=httpx.Request("GET", url),
        ),
    )
    out = client.get_response("resp_abc123", purpose="demo.responses.get")
    assert out["id"] == "resp_abc123"
    assert len(cap.gets) == 1
    call = cap.gets[0]
    assert call["url"] == url
    assert call["headers"]["Authorization"] == "Bearer test-key"
    ev = list(sink.iter_events())[0]
    assert ev.purpose == "demo.responses.get"
    assert ev.modality == "responses"
    assert ev.success is True
    assert ev.estimated_usd is None
    assert ev.prompt_tokens is None
    assert ev.completion_tokens is None


def test_get_response_rejects_empty_id_without_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install_get(
        monkeypatch,
        httpx.Response(
            200,
            json=_response_json(),
            request=httpx.Request("GET", XAI_RESPONSES_URL),
        ),
    )
    with pytest.raises(RuntimeError, match="empty"):
        client.get_response("  ")
    assert cap.gets == []


def test_get_response_requires_purpose_when_metered() -> None:
    client = _client(usage_meter=UsageMeter(sink=InMemoryUsageSink()))
    with pytest.raises(ValueError, match="purpose"):
        client.get_response("resp_abc123")
