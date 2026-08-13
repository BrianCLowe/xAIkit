"""Contract tests: TTS voice roster REST wiring (URL, auth, metering)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from xaikit import (
    InMemoryUsageSink,
    MockChatProvider,
    UsageMeter,
    XAI_TTS_VOICES_URL,
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


def _voices_json() -> dict[str, Any]:
    return {
        "voices": [
            {"voice_id": "eve", "name": "Eve", "language": "en"},
            {"voice_id": "ara", "name": "Ara", "language": None},
        ]
    }


class _Capture:
    def __init__(self) -> None:
        self.gets: list[dict[str, Any]] = []

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


def test_list_tts_voices_gets_url_auth_and_returns_voices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    meter = UsageMeter(sink=sink)
    client = _client(usage_meter=meter)
    recorded: list[dict[str, Any]] = []
    orig = client._record

    def _wrap(**kwargs: Any) -> None:
        recorded.append(kwargs)
        orig(**kwargs)

    client._record = _wrap  # type: ignore[method-assign]
    cap = _Capture()
    cap.install_get(
        monkeypatch,
        httpx.Response(
            200,
            json=_voices_json(),
            request=httpx.Request("GET", XAI_TTS_VOICES_URL),
        ),
    )

    voices = client.list_tts_voices(
        purpose="demo.tts.voices",
        parent_id="p1",
        labels={"request_id": "v1"},
    )

    assert voices == _voices_json()["voices"]
    assert len(cap.gets) == 1
    call = cap.gets[0]
    assert call["url"] == XAI_TTS_VOICES_URL
    assert call["headers"]["Authorization"] == "Bearer test-key"
    assert call["timeout"] == 30.0

    ev = list(sink.iter_events())[0]
    assert ev.purpose == "demo.tts.voices"
    assert ev.modality == "tts"
    assert ev.model == "tts"
    assert ev.success is True
    assert ev.parent_id == "p1"
    assert ev.labels["request_id"] == "v1"
    assert ev.estimated_usd is None
    assert recorded[-1]["apply_price_table"] is False


def test_list_tts_voices_empty_or_missing_voices_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install_get(
        monkeypatch,
        httpx.Response(
            200,
            json={},
            request=httpx.Request("GET", XAI_TTS_VOICES_URL),
        ),
    )
    with pytest.raises(RuntimeError, match="voices list"):
        client.list_tts_voices()

    cap.install_get(
        monkeypatch,
        httpx.Response(
            200,
            json={"voices": []},
            request=httpx.Request("GET", XAI_TTS_VOICES_URL),
        ),
    )
    with pytest.raises(RuntimeError, match="voices list"):
        client.list_tts_voices()

    cap.install_get(
        monkeypatch,
        httpx.Response(
            200,
            json={"voices": None},
            request=httpx.Request("GET", XAI_TTS_VOICES_URL),
        ),
    )
    with pytest.raises(RuntimeError, match="voices list"):
        client.list_tts_voices()

    cap.install_get(
        monkeypatch,
        httpx.Response(
            200,
            json={"voices": {"voice_id": "eve"}},
            request=httpx.Request("GET", XAI_TTS_VOICES_URL),
        ),
    )
    with pytest.raises(RuntimeError, match="voices list"):
        client.list_tts_voices()


def test_list_tts_voices_requires_purpose_when_metered() -> None:
    client = _client(usage_meter=UsageMeter(sink=InMemoryUsageSink()))
    with pytest.raises(ValueError, match="purpose"):
        client.list_tts_voices()


def test_list_tts_voices_http_400_records_failed_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    client = _client(usage_meter=UsageMeter(sink=sink))
    cap = _Capture()
    cap.install_get(
        monkeypatch,
        httpx.Response(
            400,
            text="bad request",
            request=httpx.Request("GET", XAI_TTS_VOICES_URL),
        ),
    )
    with pytest.raises(RuntimeError, match="TTS voices failed \\(400\\)"):
        client.list_tts_voices(purpose="demo.tts.voices.http")
    ev = list(sink.iter_events())[0]
    assert ev.success is False
    assert ev.modality == "tts"
    assert ev.model == "tts"
    assert ev.purpose == "demo.tts.voices.http"
    assert ev.estimated_usd is None


def test_list_tts_voices_401_skips_meter(
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
            request=httpx.Request("GET", XAI_TTS_VOICES_URL),
        ),
    )
    with pytest.raises(RuntimeError, match="unauthorized"):
        client.list_tts_voices(purpose="demo.tts.voices.401")
    assert list(sink.iter_events()) == []


def test_list_tts_voices_does_not_call_chat_provider(
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
    cap.install_get(
        monkeypatch,
        httpx.Response(
            200,
            json=_voices_json(),
            request=httpx.Request("GET", XAI_TTS_VOICES_URL),
        ),
    )
    client.list_tts_voices()
    assert provider.calls == []


def test_get_tts_voice_gets_url_auth_and_returns_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    client = _client(usage_meter=UsageMeter(sink=sink))
    cap = _Capture()
    voice = {"voice_id": "eve", "name": "Eve", "language": "en"}
    cap.install_get(
        monkeypatch,
        httpx.Response(
            200,
            json=voice,
            request=httpx.Request("GET", f"{XAI_TTS_VOICES_URL}/eve"),
        ),
    )

    out = client.get_tts_voice("eve", purpose="demo.tts.voice")
    assert out == voice
    assert cap.gets[0]["url"] == f"{XAI_TTS_VOICES_URL}/eve"
    assert cap.gets[0]["headers"]["Authorization"] == "Bearer test-key"
    ev = list(sink.iter_events())[0]
    assert ev.success is True
    assert ev.modality == "tts"
    assert ev.model == "tts"
    assert ev.estimated_usd is None


def test_get_tts_voice_rejects_empty_id_without_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install_get(
        monkeypatch,
        httpx.Response(
            200,
            json={"voice_id": "eve"},
            request=httpx.Request("GET", XAI_TTS_VOICES_URL),
        ),
    )
    with pytest.raises(RuntimeError, match="voice_id is empty"):
        client.get_tts_voice("  ")
    assert cap.gets == []


def test_list_tts_voices_missing_key_skips_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    client.api_key = ""
    cap = _Capture()
    cap.install_get(
        monkeypatch,
        httpx.Response(
            200,
            json=_voices_json(),
            request=httpx.Request("GET", XAI_TTS_VOICES_URL),
        ),
    )
    with pytest.raises(RuntimeError, match="credentials"):
        client.list_tts_voices()
    assert cap.gets == []
