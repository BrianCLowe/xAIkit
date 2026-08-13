"""Contract tests: realtime client-secret mint (URL, auth, JSON body, metering)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from xaikit import (
    InMemoryUsageSink,
    MockChatProvider,
    UsageMeter,
    XAI_REALTIME_CLIENT_SECRETS_URL,
    XaiClient,
    default_retry_policy,
    realtime_client_secret_protocol,
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


def _secret_json(*, value: str = "ek_test_secret") -> dict[str, Any]:
    return {"value": value, "expires_after": {"seconds": 300}}


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


def test_create_realtime_client_secret_posts_auth_body_and_meters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    client = _client(usage_meter=UsageMeter(sink=sink))
    cap = _Capture()
    cap.install_post(
        monkeypatch,
        httpx.Response(
            200,
            json=_secret_json(),
            request=httpx.Request("POST", XAI_REALTIME_CLIENT_SECRETS_URL),
        ),
    )

    out = client.create_realtime_client_secret(
        purpose="demo.realtime.secret",
        parent_id="p1",
        labels={"request_id": "r1"},
    )

    assert out["value"] == "ek_test_secret"
    assert len(cap.posts) == 1
    call = cap.posts[0]
    assert call["url"] == XAI_REALTIME_CLIENT_SECRETS_URL
    assert call["headers"]["Authorization"] == "Bearer test-key"
    assert call["headers"]["Content-Type"] == "application/json"
    assert call["json"] == {"expires_after": {"seconds": 300}}
    assert "session" not in call["json"]
    assert "anchor" not in call["json"]
    assert "anchor" not in call["json"]["expires_after"]
    assert call["timeout"] == 30.0

    ev = list(sink.iter_events())[0]
    assert ev.purpose == "demo.realtime.secret"
    assert ev.modality == "realtime"
    assert ev.success is True
    assert ev.estimated_usd is None
    assert ev.prompt_tokens is None
    assert ev.completion_tokens is None
    assert ev.parent_id == "p1"
    assert ev.labels["request_id"] == "r1"


def test_create_realtime_client_secret_custom_expires_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install_post(
        monkeypatch,
        httpx.Response(
            200,
            json=_secret_json(),
            request=httpx.Request("POST", XAI_REALTIME_CLIENT_SECRETS_URL),
        ),
    )
    client.create_realtime_client_secret(expires_after=60)
    assert cap.posts[0]["json"] == {"expires_after": {"seconds": 60}}
    assert "session" not in cap.posts[0]["json"]


def test_create_realtime_client_secret_returns_upstream_json_as_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    noisy = {"value": "ek_x", "object": "realtime.client_secret", "extra": [1]}
    cap.install_post(
        monkeypatch,
        httpx.Response(
            200,
            json=noisy,
            request=httpx.Request("POST", XAI_REALTIME_CLIENT_SECRETS_URL),
        ),
    )
    assert client.create_realtime_client_secret() == noisy


def test_create_realtime_client_secret_does_not_call_chat_provider(
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
            json=_secret_json(),
            request=httpx.Request("POST", XAI_REALTIME_CLIENT_SECRETS_URL),
        ),
    )
    client.create_realtime_client_secret()
    assert provider.calls == []


@pytest.mark.parametrize("bad", [0, -1, None, ""])
def test_create_realtime_client_secret_rejects_invalid_expires_after_without_http(
    monkeypatch: pytest.MonkeyPatch,
    bad: Any,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install_post(
        monkeypatch,
        httpx.Response(
            200,
            json=_secret_json(),
            request=httpx.Request("POST", XAI_REALTIME_CLIENT_SECRETS_URL),
        ),
    )
    with pytest.raises(ValueError, match="expires_after"):
        client.create_realtime_client_secret(expires_after=bad)
    assert cap.posts == []


def test_create_realtime_client_secret_requires_purpose_when_metered() -> None:
    client = _client(usage_meter=UsageMeter(sink=InMemoryUsageSink()))
    with pytest.raises(ValueError, match="purpose"):
        client.create_realtime_client_secret()


def test_create_realtime_client_secret_missing_credentials_before_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    client.api_key = ""
    cap = _Capture()
    cap.install_post(
        monkeypatch,
        httpx.Response(
            200,
            json=_secret_json(),
            request=httpx.Request("POST", XAI_REALTIME_CLIENT_SECRETS_URL),
        ),
    )
    with pytest.raises(RuntimeError, match="credentials not configured"):
        client.create_realtime_client_secret()
    assert cap.posts == []


def test_create_realtime_client_secret_http_error_records_failed_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    client = _client(usage_meter=UsageMeter(sink=sink))

    def _boom(*_a: Any, **_k: Any) -> httpx.Response:
        raise httpx.ConnectError("offline")

    monkeypatch.setattr("xaikit.client.httpx.post", _boom)
    with pytest.raises(RuntimeError, match="Realtime client secret request failed"):
        client.create_realtime_client_secret(purpose="demo.realtime.secret.fail")

    ev = list(sink.iter_events())[0]
    assert ev.success is False
    assert ev.modality == "realtime"
    assert ev.purpose == "demo.realtime.secret.fail"
    assert ev.estimated_usd is None
    assert ev.prompt_tokens is None


def test_create_realtime_client_secret_unauthorized_skips_meter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    client = _client(usage_meter=UsageMeter(sink=sink))
    cap = _Capture()
    cap.install_post(
        monkeypatch,
        httpx.Response(
            401,
            text="unauthorized",
            request=httpx.Request("POST", XAI_REALTIME_CLIENT_SECRETS_URL),
        ),
    )
    with pytest.raises(RuntimeError, match="unauthorized"):
        client.create_realtime_client_secret(purpose="demo.realtime.secret.401")
    assert list(sink.iter_events()) == []


def test_create_realtime_client_secret_http_status_error_records_failed_usage(
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
            request=httpx.Request("POST", XAI_REALTIME_CLIENT_SECRETS_URL),
        ),
    )
    with pytest.raises(RuntimeError, match="Realtime client secret failed \\(400\\)"):
        client.create_realtime_client_secret(purpose="demo.realtime.secret.http")
    ev = list(sink.iter_events())[0]
    assert ev.success is False
    assert ev.modality == "realtime"
    assert ev.estimated_usd is None
    assert cap.posts[0]["json"] == {"expires_after": {"seconds": 300}}


def test_realtime_client_secret_protocol() -> None:
    assert (
        realtime_client_secret_protocol("ek_test") == "xai-client-secret.ek_test"
    )
    with pytest.raises(ValueError, match="empty"):
        realtime_client_secret_protocol("  ")
