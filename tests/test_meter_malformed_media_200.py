"""Malformed HTTP 200 from STT, REST TTS, and the TTS voice roster.

CUT-2026-10-15-xk-malformed-200-metering. MM-AC-1 and MM-AC-2.
Follows the imagine/video precedent in test_meter_unparseable_success.py.

HTTP is mocked in process. ``inject_catalog(static_fallback_models())``
keeps resolve off catalog gRPC. A socket guard allows loopback only.

Cases:
MM-C01 test_mm_c01_sync_stt_non_json
MM-C02 test_mm_c02_async_stt_non_json
MM-C03 test_mm_c03_sync_stt_missing_text
MM-C04 test_mm_c04_async_stt_missing_text
MM-C05 test_mm_c05_sync_tts_empty_audio
MM-C06 test_mm_c06_async_tts_empty_audio
MM-C07 test_mm_c07_roster_non_json_and_missing_list
MM-C07b test_mm_c07b_roster_entries_are_not_voice_objects
MM-C08 test_mm_c08_sync_get_tts_voice_non_json
MM-C09 test_mm_c09_async_get_tts_voice_non_json
MM-C10 test_mm_c10_sync_get_tts_voice_unexpected
MM-C11 test_mm_c11_async_get_tts_voice_unexpected
MM-C12 test_mm_c12_http_401_records_nothing
MM-C13 test_mm_c13_success_records_one_event
MM-C14 test_mm_c14_stt_413_records_nothing
MM-C15 test_mm_c15_http_500_records_http500_once
MM-C16 test_mm_c16_transport_error_unchanged
"""

from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest

from xaikit import (
    AsyncXaiClient,
    InMemoryUsageSink,
    MockChatProvider,
    UsageMeter,
    XAI_STT_URL,
    XAI_TTS_URL,
    XAI_TTS_VOICES_URL,
    XaiClient,
    default_retry_policy,
)
from xaikit.catalog import inject_catalog, static_fallback_models

_PARENT = "p1"
_LABELS = {"request_id": "v1"}
_STT_NON_JSON = "STT returned non-JSON response"
_STT_MISSING = "STT response missing text field"
_TTS_EMPTY = "TTS returned empty audio"
_ROSTER_NON_JSON = "TTS voices returned non-JSON response"
_ROSTER_MISSING = "TTS voices response missing voices list"
_VOICE_NON_JSON = "TTS voice returned non-JSON response"
_VOICE_UNEXPECTED = "TTS voice returned unexpected payload"
_VOICE_URL = f"{XAI_TTS_VOICES_URL}/eve"
_HTTP500 = "HTTP500"
_STT_413 = "Audio file too large for STT"
_TRANSPORT_ERROR = "ConnectError: offline"

# JSON values that are not an object with text. None is encoded as JSON null.
_STT_BAD_BODIES = [
    pytest.param({}, id="empty-object"),
    pytest.param({"text": None}, id="null-text"),
    pytest.param({"transcript": "hi"}, id="wrong-field"),
    pytest.param([], id="list"),
    pytest.param("hello", id="string"),
    pytest.param(0, id="number"),
    pytest.param(None, id="null"),
    pytest.param(True, id="bool"),
]

_ROSTER_MISSING_BODIES = [
    pytest.param({}, id="empty-object"),
    pytest.param({"voices": []}, id="empty-list"),
    pytest.param({"voices": None}, id="null-voices"),
    pytest.param({"voices": {"voice_id": "eve"}}, id="voices-object"),
    pytest.param([], id="list"),
    pytest.param("nope", id="string"),
    pytest.param(0, id="number"),
    pytest.param(None, id="null"),
    pytest.param(True, id="bool"),
]

_ROSTER_BAD_ENTRIES = [
    pytest.param({"voices": [1, 2]}, id="ints"),
    pytest.param({"voices": ["eve"]}, id="strings"),
    pytest.param({"voices": [None]}, id="null-entry"),
    pytest.param({"voices": [{}]}, id="empty-object"),
    pytest.param({"voices": [{"name": "Eve"}]}, id="missing-voice-id"),
    pytest.param({"voices": [{"voice_id": ""}]}, id="blank-voice-id"),
    pytest.param({"voices": [{"voice_id": "   "}]}, id="whitespace-voice-id"),
    pytest.param({"voices": [{"voice_id": 1}]}, id="numeric-voice-id"),
    pytest.param({"voices": [{"voice_id": "eve"}, 2]}, id="mixed"),
]

_VOICE_BAD_BODIES = [
    pytest.param([], id="list"),
    pytest.param("eve", id="string"),
    pytest.param(0, id="number"),
    pytest.param(None, id="null"),
    pytest.param(True, id="bool"),
]

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}
_CONNECT_VIOLATIONS: list[str] = []


