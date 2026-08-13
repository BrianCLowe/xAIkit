"""Contract tests: embeddings REST wiring (URL, auth, JSON body, metering)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from xaikit import (
    InMemoryUsageSink,
    MockChatProvider,
    UsageMeter,
    XAI_EMBEDDINGS_URL,
    XaiClient,
    default_retry_policy,
)
from xaikit.client import XAI_EMBED_MAX_INPUTS


def _client(*, usage_meter: UsageMeter | None = None, **kwargs: Any) -> XaiClient:
    return XaiClient(
        provider=MockChatProvider(),
        model="grok-3-mini",
        api_key="test-key",
        usage_meter=usage_meter,
        retry_policy=default_retry_policy(max_attempts=1),
        **kwargs,
    )


def _embed_json(
    *,
    model: str = "v1",
    vectors: list[list[float]] | None = None,
) -> dict[str, Any]:
    rows = vectors if vectors is not None else [[0.1, 0.2, 0.3]]
    return {
        "object": "list",
        "model": model,
        "data": [
            {"index": i, "embedding": vec, "object": "embedding"}
            for i, vec in enumerate(rows)
        ],
        "usage": {"prompt_tokens": 1, "total_tokens": 1},
    }


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


def test_embed_posts_json_with_auth_body_and_meters(
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
            json=_embed_json(),
            request=httpx.Request("POST", XAI_EMBEDDINGS_URL),
        ),
    )

    out = client.embed(
        ["query: hello", "passage: world"],
        model="v1",
        purpose="demo.embed",
        parent_id="p1",
        labels={"request_id": "e1"},
    )

    assert out["model"] == "v1"
    assert out["object"] == "list"
    assert out["data"][0]["index"] == 0
    assert out["data"][0]["embedding"] == [0.1, 0.2, 0.3]
    assert out["usage"] == {"prompt_tokens": 1, "total_tokens": 1}
    assert len(cap.posts) == 1
    call = cap.posts[0]
    assert call["url"] == XAI_EMBEDDINGS_URL
    assert call["headers"]["Authorization"] == "Bearer test-key"
    assert call["headers"]["Content-Type"] == "application/json"
    assert call["json"] == {
        "model": "v1",
        "input": ["query: hello", "passage: world"],
    }
    assert call["timeout"] == 120.0

    ev = list(sink.iter_events())[0]
    assert ev.purpose == "demo.embed"
    assert ev.modality == "embed"
    assert ev.model == "v1"
    assert ev.success is True
    assert ev.prompt_tokens == 1
    assert ev.estimated_usd is None
    assert ev.parent_id == "p1"
    assert ev.labels["request_id"] == "e1"


def test_embed_single_string_sends_string_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install_post(
        monkeypatch,
        httpx.Response(
            200,
            json=_embed_json(),
            request=httpx.Request("POST", XAI_EMBEDDINGS_URL),
        ),
    )
    client.embed("query: hello", model="v1")
    assert cap.posts[0]["json"]["input"] == "query: hello"


def test_embed_rejects_empty_string_without_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install_post(
        monkeypatch,
        httpx.Response(
            200,
            json=_embed_json(),
            request=httpx.Request("POST", XAI_EMBEDDINGS_URL),
        ),
    )
    with pytest.raises(RuntimeError, match="empty"):
        client.embed("   ", model="v1")
    assert cap.posts == []


def test_embed_rejects_empty_list_without_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install_post(
        monkeypatch,
        httpx.Response(
            200,
            json=_embed_json(),
            request=httpx.Request("POST", XAI_EMBEDDINGS_URL),
        ),
    )
    with pytest.raises(RuntimeError, match="empty"):
        client.embed([], model="v1")
    assert cap.posts == []


def test_embed_rejects_blank_list_item_without_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install_post(
        monkeypatch,
        httpx.Response(
            200,
            json=_embed_json(),
            request=httpx.Request("POST", XAI_EMBEDDINGS_URL),
        ),
    )
    with pytest.raises(RuntimeError, match="empty"):
        client.embed(["ok", "  "], model="v1")
    assert cap.posts == []


def test_embed_rejects_oversized_list_without_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install_post(
        monkeypatch,
        httpx.Response(
            200,
            json=_embed_json(),
            request=httpx.Request("POST", XAI_EMBEDDINGS_URL),
        ),
    )
    with pytest.raises(RuntimeError, match="128"):
        client.embed(["x"] * (XAI_EMBED_MAX_INPUTS + 1), model="v1")
    assert cap.posts == []


def test_embed_requires_model() -> None:
    client = _client()
    with pytest.raises(RuntimeError, match="model is required"):
        client.embed("hello", model="  ")


def test_embed_requires_purpose_when_metered() -> None:
    client = _client(usage_meter=UsageMeter(sink=InMemoryUsageSink()))
    with pytest.raises(ValueError, match="purpose"):
        client.embed("hello", model="v1")


def test_embed_http_error_records_failed_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    client = _client(usage_meter=UsageMeter(sink=sink))

    def _boom(*_a: Any, **_k: Any) -> httpx.Response:
        raise httpx.ConnectError("offline")

    monkeypatch.setattr("xaikit.client.httpx.post", _boom)
    with pytest.raises(RuntimeError, match="Embeddings request failed"):
        client.embed("hello", model="v1", purpose="demo.embed.fail")

    ev = list(sink.iter_events())[0]
    assert ev.success is False
    assert ev.modality == "embed"
    assert ev.purpose == "demo.embed.fail"
    assert ev.model == "v1"
    assert ev.estimated_usd is None


def test_embed_http_status_error_records_failed_usage(
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
            request=httpx.Request("POST", XAI_EMBEDDINGS_URL),
        ),
    )
    with pytest.raises(RuntimeError, match="Embeddings failed \\(400\\)"):
        client.embed("hello", model="v1", purpose="demo.embed.http")
    ev = list(sink.iter_events())[0]
    assert ev.success is False
    assert ev.modality == "embed"
