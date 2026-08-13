"""Contract tests: tokenize REST wiring (URL, auth, JSON body, metering)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from xaikit import (
    InMemoryUsageSink,
    MockChatProvider,
    UsageMeter,
    XAI_TOKENIZE_URL,
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


def _tokenize_json(
    *,
    tokens: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rows = tokens if tokens is not None else [
        {"token_id": 1, "string_token": "Hello", "token_bytes": [72]},
        {"token_id": 2, "string_token": " world", "token_bytes": [32, 119]},
    ]
    return {"token_ids": rows}


class _Capture:
    def __init__(self) -> None:
        self.posts: list[dict[str, Any]] = []

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


def test_tokenize_posts_json_with_auth_body_and_meters(
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
            json=_tokenize_json(),
            request=httpx.Request("POST", XAI_TOKENIZE_URL),
        ),
    )

    out = client.tokenize(
        "Hello world",
        model="grok-3",
        purpose="demo.tokenize",
        parent_id="p1",
        labels={"request_id": "t1"},
    )

    assert out["model"] == "grok-3"
    assert out["count"] == 2
    assert out["tokens"][0] == {
        "token_id": 1,
        "string": "Hello",
        "token_bytes": [72],
    }
    assert out["tokens"][1]["token_id"] == 2
    assert out["tokens"][1]["string"] == " world"
    assert len(cap.posts) == 1
    call = cap.posts[0]
    assert call["url"] == XAI_TOKENIZE_URL
    assert call["headers"]["Authorization"] == "Bearer test-key"
    assert call["headers"]["Content-Type"] == "application/json"
    assert call["json"] == {"text": "Hello world", "model": "grok-3"}
    assert call["timeout"] == 60.0

    ev = list(sink.iter_events())[0]
    assert ev.purpose == "demo.tokenize"
    assert ev.modality == "tokenize"
    assert ev.model == "grok-3"
    assert ev.success is True
    assert ev.prompt_tokens == 2
    assert ev.total_tokens == 2
    assert ev.estimated_usd is None
    assert ev.parent_id == "p1"
    assert ev.labels["request_id"] == "t1"


def test_tokenize_defaults_model_to_client_chat_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install_post(
        monkeypatch,
        httpx.Response(
            200,
            json=_tokenize_json(),
            request=httpx.Request("POST", XAI_TOKENIZE_URL),
        ),
    )
    out = client.tokenize("Hello world")
    assert cap.posts[0]["json"]["model"] == "grok-3-mini"
    assert out["model"] == "grok-3-mini"
    assert out["count"] == 2


def test_tokenize_rejects_empty_text_without_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install_post(
        monkeypatch,
        httpx.Response(
            200,
            json=_tokenize_json(),
            request=httpx.Request("POST", XAI_TOKENIZE_URL),
        ),
    )
    with pytest.raises(RuntimeError, match="empty"):
        client.tokenize("   ")
    assert cap.posts == []


def test_tokenize_requires_purpose_when_metered() -> None:
    client = _client(usage_meter=UsageMeter(sink=InMemoryUsageSink()))
    with pytest.raises(ValueError, match="purpose"):
        client.tokenize("hello")


def test_tokenize_http_error_records_failed_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    client = _client(usage_meter=UsageMeter(sink=sink))

    def _boom(*_a: Any, **_k: Any) -> httpx.Response:
        raise httpx.ConnectError("offline")

    monkeypatch.setattr("xaikit.client.httpx.post", _boom)
    with pytest.raises(RuntimeError, match="Tokenize request failed"):
        client.tokenize("hello", purpose="demo.tokenize.fail")

    ev = list(sink.iter_events())[0]
    assert ev.success is False
    assert ev.modality == "tokenize"
    assert ev.purpose == "demo.tokenize.fail"
    assert ev.model == "grok-3-mini"
    assert ev.estimated_usd is None


def test_tokenize_http_status_error_records_failed_usage(
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
            request=httpx.Request("POST", XAI_TOKENIZE_URL),
        ),
    )
    with pytest.raises(RuntimeError, match="Tokenize failed \\(400\\)"):
        client.tokenize("hello", purpose="demo.tokenize.http")
    ev = list(sink.iter_events())[0]
    assert ev.success is False
    assert ev.modality == "tokenize"


def test_tokenize_maps_string_field_from_proto_style_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install_post(
        monkeypatch,
        httpx.Response(
            200,
            json={
                "token_ids": [
                    {"token_id": 9, "string": "Hi", "token_bytes": [72, 105]},
                ]
            },
            request=httpx.Request("POST", XAI_TOKENIZE_URL),
        ),
    )
    out = client.tokenize("Hi")
    assert out["tokens"][0]["string"] == "Hi"
    assert out["count"] == 1