def _host_of(address: Any) -> str:
    if isinstance(address, tuple) and address:
        return str(address[0])
    return str(address)


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Inject the static catalog and refuse non-loopback sockets."""
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("XAI_MANAGEMENT_KEY", raising=False)
    inject_catalog(None)
    inject_catalog(list(static_fallback_models()))
    monkeypatch.setattr(
        "xaikit.pricing.fetch_public_price_payload",
        lambda *_args, **_kwargs: None,
    )
    _CONNECT_VIOLATIONS.clear()

    def _check(address: Any) -> None:
        host = _host_of(address)
        if host in _LOOPBACK:
            return
        _CONNECT_VIOLATIONS.append(host)
        raise AssertionError(f"non-loopback connection to {host}")

    orig_connect = socket.socket.connect
    orig_connect_ex = socket.socket.connect_ex

    def connect(self, address):  # type: ignore[no-untyped-def]
        _check(address)
        return orig_connect(self, address)

    def connect_ex(self, address):  # type: ignore[no-untyped-def]
        _check(address)
        return orig_connect_ex(self, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    yield
    inject_catalog(None)
    assert _CONNECT_VIOLATIONS == []


def _sync_client(sink: InMemoryUsageSink) -> XaiClient:
    return XaiClient(
        provider=MockChatProvider(),
        model="grok-3-mini",
        api_key="test-key",
        usage_meter=UsageMeter(sink=sink),
        retry_policy=default_retry_policy(max_attempts=1),
    )


def _async_client(sink: InMemoryUsageSink) -> AsyncXaiClient:
    return AsyncXaiClient(
        provider=MockChatProvider(),
        model="grok-3-mini",
        api_key="test-key",
        usage_meter=UsageMeter(sink=sink),
        retry_policy=default_retry_policy(max_attempts=1, backoff_seconds=0.0),
    )


def _spy(client: XaiClient) -> list[dict[str, Any]]:
    recorded: list[dict[str, Any]] = []
    orig = client._record

    def _wrap(**kwargs: Any) -> None:
        recorded.append(kwargs)
        orig(**kwargs)

    client._record = _wrap  # type: ignore[method-assign]
    return recorded


def _response(
    status_code: int,
    *,
    method: str,
    url: str,
    payload: Any = None,
    content: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    kwargs: dict[str, Any] = {
        "status_code": status_code,
        "request": httpx.Request(method, url),
    }
    if headers is not None:
        kwargs["headers"] = headers
    if content is not None:
        kwargs["content"] = content
    else:
        kwargs["json"] = payload
    return httpx.Response(**kwargs)


def _json_response(method: str, url: str, body: Any) -> httpx.Response:
    if body is None:
        return _response(200, method=method, url=url, content=b"null")
    return _response(200, method=method, url=url, payload=body)


def _install_sync(
    monkeypatch: pytest.MonkeyPatch, response: httpx.Response, *, method: str
) -> None:
    def _call(url: str, **kwargs: Any) -> httpx.Response:
        if response.request is not None:
            return response
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            content=response.content,
            request=httpx.Request(method, url),
        )

    monkeypatch.setattr(f"xaikit.client.httpx.{method}", _call)


def _install_sync_raise(
    monkeypatch: pytest.MonkeyPatch, *, method: str, exc_type: type[BaseException]
) -> None:
    def _call(url: str, **kwargs: Any) -> httpx.Response:
        raise exc_type("offline")

    monkeypatch.setattr(f"xaikit.client.httpx.{method}", _call)


def _install_async(monkeypatch: pytest.MonkeyPatch, response: httpx.Response) -> None:
    class FakeAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> FakeAsyncClient:
            return self

        async def __aexit__(self, *args: Any) -> bool:
            return False

        async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
            if response.request is not None:
                return response
            return httpx.Response(
                response.status_code,
                headers=response.headers,
                content=response.content,
                request=httpx.Request(method, url),
            )

    monkeypatch.setattr("xaikit.async_client.httpx.AsyncClient", FakeAsyncClient)


def _install_async_raise(
    monkeypatch: pytest.MonkeyPatch, exc_type: type[BaseException]
) -> None:
    class FakeAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> FakeAsyncClient:
            return self

        async def __aexit__(self, *args: Any) -> bool:
            return False

        async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
            raise exc_type("offline")

    monkeypatch.setattr("xaikit.async_client.httpx.AsyncClient", FakeAsyncClient)


def _one_failed(
    sink: InMemoryUsageSink,
    recorded: list[dict[str, Any]],
    *,
    raised: BaseException,
    modality: str,
    model: str,
    purpose: str,
    apply_price_table: bool | None,
) -> None:
    events = list(sink.iter_events())
    assert len(events) == 1, f"expected 1 failed event, recorded {len(events)}"
    ev = events[0]
    assert ev.success is False
    assert ev.error == str(raised)
    assert ev.modality == modality
    assert ev.model == model
    assert ev.purpose == purpose
    assert ev.parent_id == _PARENT
    assert ev.labels == _LABELS
    assert ev.estimated_usd is None
    assert len(recorded) == 1, f"expected 1 _record call, saw {len(recorded)}"
    call = recorded[0]
    assert call["success"] is False
    assert call["error"] == str(raised)
    assert call["purpose"] == purpose
    assert call["parent_id"] == _PARENT
    assert call["labels"] == _LABELS
    assert call["modality"] == modality
    assert call["model"] == model
    assert call["usage"] is None
    assert call["thought_level"] is None
    if apply_price_table is None:
        assert "apply_price_table" not in call
    else:
        assert call["apply_price_table"] is apply_price_table


def _one_success(
    sink: InMemoryUsageSink,
    recorded: list[dict[str, Any]],
    *,
    modality: str,
    model: str,
    purpose: str,
    apply_price_table: bool | None,
) -> None:
    events = list(sink.iter_events())
    assert len(events) == 1, f"expected 1 success event, recorded {len(events)}"
    ev = events[0]
    assert ev.success is True
    assert ev.error is None
    assert ev.modality == modality
    assert ev.model == model
    assert ev.purpose == purpose
    assert ev.parent_id == _PARENT
    assert ev.labels == _LABELS
    assert ev.estimated_usd is None
    assert len(recorded) == 1
    call = recorded[0]
    assert call["success"] is True
    assert call.get("error") is None
    assert call["modality"] == modality
    assert call["model"] == model
    if apply_price_table is None:
        assert "apply_price_table" not in call
    else:
        assert call["apply_price_table"] is apply_price_table


def _zero_events(sink: InMemoryUsageSink, recorded: list[dict[str, Any]]) -> None:
    assert list(sink.iter_events()) == []
    assert recorded == []


def _transcribe(client: XaiClient, purpose: str) -> str:
    return client.transcribe(
        b"fake-audio",
        purpose=purpose,
        parent_id=_PARENT,
        labels=_LABELS,
    )


def _synthesize(client: XaiClient, purpose: str) -> tuple[bytes, str]:
    return client.synthesize_speech(
        "hello",
        purpose=purpose,
        parent_id=_PARENT,
        labels=_LABELS,
    )


def _list_voices(client: XaiClient, purpose: str) -> list[dict[str, Any]]:
    return client.list_tts_voices(
        purpose=purpose,
        parent_id=_PARENT,
        labels=_LABELS,
    )


def _get_voice(client: XaiClient, purpose: str) -> dict[str, Any]:
    return client.get_tts_voice(
        "eve",
        purpose=purpose,
        parent_id=_PARENT,
        labels=_LABELS,
    )


def _expect_sync(
    monkeypatch: pytest.MonkeyPatch,
    *,
    response: httpx.Response,
    method: str,
    purpose: str,
    message: str,
    modality: str,
    model: str,
    call: Callable[[XaiClient, str], Any],
    json_cause: bool,
    apply_price_table: bool | None,
) -> None:
    sink = InMemoryUsageSink()
    client = _sync_client(sink)
    recorded = _spy(client)
    _install_sync(monkeypatch, response, method=method)
    with pytest.raises(RuntimeError, match=rf"^{message}$") as raised:
        call(client, purpose)
    assert str(raised.value) == message
    if json_cause:
        assert isinstance(raised.value.__cause__, json.JSONDecodeError)
    else:
        assert raised.value.__cause__ is None
    _one_failed(
        sink,
        recorded,
        raised=raised.value,
        modality=modality,
        model=model,
        purpose=purpose,
        apply_price_table=apply_price_table,
    )


async def _expect_async(
    monkeypatch: pytest.MonkeyPatch,
    *,
    response: httpx.Response,
    purpose: str,
    message: str,
    modality: str,
    model: str,
    call: Callable[[AsyncXaiClient, str], Any],
    json_cause: bool,
    apply_price_table: bool | None,
) -> None:
    sink = InMemoryUsageSink()
    client = _async_client(sink)
    recorded = _spy(client)
    _install_async(monkeypatch, response)
    with pytest.raises(RuntimeError, match=rf"^{message}$") as raised:
        await call(client, purpose)
    assert str(raised.value) == message
    if json_cause:
        assert isinstance(raised.value.__cause__, json.JSONDecodeError)
    else:
        assert raised.value.__cause__ is None
    _one_failed(
        sink,
        recorded,
        raised=raised.value,
        modality=modality,
        model=model,
        purpose=purpose,
        apply_price_table=apply_price_table,
    )


def _run_async(coro: Any) -> None:
    asyncio.run(coro)


def test_mm_c01_sync_stt_non_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _expect_sync(
        monkeypatch,
        response=_response(200, method="POST", url=XAI_STT_URL, content=b"not-json"),
        method="post",
        purpose="demo.stt.nonjson",
        message=_STT_NON_JSON,
        modality="stt",
        model="stt",
        call=_transcribe,
        json_cause=True,
        apply_price_table=None,
    )


def test_mm_c02_async_stt_non_json(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _call(client: AsyncXaiClient, purpose: str) -> str:
        return await client.transcribe(
            b"fake-audio",
            purpose=purpose,
            parent_id=_PARENT,
            labels=_LABELS,
        )

    _run_async(
        _expect_async(
            monkeypatch,
            response=_response(200, method="POST", url=XAI_STT_URL, content=b"not-json"),
            purpose="demo.stt.nonjson",
            message=_STT_NON_JSON,
            modality="stt",
            model="stt",
            call=_call,
            json_cause=True,
            apply_price_table=None,
        )
    )


@pytest.mark.parametrize("body", _STT_BAD_BODIES)
def test_mm_c03_sync_stt_missing_text(
    monkeypatch: pytest.MonkeyPatch, body: Any
) -> None:
    _expect_sync(
        monkeypatch,
        response=_json_response("POST", XAI_STT_URL, body),
        method="post",
        purpose="demo.stt.missing",
        message=_STT_MISSING,
        modality="stt",
        model="stt",
        call=_transcribe,
        json_cause=False,
        apply_price_table=None,
    )


@pytest.mark.parametrize("body", _STT_BAD_BODIES)
def test_mm_c04_async_stt_missing_text(
    monkeypatch: pytest.MonkeyPatch, body: Any
) -> None:
    async def _call(client: AsyncXaiClient, purpose: str) -> str:
        return await client.transcribe(
            b"fake-audio",
            purpose=purpose,
            parent_id=_PARENT,
            labels=_LABELS,
        )

    _run_async(
        _expect_async(
            monkeypatch,
            response=_json_response("POST", XAI_STT_URL, body),
            purpose="demo.stt.missing",
            message=_STT_MISSING,
            modality="stt",
            model="stt",
            call=_call,
            json_cause=False,
            apply_price_table=None,
        )
    )


def test_mm_c05_sync_tts_empty_audio(monkeypatch: pytest.MonkeyPatch) -> None:
    _expect_sync(
        monkeypatch,
        response=_response(
            200,
            method="POST",
            url=XAI_TTS_URL,
            content=b"",
            headers={"content-type": "audio/mpeg"},
        ),
        method="post",
        purpose="demo.tts.empty",
        message=_TTS_EMPTY,
        modality="tts",
        model="tts",
        call=_synthesize,
        json_cause=False,
        apply_price_table=None,
    )


def test_mm_c06_async_tts_empty_audio(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _call(client: AsyncXaiClient, purpose: str) -> tuple[bytes, str]:
        return await client.synthesize_speech(
            "hello",
            purpose=purpose,
            parent_id=_PARENT,
            labels=_LABELS,
        )

    _run_async(
        _expect_async(
            monkeypatch,
            response=_response(
                200,
                method="POST",
                url=XAI_TTS_URL,
                content=b"",
                headers={"content-type": "audio/mpeg"},
            ),
            purpose="demo.tts.empty",
            message=_TTS_EMPTY,
            modality="tts",
            model="tts",
            call=_call,
            json_cause=False,
            apply_price_table=None,
        )
    )


def test_mm_c07_roster_non_json_and_missing_list(monkeypatch: pytest.MonkeyPatch) -> None:
    _expect_sync(
        monkeypatch,
        response=_response(
            200, method="GET", url=XAI_TTS_VOICES_URL, content=b"not-json"
        ),
        method="get",
        purpose="demo.roster.nonjson",
        message=_ROSTER_NON_JSON,
        modality="tts",
        model="tts",
        call=_list_voices,
        json_cause=True,
        apply_price_table=False,
    )

    async def _list(client: AsyncXaiClient, purpose: str) -> list[dict[str, Any]]:
        return await client.list_tts_voices(
            purpose=purpose,
            parent_id=_PARENT,
            labels=_LABELS,
        )

    _run_async(
        _expect_async(
            monkeypatch,
            response=_response(
                200, method="GET", url=XAI_TTS_VOICES_URL, content=b"not-json"
            ),
            purpose="demo.roster.nonjson",
            message=_ROSTER_NON_JSON,
            modality="tts",
            model="tts",
            call=_list,
            json_cause=True,
            apply_price_table=False,
        )
    )
    for body in (item.values[0] for item in _ROSTER_MISSING_BODIES):
        _expect_sync(
            monkeypatch,
            response=_json_response("GET", XAI_TTS_VOICES_URL, body),
            method="get",
            purpose="demo.roster.missing",
            message=_ROSTER_MISSING,
            modality="tts",
            model="tts",
            call=_list_voices,
            json_cause=False,
            apply_price_table=False,
        )
        _run_async(
            _expect_async(
                monkeypatch,
                response=_json_response("GET", XAI_TTS_VOICES_URL, body),
                purpose="demo.roster.missing",
                message=_ROSTER_MISSING,
                modality="tts",
                model="tts",
                call=_list,
                json_cause=False,
                apply_price_table=False,
            )
        )


def test_mm_c07b_roster_entries_are_not_voice_objects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _list(client: AsyncXaiClient, purpose: str) -> list[dict[str, Any]]:
        return await client.list_tts_voices(
            purpose=purpose,
            parent_id=_PARENT,
            labels=_LABELS,
        )

    for body in (item.values[0] for item in _ROSTER_BAD_ENTRIES):
        _expect_sync(
            monkeypatch,
            response=_json_response("GET", XAI_TTS_VOICES_URL, body),
            method="get",
            purpose="demo.roster.badentry",
            message=_ROSTER_MISSING,
            modality="tts",
            model="tts",
            call=_list_voices,
            json_cause=False,
            apply_price_table=False,
        )
        _run_async(
            _expect_async(
                monkeypatch,
                response=_json_response("GET", XAI_TTS_VOICES_URL, body),
                purpose="demo.roster.badentry",
                message=_ROSTER_MISSING,
                modality="tts",
                model="tts",
                call=_list,
                json_cause=False,
                apply_price_table=False,
            )
        )


def test_mm_c08_sync_get_tts_voice_non_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _expect_sync(
        monkeypatch,
        response=_response(200, method="GET", url=_VOICE_URL, content=b"not-json"),
        method="get",
        purpose="demo.voice.nonjson",
        message=_VOICE_NON_JSON,
        modality="tts",
        model="tts",
        call=_get_voice,
        json_cause=True,
        apply_price_table=False,
    )


def test_mm_c09_async_get_tts_voice_non_json(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _call(client: AsyncXaiClient, purpose: str) -> dict[str, Any]:
        return await client.get_tts_voice(
            "eve",
            purpose=purpose,
            parent_id=_PARENT,
            labels=_LABELS,
        )

    _run_async(
        _expect_async(
            monkeypatch,
            response=_response(200, method="GET", url=_VOICE_URL, content=b"not-json"),
            purpose="demo.voice.nonjson",
            message=_VOICE_NON_JSON,
            modality="tts",
            model="tts",
            call=_call,
            json_cause=True,
            apply_price_table=False,
        )
    )


@pytest.mark.parametrize("body", _VOICE_BAD_BODIES)
def test_mm_c10_sync_get_tts_voice_unexpected(
    monkeypatch: pytest.MonkeyPatch, body: Any
) -> None:
    _expect_sync(
        monkeypatch,
        response=_json_response("GET", _VOICE_URL, body),
        method="get",
        purpose="demo.voice.unexpected",
        message=_VOICE_UNEXPECTED,
        modality="tts",
        model="tts",
        call=_get_voice,
        json_cause=False,
        apply_price_table=False,
    )


@pytest.mark.parametrize("body", _VOICE_BAD_BODIES)
def test_mm_c11_async_get_tts_voice_unexpected(
    monkeypatch: pytest.MonkeyPatch, body: Any
) -> None:
    async def _call(client: AsyncXaiClient, purpose: str) -> dict[str, Any]:
        return await client.get_tts_voice(
            "eve",
            purpose=purpose,
            parent_id=_PARENT,
            labels=_LABELS,
        )

    _run_async(
        _expect_async(
            monkeypatch,
            response=_json_response("GET", _VOICE_URL, body),
            purpose="demo.voice.unexpected",
            message=_VOICE_UNEXPECTED,
            modality="tts",
            model="tts",
            call=_call,
            json_cause=False,
            apply_price_table=False,
        )
    )


def _assert_sync_401(
    monkeypatch: pytest.MonkeyPatch,
    *,
    method: str,
    url: str,
    purpose: str,
    call: Callable[[XaiClient, str], Any],
) -> None:
    sink = InMemoryUsageSink()
    client = _sync_client(sink)
    recorded = _spy(client)
    _install_sync(
        monkeypatch,
        _response(401, method=method.upper(), url=url, content=b"unauthorized"),
        method=method,
    )
    with pytest.raises(RuntimeError, match="unauthorized") as raised:
        call(client, purpose)
    assert "unauthorized" in str(raised.value)
    assert "check API key" in str(raised.value)
    _zero_events(sink, recorded)


async def _assert_async_401(
    monkeypatch: pytest.MonkeyPatch,
    *,
    url: str,
    http_method: str,
    purpose: str,
    call: Callable[[AsyncXaiClient, str], Any],
) -> None:
    sink = InMemoryUsageSink()
    client = _async_client(sink)
    recorded = _spy(client)
    _install_async(
        monkeypatch,
        _response(401, method=http_method, url=url, content=b"unauthorized"),
    )
    with pytest.raises(RuntimeError, match="unauthorized") as raised:
        await call(client, purpose)
    assert "unauthorized" in str(raised.value)
    assert "check API key" in str(raised.value)
    _zero_events(sink, recorded)


def test_mm_c12_http_401_records_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_sync_401(
        monkeypatch,
        method="post",
        url=XAI_STT_URL,
        purpose="demo.stt.401",
        call=_transcribe,
    )
    _assert_sync_401(
        monkeypatch,
        method="post",
        url=XAI_TTS_URL,
        purpose="demo.tts.401",
        call=_synthesize,
    )
    _assert_sync_401(
        monkeypatch,
        method="get",
        url=XAI_TTS_VOICES_URL,
        purpose="demo.roster.401",
        call=_list_voices,
    )
    _assert_sync_401(
        monkeypatch,
        method="get",
        url=_VOICE_URL,
        purpose="demo.voice.401",
        call=_get_voice,
    )

    async def _run() -> None:
        async def _stt(client: AsyncXaiClient, purpose: str) -> str:
            return await client.transcribe(
                b"fake-audio", purpose=purpose, parent_id=_PARENT, labels=_LABELS
            )

        async def _tts(client: AsyncXaiClient, purpose: str) -> tuple[bytes, str]:
            return await client.synthesize_speech(
                "hello", purpose=purpose, parent_id=_PARENT, labels=_LABELS
            )

        async def _roster(client: AsyncXaiClient, purpose: str) -> list[dict[str, Any]]:
            return await client.list_tts_voices(
                purpose=purpose, parent_id=_PARENT, labels=_LABELS
            )

        async def _voice(client: AsyncXaiClient, purpose: str) -> dict[str, Any]:
            return await client.get_tts_voice(
                "eve", purpose=purpose, parent_id=_PARENT, labels=_LABELS
            )

        await _assert_async_401(
            monkeypatch,
            url=XAI_STT_URL,
            http_method="POST",
            purpose="demo.stt.401",
            call=_stt,
        )
        await _assert_async_401(
            monkeypatch,
            url=XAI_TTS_URL,
            http_method="POST",
            purpose="demo.tts.401",
            call=_tts,
        )
        await _assert_async_401(
            monkeypatch,
            url=XAI_TTS_VOICES_URL,
            http_method="GET",
            purpose="demo.roster.401",
            call=_roster,
        )
        await _assert_async_401(
            monkeypatch,
            url=_VOICE_URL,
            http_method="GET",
            purpose="demo.voice.401",
            call=_voice,
        )

    _run_async(_run())


def _assert_sync_success(
    monkeypatch: pytest.MonkeyPatch,
    *,
    response: httpx.Response,
    method: str,
    purpose: str,
    modality: str,
    model: str,
    call: Callable[[XaiClient, str], Any],
    expected: Any,
    apply_price_table: bool | None,
) -> None:
    sink = InMemoryUsageSink()
    client = _sync_client(sink)
    recorded = _spy(client)
    _install_sync(monkeypatch, response, method=method)
    assert call(client, purpose) == expected
    _one_success(
        sink,
        recorded,
        modality=modality,
        model=model,
        purpose=purpose,
        apply_price_table=apply_price_table,
    )


def test_mm_c13_success_records_one_event(monkeypatch: pytest.MonkeyPatch) -> None:
    voices = [{"voice_id": "eve", "name": "Eve", "language": "en"}]
    voice = {"voice_id": "eve", "name": "Eve", "language": "en"}
    _assert_sync_success(
        monkeypatch,
        response=_response(200, method="POST", url=XAI_STT_URL, payload={"text": "hello"}),
        method="post",
        purpose="demo.stt.ok",
        modality="stt",
        model="stt",
        call=_transcribe,
        expected="hello",
        apply_price_table=None,
    )
    _assert_sync_success(
        monkeypatch,
        response=_response(
            200,
            method="POST",
            url=XAI_TTS_URL,
            content=b"ID3fake",
            headers={"content-type": "audio/mpeg"},
        ),
        method="post",
        purpose="demo.tts.ok",
        modality="tts",
        model="tts",
        call=_synthesize,
        expected=(b"ID3fake", "audio/mpeg"),
        apply_price_table=None,
    )
    _assert_sync_success(
        monkeypatch,
        response=_response(
            200, method="GET", url=XAI_TTS_VOICES_URL, payload={"voices": voices}
        ),
        method="get",
        purpose="demo.roster.ok",
        modality="tts",
        model="tts",
        call=_list_voices,
        expected=voices,
        apply_price_table=False,
    )
    _assert_sync_success(
        monkeypatch,
        response=_response(200, method="GET", url=_VOICE_URL, payload=voice),
        method="get",
        purpose="demo.voice.ok",
        modality="tts",
        model="tts",
        call=_get_voice,
        expected=voice,
        apply_price_table=False,
    )

    async def _run() -> None:
        async def _check(
            response: httpx.Response,
            purpose: str,
            modality: str,
            model: str,
            call: Callable[[AsyncXaiClient, str], Any],
            expected: Any,
            apply_price_table: bool | None,
        ) -> None:
            sink = InMemoryUsageSink()
            client = _async_client(sink)
            recorded = _spy(client)
            _install_async(monkeypatch, response)
            assert await call(client, purpose) == expected
            _one_success(
                sink,
                recorded,
                modality=modality,
                model=model,
                purpose=purpose,
                apply_price_table=apply_price_table,
            )

        await _check(
            _response(200, method="POST", url=XAI_STT_URL, payload={"text": "hello"}),
            "demo.stt.ok",
            "stt",
            "stt",
            lambda client, purpose: client.transcribe(
                b"fake-audio", purpose=purpose, parent_id=_PARENT, labels=_LABELS
            ),
            "hello",
            None,
        )
        await _check(
            _response(
                200,
                method="POST",
                url=XAI_TTS_URL,
                content=b"ID3fake",
                headers={"content-type": "audio/mpeg"},
            ),
            "demo.tts.ok",
            "tts",
            "tts",
            lambda client, purpose: client.synthesize_speech(
                "hello", purpose=purpose, parent_id=_PARENT, labels=_LABELS
            ),
            (b"ID3fake", "audio/mpeg"),
            None,
        )
        await _check(
            _response(
                200, method="GET", url=XAI_TTS_VOICES_URL, payload={"voices": voices}
            ),
            "demo.roster.ok",
            "tts",
            "tts",
            lambda client, purpose: client.list_tts_voices(
                purpose=purpose, parent_id=_PARENT, labels=_LABELS
            ),
            voices,
            False,
        )
        await _check(
            _response(200, method="GET", url=_VOICE_URL, payload=voice),
            "demo.voice.ok",
            "tts",
            "tts",
            lambda client, purpose: client.get_tts_voice(
                "eve", purpose=purpose, parent_id=_PARENT, labels=_LABELS
            ),
            voice,
            False,
        )

    _run_async(_run())


def test_mm_c14_stt_413_records_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    sink = InMemoryUsageSink()
    client = _sync_client(sink)
    recorded = _spy(client)
    _install_sync(
        monkeypatch,
        _response(413, method="POST", url=XAI_STT_URL, content=b"too big"),
        method="post",
    )
    with pytest.raises(RuntimeError, match=rf"^{_STT_413}$") as raised:
        _transcribe(client, "demo.stt.413")
    assert str(raised.value) == _STT_413
    _zero_events(sink, recorded)

    async def _run() -> None:
        async_sink = InMemoryUsageSink()
        async_client = _async_client(async_sink)
        async_recorded = _spy(async_client)
        _install_async(
            monkeypatch,
            _response(413, method="POST", url=XAI_STT_URL, content=b"too big"),
        )
        with pytest.raises(RuntimeError, match=rf"^{_STT_413}$") as async_raised:
            await async_client.transcribe(
                b"fake-audio",
                purpose="demo.stt.413",
                parent_id=_PARENT,
                labels=_LABELS,
            )
        assert str(async_raised.value) == _STT_413
        _zero_events(async_sink, async_recorded)

    _run_async(_run())


def _assert_sync_500(
    monkeypatch: pytest.MonkeyPatch,
    *,
    method: str,
    url: str,
    purpose: str,
    call: Callable[[XaiClient, str], Any],
    modality: str,
    model: str,
    apply_price_table: bool | None,
) -> None:
    sink = InMemoryUsageSink()
    client = _sync_client(sink)
    recorded = _spy(client)
    _install_sync(
        monkeypatch,
        _response(500, method=method.upper(), url=url, content=b"boom"),
        method=method,
    )
    with pytest.raises(RuntimeError, match=r"failed \(500\): boom$") as raised:
        call(client, purpose)
    assert "(500)" in str(raised.value)
    events = list(sink.iter_events())
    assert len(events) == 1
    assert events[0].success is False
    assert events[0].error == _HTTP500
    assert events[0].modality == modality
    assert events[0].model == model
    assert events[0].purpose == purpose
    assert events[0].estimated_usd is None
    assert len(recorded) == 1
    assert recorded[0]["success"] is False
    assert recorded[0]["error"] == _HTTP500
    if apply_price_table is None:
        assert "apply_price_table" not in recorded[0]
    else:
        assert recorded[0]["apply_price_table"] is apply_price_table


def test_mm_c15_http_500_records_http500_once(monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_sync_500(
        monkeypatch,
        method="post",
        url=XAI_STT_URL,
        purpose="demo.stt.500",
        call=_transcribe,
        modality="stt",
        model="stt",
        apply_price_table=None,
    )
    _assert_sync_500(
        monkeypatch,
        method="post",
        url=XAI_TTS_URL,
        purpose="demo.tts.500",
        call=_synthesize,
        modality="tts",
        model="tts",
        apply_price_table=None,
    )
    _assert_sync_500(
        monkeypatch,
        method="get",
        url=XAI_TTS_VOICES_URL,
        purpose="demo.roster.500",
        call=_list_voices,
        modality="tts",
        model="tts",
        apply_price_table=False,
    )
    _assert_sync_500(
        monkeypatch,
        method="get",
        url=_VOICE_URL,
        purpose="demo.voice.500",
        call=_get_voice,
        modality="tts",
        model="tts",
        apply_price_table=False,
    )

    async def _run() -> None:
        async def _check(
            url: str,
            http_method: str,
            purpose: str,
            call: Callable[[AsyncXaiClient, str], Any],
            modality: str,
            model: str,
            apply_price_table: bool | None,
        ) -> None:
            sink = InMemoryUsageSink()
            client = _async_client(sink)
            recorded = _spy(client)
            _install_async(
                monkeypatch,
                _response(500, method=http_method, url=url, content=b"boom"),
            )
            with pytest.raises(RuntimeError, match=r"failed \(500\): boom$"):
                await call(client, purpose)
            events = list(sink.iter_events())
            assert len(events) == 1
            assert events[0].error == _HTTP500
            assert events[0].success is False
            assert events[0].modality == modality
            assert events[0].model == model
            assert len(recorded) == 1
            assert recorded[0]["error"] == _HTTP500
            if apply_price_table is None:
                assert "apply_price_table" not in recorded[0]
            else:
                assert recorded[0]["apply_price_table"] is apply_price_table

        await _check(
            XAI_STT_URL,
            "POST",
            "demo.stt.500",
            lambda client, purpose: client.transcribe(
                b"fake-audio", purpose=purpose, parent_id=_PARENT, labels=_LABELS
            ),
            "stt",
            "stt",
            None,
        )
        await _check(
            XAI_TTS_URL,
            "POST",
            "demo.tts.500",
            lambda client, purpose: client.synthesize_speech(
                "hello", purpose=purpose, parent_id=_PARENT, labels=_LABELS
            ),
            "tts",
            "tts",
            None,
        )
        await _check(
            XAI_TTS_VOICES_URL,
            "GET",
            "demo.roster.500",
            lambda client, purpose: client.list_tts_voices(
                purpose=purpose, parent_id=_PARENT, labels=_LABELS
            ),
            "tts",
            "tts",
            False,
        )
        await _check(
            _VOICE_URL,
            "GET",
            "demo.voice.500",
            lambda client, purpose: client.get_tts_voice(
                "eve", purpose=purpose, parent_id=_PARENT, labels=_LABELS
            ),
            "tts",
            "tts",
            False,
        )

    _run_async(_run())


def test_mm_c16_transport_error_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    def _check_sync(
        method: str,
        purpose: str,
        call: Callable[[XaiClient, str], Any],
        modality: str,
        model: str,
        apply_price_table: bool | None,
        prefix: str,
    ) -> None:
        sink = InMemoryUsageSink()
        client = _sync_client(sink)
        recorded = _spy(client)
        _install_sync_raise(monkeypatch, method=method, exc_type=httpx.ConnectError)
        with pytest.raises(RuntimeError, match=rf"^{prefix} request failed: offline$") as raised:
            call(client, purpose)
        assert str(raised.value) == f"{prefix} request failed: offline"
        events = list(sink.iter_events())
        assert len(events) == 1
        assert events[0].success is False
        assert events[0].error == _TRANSPORT_ERROR
        assert events[0].modality == modality
        assert events[0].model == model
        assert events[0].error == str(recorded[0]["error"])
        assert len(recorded) == 1
        if apply_price_table is None:
            assert "apply_price_table" not in recorded[0]
        else:
            assert recorded[0]["apply_price_table"] is apply_price_table

    _check_sync("post", "demo.stt.transport", _transcribe, "stt", "stt", None, "STT")
    _check_sync("post", "demo.tts.transport", _synthesize, "tts", "tts", None, "TTS")
    _check_sync(
        "get", "demo.roster.transport", _list_voices, "tts", "tts", False, "TTS voices"
    )
    _check_sync(
        "get", "demo.voice.transport", _get_voice, "tts", "tts", False, "TTS voices"
    )

    async def _run() -> None:
        async def _check(
            purpose: str,
            call: Callable[[AsyncXaiClient, str], Any],
            modality: str,
            model: str,
            apply_price_table: bool | None,
            prefix: str,
        ) -> None:
            sink = InMemoryUsageSink()
            client = _async_client(sink)
            recorded = _spy(client)
            _install_async_raise(monkeypatch, httpx.ConnectError)
            with pytest.raises(
                RuntimeError, match=rf"^{prefix} request failed: offline$"
            ):
                await call(client, purpose)
            events = list(sink.iter_events())
            assert len(events) == 1
            assert events[0].error == _TRANSPORT_ERROR
            assert events[0].success is False
            assert events[0].modality == modality
            assert events[0].model == model
            assert len(recorded) == 1
            assert recorded[0]["error"] == _TRANSPORT_ERROR
            if apply_price_table is None:
                assert "apply_price_table" not in recorded[0]
            else:
                assert recorded[0]["apply_price_table"] is apply_price_table

        await _check(
            "demo.stt.transport",
            lambda client, purpose: client.transcribe(
                b"fake-audio", purpose=purpose, parent_id=_PARENT, labels=_LABELS
            ),
            "stt",
            "stt",
            None,
            "STT",
        )
        await _check(
            "demo.tts.transport",
            lambda client, purpose: client.synthesize_speech(
                "hello", purpose=purpose, parent_id=_PARENT, labels=_LABELS
            ),
            "tts",
            "tts",
            None,
            "TTS",
        )
        await _check(
            "demo.roster.transport",
            lambda client, purpose: client.list_tts_voices(
                purpose=purpose, parent_id=_PARENT, labels=_LABELS
            ),
            "tts",
            "tts",
            False,
            "TTS voices",
        )
        await _check(
            "demo.voice.transport",
            lambda client, purpose: client.get_tts_voice(
                "eve", purpose=purpose, parent_id=_PARENT, labels=_LABELS
            ),
            "tts",
            "tts",
            False,
            "TTS voices",
        )

    _run_async(_run())
