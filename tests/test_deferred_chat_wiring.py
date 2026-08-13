"""Contract tests: deferred chat REST wiring (URL, auth, 200/202, metering)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from xaikit import (
    InMemoryUsageSink,
    MockChatProvider,
    UsageMeter,
    XAI_CHAT_COMPLETIONS_URL,
    XAI_DEFERRED_CHAT_URL,
    XaiClient,
    default_retry_policy,
)


def _client(*, usage_meter: UsageMeter | None = None, **kwargs: Any) -> XaiClient:
    return XaiClient(
        provider=MockChatProvider(),
        model="grok-3-mini",
        api_key="test-key",
        usage_meter=usage_meter,
        retry_policy=default_retry_policy(max_attempts=1),
        **kwargs,
    )


def _completion_json(
    *,
    request_id: str = "f15c114e-f47d-40ca-8d5c-8c23d656eeb6",
    model: str = "grok-3-mini",
) -> dict[str, Any]:
    return {
        "id": "cmpl_abc",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "42"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 26, "completion_tokens": 8, "total_tokens": 34},
        "request_id": request_id,
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


def test_create_deferred_chat_posts_deferred_true_and_meters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    client = _client(usage_meter=UsageMeter(sink=sink))
    cap = _Capture()
    cap.install_post(
        monkeypatch,
        httpx.Response(
            200,
            json={"request_id": "req_abc123"},
            request=httpx.Request("POST", XAI_CHAT_COMPLETIONS_URL),
        ),
    )
    out = client.create_deferred_chat(
        [{"role": "user", "content": "126/3=?"}],
        purpose="demo.deferred.create",
        parent_id="p1",
        labels={"request_id": "r1"},
        service_tier="priority",
    )
    assert out == {"request_id": "req_abc123"}
    assert len(cap.posts) == 1
    call = cap.posts[0]
    assert call["url"] == XAI_CHAT_COMPLETIONS_URL
    assert call["headers"]["Authorization"] == "Bearer test-key"
    assert call["json"]["deferred"] is True
    assert call["json"]["model"] == "grok-3-mini"
    assert call["json"]["messages"] == [{"role": "user", "content": "126/3=?"}]
    assert call["json"]["service_tier"] == "priority"
    ev = list(sink.iter_events())[0]
    assert ev.purpose == "demo.deferred.create"
    assert ev.modality == "chat"
    assert ev.success is True
    assert ev.prompt_tokens is None
    assert ev.completion_tokens is None
    assert ev.estimated_usd is None
    assert ev.parent_id == "p1"
    assert ev.labels["request_id"] == "r1"


def test_create_deferred_chat_does_not_call_chat_provider(
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
            json={"request_id": "req_abc123"},
            request=httpx.Request("POST", XAI_CHAT_COMPLETIONS_URL),
        ),
    )
    client.create_deferred_chat([{"role": "user", "content": "hi"}])
    assert provider.calls == []


def test_create_deferred_chat_rejects_empty_messages_without_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install_post(
        monkeypatch,
        httpx.Response(
            200,
            json={"request_id": "req_abc123"},
            request=httpx.Request("POST", XAI_CHAT_COMPLETIONS_URL),
        ),
    )
    with pytest.raises(RuntimeError, match="empty"):
        client.create_deferred_chat([])
    assert cap.posts == []


def test_create_deferred_chat_requires_purpose_when_metered() -> None:
    client = _client(usage_meter=UsageMeter(sink=InMemoryUsageSink()))
    with pytest.raises(ValueError, match="purpose"):
        client.create_deferred_chat([{"role": "user", "content": "hi"}])


def test_get_deferred_chat_200_complete_and_meters_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    client = _client(usage_meter=UsageMeter(sink=sink))
    cap = _Capture()
    request_id = "req_abc123"
    url = f"{XAI_DEFERRED_CHAT_URL}/{request_id}"
    cap.install_get(
        monkeypatch,
        httpx.Response(
            200,
            json=_completion_json(),
            request=httpx.Request("GET", url),
        ),
    )
    out = client.get_deferred_chat(request_id, purpose="demo.deferred.get")
    assert out["status"] == "complete"
    assert out["choices"][0]["message"]["content"] == "42"
    assert cap.gets[0]["url"] == url
    assert cap.gets[0]["headers"]["Authorization"] == "Bearer test-key"
    ev = list(sink.iter_events())[0]
    assert ev.purpose == "demo.deferred.get"
    assert ev.modality == "chat"
    assert ev.success is True
    assert ev.prompt_tokens == 26
    assert ev.completion_tokens == 8
    assert ev.estimated_usd is None


def test_get_deferred_chat_202_pending_meters_without_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    client = _client(usage_meter=UsageMeter(sink=sink))
    cap = _Capture()
    request_id = "req_abc123"
    url = f"{XAI_DEFERRED_CHAT_URL}/{request_id}"
    cap.install_get(
        monkeypatch,
        httpx.Response(
            202,
            content=b"",
            request=httpx.Request("GET", url),
        ),
    )
    out = client.get_deferred_chat(request_id, purpose="demo.deferred.pending")
    assert out == {"status": "pending"}
    assert cap.gets[0]["url"] == url
    ev = list(sink.iter_events())[0]
    assert ev.purpose == "demo.deferred.pending"
    assert ev.modality == "chat"
    assert ev.success is True
    assert ev.prompt_tokens is None
    assert ev.completion_tokens is None
    assert ev.estimated_usd is None


def test_get_deferred_chat_rejects_empty_id_without_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install_get(
        monkeypatch,
        httpx.Response(
            200,
            json=_completion_json(),
            request=httpx.Request("GET", XAI_DEFERRED_CHAT_URL),
        ),
    )
    with pytest.raises(RuntimeError, match="empty"):
        client.get_deferred_chat("  ")
    assert cap.gets == []


def test_get_deferred_chat_requires_purpose_when_metered() -> None:
    client = _client(usage_meter=UsageMeter(sink=InMemoryUsageSink()))
    with pytest.raises(ValueError, match="purpose"):
        client.get_deferred_chat("req_abc123")


def test_get_deferred_chat_401_skips_meter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    client = _client(usage_meter=UsageMeter(sink=sink))
    cap = _Capture()
    cap.install_get(
        monkeypatch,
        httpx.Response(
            401,
            text="unauthorized",
            request=httpx.Request("GET", f"{XAI_DEFERRED_CHAT_URL}/req_abc123"),
        ),
    )
    with pytest.raises(RuntimeError, match="unauthorized"):
        client.get_deferred_chat("req_abc123", purpose="demo.deferred.401")
    assert list(sink.iter_events()) == []


def test_create_deferred_chat_http_error_records_failed_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    client = _client(usage_meter=UsageMeter(sink=sink))

    def _boom(*_a: Any, **_k: Any) -> httpx.Response:
        raise httpx.ConnectError("offline")

    monkeypatch.setattr("xaikit.client.httpx.post", _boom)
    with pytest.raises(RuntimeError, match="Deferred chat request failed"):
        client.create_deferred_chat(
            [{"role": "user", "content": "hi"}],
            purpose="demo.deferred.fail",
        )
    ev = list(sink.iter_events())[0]
    assert ev.success is False
    assert ev.modality == "chat"
    assert ev.purpose == "demo.deferred.fail"
    assert ev.estimated_usd is None
