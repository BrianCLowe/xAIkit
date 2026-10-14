"""Shared custom-voice cases for the sync and async wiring tests.

Not collected by pytest (the filename does not start with ``test_``).
"""

from __future__ import annotations

import asyncio
import inspect
import io
import json
import logging
import re
import tempfile
from collections.abc import Callable
from email import message_from_bytes
from email.policy import default
from pathlib import Path
from typing import Any, Literal, get_args, get_origin
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from xaikit import (
    AsyncXaiClient,
    CustomVoice,
    CustomVoiceError,
    CustomVoicePage,
    InMemoryUsageSink,
    MockChatProvider,
    UsageMeter,
    XAI_CUSTOM_VOICES_URL,
    XaiClient,
    XaiKitError,
    default_retry_policy,
)
from xaikit.custom_voices import UNSET

A1 = b"RIFF" + b"\x00" * 36 + b"WAVE"
A2 = b"ID3"
VOICE_ID = "nlbqfwie"
KEY = "xai-QAFAKEKEY0000"
V1: dict[str, Any] = {
    "voice_id": VOICE_ID,
    "name": "Friendly Narrator",
    "description": "Warm, conversational tone for narration.",
    "gender": "female",
    "accent": "American",
    "age": "young",
    "language": "en",
    "use_case": "narration",
    "tone": "warm",
    "created_at": "2026-04-26T18:56:34.872993+00:00",
}
BASE = "https://api.x.ai/v1/custom-voices"
PAGE_IDS = [
    ["a1b2c3d4", "e5f6g7h8"],
    ["i9j0k1l2", "m3n4o5p6"],
    ["q7r8s9t0"],
]
PAGE_TOKENS = ["t1", "t2", None]

CASES: list[Callable[..., Any]] = []


def case(fn: Callable[..., Any] | None = None, *, sync_only: bool = False, async_only: bool = False):
    def decorate(func: Callable[..., Any]) -> Callable[..., Any]:
        func.sync_only = sync_only  # type: ignore[attr-defined]
        func.async_only = async_only  # type: ignore[attr-defined]
        CASES.append(func)
        return func

    if fn is not None:
        return decorate(fn)
    return decorate


class Script:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.timeouts: list[Any] = []
        self.queue: list[Any] = []

    def push(self, *items: Any) -> Script:
        self.queue.extend(items)
        return self

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self.queue:
            raise AssertionError(f"unexpected {request.method} {request.url}")
        item = self.queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class Env:
    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        *,
        async_mode: bool,
    ) -> None:
        self.monkeypatch = monkeypatch
        self.caplog = caplog
        self.async_mode = async_mode
        self.script = Script()
        self._installed = False

    def install(self) -> Script:
        if self._installed:
            return self.script
        self._installed = True
        script = self.script
        transport = httpx.MockTransport(script.handler)
        if self.async_mode:

            class RecordingAsyncClient(httpx.AsyncClient):
                def __init__(self, *args: Any, **kwargs: Any) -> None:
                    script.timeouts.append(kwargs.get("timeout"))
                    kwargs["transport"] = transport
                    super().__init__(*args, **kwargs)

            self.monkeypatch.setattr(
                "xaikit.async_client.httpx.AsyncClient",
                RecordingAsyncClient,
            )
        else:

            def request(method: str, url: str, **kwargs: Any) -> httpx.Response:
                script.timeouts.append(kwargs.get("timeout"))
                with httpx.Client(transport=transport) as client:
                    return client.request(method, url, **kwargs)

            self.monkeypatch.setattr("xaikit.client.httpx.request", request)
        return script

    def client(self, **kwargs: Any) -> XaiClient | AsyncXaiClient:
        policy = kwargs.pop(
            "retry_policy",
            default_retry_policy(max_attempts=1, backoff_seconds=0),
        )
        api_key = kwargs.pop("api_key", "test-key")
        common = dict(
            model="grok-3-mini",
            api_key=api_key,
            retry_policy=policy,
            provider=MockChatProvider(),
        )
        common.update(kwargs)
        if self.async_mode:
            return AsyncXaiClient(**common)
        return XaiClient(**common)


def json_response(status: int, payload: Any) -> httpx.Response:
    return httpx.Response(status, json=payload)


def text_response(status: int, body: str) -> httpx.Response:
    return httpx.Response(status, content=body.encode("utf-8"))


def voice_row(voice_id: str) -> dict[str, Any]:
    return {"voice_id": voice_id, "name": voice_id, "language": "en"}


def page_payload(ids: list[str], token: str | None) -> dict[str, Any]:
    return {"voices": [voice_row(item) for item in ids], "pagination_token": token}


async def drive(client: Any, method: str, *args: Any, **kwargs: Any) -> Any:
    result = getattr(client, method)(*args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


async def collect_ids(client: Any, **kwargs: Any) -> list[str]:
    result = client.iter_custom_voices(**kwargs)
    ids: list[str] = []
    if hasattr(result, "__anext__"):
        async for voice in result:
            ids.append(voice.voice_id)
    else:
        for voice in result:
            ids.append(voice.voice_id)
    return ids


def parts_of(request: httpx.Request) -> dict[str, dict[str, Any]]:
    ctype = request.headers["content-type"]
    blob = (
        b"Content-Type: "
        + ctype.encode("ascii")
        + b"\r\nMIME-Version: 1.0\r\n\r\n"
        + request.content
    )
    message = message_from_bytes(blob, policy=default)
    found: dict[str, dict[str, Any]] = {}
    for part in message.iter_parts():
        disposition = part.get("Content-Disposition", "")
        name_match = re.search(r'name="([^"]+)"', disposition)
        file_match = re.search(r'filename="([^"]*)"', disposition)
        assert name_match is not None
        found[name_match.group(1)] = {
            "filename": None if file_match is None else file_match.group(1),
            "content_type": part.get_content_type(),
            "data": part.get_payload(decode=True) or b"",
        }
    return found


def assert_voice(voice: CustomVoice, payload: dict[str, Any]) -> None:
    assert isinstance(voice, CustomVoice)
    for key, value in payload.items():
        assert getattr(voice, key) == value


def _policy(attempts: int) -> Any:
    return default_retry_policy(max_attempts=attempts, backoff_seconds=0)


@case
async def c01_create_multipart(env: Env) -> None:
    script = env.install()
    script.push(json_response(201, V1))
    client = env.client()
    voice = await drive(
        client,
        "create_custom_voice",
        file=A1,
        name="Friendly Narrator",
        gender="female",
        tone="warm",
        use_case="narration",
        language="en",
    )
    assert_voice(voice, V1)
    assert len(script.requests) == 1
    request = script.requests[0]
    assert request.method == "POST"
    assert str(request.url) == BASE
    ctype = request.headers["content-type"]
    assert ctype.startswith("multipart/form-data")
    assert "boundary=" in ctype
    assert request.headers["authorization"] == "Bearer test-key"
    assert script.timeouts == [120.0]
    parsed = parts_of(request)
    assert set(parsed) == {"file", "name", "gender", "tone", "use_case", "language"}
    assert parsed["file"]["filename"] == "reference.wav"
    assert parsed["file"]["content_type"] == "audio/wav"
    assert parsed["file"]["data"] == A1
    assert parsed["name"]["data"] == b"Friendly Narrator"
    assert parsed["gender"]["data"] == b"female"
    assert parsed["tone"]["data"] == b"warm"
    assert parsed["use_case"]["data"] == b"narration"
    assert parsed["language"]["data"] == b"en"


@case
async def c02_create_file_only(env: Env) -> None:
    script = env.install()
    script.push(json_response(201, V1))
    voice = await drive(env.client(), "create_custom_voice", file=A1)
    assert voice.voice_id == VOICE_ID
    parsed = parts_of(script.requests[0])
    assert set(parsed) == {"file"}
    assert parsed["file"]["data"] == A1


@case
async def c03_create_parses_voice(env: Env) -> None:
    script = env.install()
    script.push(json_response(201, V1))
    voice = await drive(env.client(), "create_custom_voice", file=A1, name="Friendly Narrator")
    assert_voice(voice, V1)
    assert isinstance(voice.created_at, str)


@case
async def c04_create_file_inputs(env: Env) -> None:
    script = env.install()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "clip.wav"
        path.write_bytes(A1)
        sources = [path, A1, io.BytesIO(A1)]
        for source in sources:
            script.requests.clear()
            script.timeouts.clear()
            script.push(json_response(201, V1))
            await drive(env.client(), "create_custom_voice", file=source)
            parsed = parts_of(script.requests[0])
            assert parsed["file"]["data"] == A1


@case
async def c05_create_enum_before_http(env: Env) -> None:
    script = env.install()
    script.push(json_response(201, V1))
    client = env.client()
    bad = {
        "gender": "other",
        "age": "old-ish",
        "use_case": "podcast",
        "tone": "angry",
    }
    for field, value in bad.items():
        script.requests.clear()
        with pytest.raises(ValueError, match=field):
            await drive(client, "create_custom_voice", file=A1, **{field: value})
        assert script.requests == []


@case
async def c06_list_limit(env: Env) -> None:
    script = env.install()
    client = env.client()
    script.push(json_response(200, page_payload([], None)))
    for bad in (0, 1001, "5", True):
        script.requests.clear()
        with pytest.raises(ValueError, match="limit"):
            await drive(client, "list_custom_voices", limit=bad)
        assert script.requests == []
    for good in (1, 1000):
        script.requests.clear()
        script.push(json_response(200, page_payload([], None)))
        await drive(client, "list_custom_voices", limit=good)
        assert str(script.requests[0].url) == f"{BASE}?limit={good}"


@case
async def c07_voice_id_before_http(env: Env) -> None:
    script = env.install()
    script.push(json_response(200, V1))
    client = env.client()
    bad_ids = ["ABCD1234", "abc1234", "abc123456", "abc-1234", "", " nlbqfwie"]
    methods = (
        "get_custom_voice",
        "update_custom_voice",
        "delete_custom_voice",
        "download_custom_voice_audio",
    )
    for method in methods:
        for voice_id in bad_ids:
            script.requests.clear()
            kwargs = {"description": "x"} if method == "update_custom_voice" else {}
            with pytest.raises(ValueError, match="voice_id"):
                await drive(client, method, voice_id, **kwargs)
            assert script.requests == []
    script.requests.clear()
    script.push(json_response(200, V1))
    voice = await drive(client, "get_custom_voice", VOICE_ID)
    assert voice.voice_id == VOICE_ID
    assert str(script.requests[0].url) == f"{BASE}/{VOICE_ID}"


@case
async def c08_empty_patch_before_http(env: Env) -> None:
    script = env.install()
    script.push(json_response(200, V1))
    client = env.client()
    fields = (
        "name",
        "description",
        "gender",
        "accent",
        "age",
        "language",
        "use_case",
        "tone",
    )
    for field in fields:
        script.requests.clear()
        with pytest.raises(ValueError, match=field):
            await drive(client, "update_custom_voice", VOICE_ID, **{field: ""})
        assert script.requests == []
    script.requests.clear()
    with pytest.raises(ValueError, match="tone"):
        await drive(client, "update_custom_voice", VOICE_ID, tone="angry")
    assert script.requests == []


@case
async def c09_create_requires_file(env: Env) -> None:
    script = env.install()
    script.push(json_response(201, V1))
    client = env.client()
    with pytest.raises(ValueError, match="file"):
        await drive(client, "create_custom_voice")
    assert script.requests == []
    with pytest.raises(ValueError, match="file"):
        await drive(client, "create_custom_voice", file=b"")
    assert script.requests == []


@case
async def c10_missing_key_before_http(env: Env) -> None:
    script = env.install()
    script.push(json_response(200, V1))
    client = env.client()
    client.api_key = ""
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = [
        ("create_custom_voice", (), {"file": A1}),
        ("list_custom_voices", (), {}),
        ("get_custom_voice", (VOICE_ID,), {}),
        ("update_custom_voice", (VOICE_ID,), {"description": "x"}),
        ("delete_custom_voice", (VOICE_ID,), {}),
        ("download_custom_voice_audio", (VOICE_ID,), {}),
    ]
    for method, args, kwargs in calls:
        script.requests.clear()
        with pytest.raises(RuntimeError, match="credentials"):
            await drive(client, method, *args, **kwargs)
        assert script.requests == []
    script.requests.clear()
    with pytest.raises(RuntimeError, match="credentials"):
        await collect_ids(client)
    assert script.requests == []


@case
async def c11_list_query(env: Env) -> None:
    script = env.install()
    script.push(json_response(200, page_payload([VOICE_ID], "t1")))
    script.push(json_response(200, page_payload([], None)))
    client = env.client()
    first = await drive(client, "list_custom_voices")
    second = await drive(client, "list_custom_voices", limit=50, pagination_token="t1")
    assert str(script.requests[0].url) == BASE
    assert script.requests[0].method == "GET"
    assert script.requests[0].content == b""
    assert str(script.requests[1].url) == f"{BASE}?limit=50&pagination_token=t1"
    assert isinstance(first, CustomVoicePage)
    assert [item.voice_id for item in first.voices] == [VOICE_ID]
    assert first.pagination_token == "t1"
    assert second.voices == []
    assert second.pagination_token is None
    assert script.timeouts == [30.0, 30.0]


@case
async def c12_iter_pages(env: Env) -> None:
    script = env.install()
    for ids, token in zip(PAGE_IDS, PAGE_TOKENS):
        script.push(json_response(200, page_payload(ids, token)))
    ids = await collect_ids(env.client())
    assert ids == [item for group in PAGE_IDS for item in group]
    assert len(script.requests) == 3
    assert str(script.requests[0].url) == BASE
    assert str(script.requests[1].url) == f"{BASE}?pagination_token=t1"
    assert str(script.requests[2].url) == f"{BASE}?pagination_token=t2"


@case
async def c13_empty_page(env: Env) -> None:
    script = env.install()
    script.push(json_response(200, {"voices": [], "pagination_token": None}))
    page = await drive(env.client(), "list_custom_voices")
    assert page.voices == []
    assert page.pagination_token is None
    script.push(json_response(200, {"voices": [], "pagination_token": None}))
    assert await collect_ids(env.client()) == []
    assert len(script.requests) == 2


@case
async def c14_get(env: Env) -> None:
    script = env.install()
    script.push(json_response(200, V1))
    voice = await drive(env.client(), "get_custom_voice", VOICE_ID)
    request = script.requests[0]
    assert request.method == "GET"
    assert str(request.url) == f"{BASE}/{VOICE_ID}"
    assert request.content == b""
    assert_voice(voice, V1)
    assert script.timeouts == [30.0]


@case
async def c15_patch_fields(env: Env) -> None:
    script = env.install()
    updated = dict(V1)
    updated["description"] = "Updated after a tuning pass."
    updated["tone"] = "calm"
    script.push(json_response(200, updated))
    voice = await drive(
        env.client(),
        "update_custom_voice",
        VOICE_ID,
        description="Updated after a tuning pass.",
        tone="calm",
    )
    request = script.requests[0]
    assert request.method == "PATCH"
    assert str(request.url) == f"{BASE}/{VOICE_ID}"
    assert request.headers["content-type"].startswith("application/json")
    assert request.content == b'{"description": "Updated after a tuning pass.", "tone": "calm"}'
    assert_voice(voice, updated)
    assert script.timeouts == [30.0]


@case
async def c16_patch_null(env: Env) -> None:
    script = env.install()
    script.push(json_response(200, V1))
    await drive(env.client(), "update_custom_voice", VOICE_ID, accent=None)
    assert script.requests[0].content == b'{"accent": null}'


@case
async def c17_patch_no_fields(env: Env) -> None:
    script = env.install()
    script.push(json_response(200, V1))
    with pytest.raises(ValueError, match="field"):
        await drive(env.client(), "update_custom_voice", VOICE_ID)
    assert script.requests == []


@case
async def c18_delete(env: Env) -> None:
    script = env.install()
    script.push(text_response(200, '{"deleted": true}'))
    script.push(text_response(200, '{"deleted": false}'))
    client = env.client()
    assert await drive(client, "delete_custom_voice", VOICE_ID) is True
    request = script.requests[0]
    assert request.method == "DELETE"
    assert str(request.url) == f"{BASE}/{VOICE_ID}"
    assert request.content == b""
    assert await drive(client, "delete_custom_voice", VOICE_ID) is True
    assert script.timeouts == [30.0, 30.0]


@case
async def c19_download_wav(env: Env) -> None:
    script = env.install()
    script.push(httpx.Response(200, content=A1, headers={"content-type": "audio/wav"}))
    audio, content_type = await drive(env.client(), "download_custom_voice_audio", VOICE_ID)
    request = script.requests[0]
    assert request.method == "GET"
    assert str(request.url) == f"{BASE}/{VOICE_ID}/audio"
    assert audio == A1
    assert isinstance(audio, bytes)
    assert content_type == "audio/wav"
    assert script.timeouts == [120.0]


@case
async def c20_download_mpeg_and_missing_type(env: Env) -> None:
    script = env.install()
    script.push(httpx.Response(200, content=A2, headers={"content-type": "audio/mpeg"}))
    script.push(httpx.Response(200, content=A2))
    client = env.client()
    audio, content_type = await drive(client, "download_custom_voice_audio", VOICE_ID)
    assert audio == A2
    assert content_type == "audio/mpeg"
    audio, content_type = await drive(client, "download_custom_voice_audio", VOICE_ID)
    assert audio == A2
    assert content_type == "application/octet-stream"


def _error_calls() -> list[tuple[str, tuple[Any, ...], dict[str, Any]]]:
    return [
        ("create_custom_voice", (), {"file": A1}),
        ("list_custom_voices", (), {}),
        ("get_custom_voice", (VOICE_ID,), {}),
        ("update_custom_voice", (VOICE_ID,), {"description": "x"}),
        ("delete_custom_voice", (VOICE_ID,), {}),
        ("download_custom_voice_audio", (VOICE_ID,), {}),
    ]


async def _one_call(client: Any, method: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    if method == "iter_custom_voices":
        return await collect_ids(client)
    return await drive(client, method, *args, **kwargs)


@case
async def c21_status_maps_to_custom_voice_error(env: Env) -> None:
    script = env.install()
    client = env.client(retry_policy=_policy(1))
    detail = "custom voices are not enabled for this team"
    calls = _error_calls() + [("iter_custom_voices", (), {})]
    for status in (400, 401, 403, 404, 500):
        for method, args, kwargs in calls:
            script.requests.clear()
            body = detail if status == 403 else f"server detail {status}"
            script.push(text_response(status, body))
            with pytest.raises(CustomVoiceError) as caught:
                await _one_call(client, method, args, kwargs)
            err = caught.value
            assert type(err) is CustomVoiceError
            assert isinstance(err, XaiKitError)
            assert isinstance(err, RuntimeError)
            assert err.status_code == status
            assert body in str(err)
            if status == 403:
                assert str(err) == f"Custom voice request failed (403): {detail}"
                assert "Enterprise" not in str(err)
                assert "region" not in str(err).lower()
            assert len(script.requests) == 1


@case
async def c22_key_absent_from_errors_and_logs(env: Env) -> None:
    script = env.install()
    client = env.client(api_key=KEY, retry_policy=_policy(3))
    calls = _error_calls() + [("iter_custom_voices", (), {})]
    env.caplog.set_level(logging.DEBUG)
    for status in (400, 401, 403, 404, 500):
        for method, args, kwargs in calls:
            attempts = 1 if method == "create_custom_voice" or status != 500 else 3
            body = f"bad Authorization: Bearer {KEY} token {KEY}"
            script.requests.clear()
            script.queue.clear()
            script.push(*[text_response(status, body) for _ in range(attempts)])
            env.caplog.clear()
            with pytest.raises(CustomVoiceError) as caught:
                await _one_call(client, method, args, kwargs)
            err = caught.value
            blob = str(err) + repr(err) + repr(err.args)
            for record in env.caplog.records:
                blob += record.getMessage()
                if record.args:
                    blob += str(record.args)
            assert KEY not in blob
            assert "[redacted]" in str(err)
            assert len(script.requests) == attempts


@case
async def c23_retry_policy_on_500(env: Env) -> None:
    script = env.install()
    client = env.client(retry_policy=_policy(3))
    recoverable = (
        ("get_custom_voice", (VOICE_ID,), {}, json_response(200, V1)),
        ("list_custom_voices", (), {}, json_response(200, page_payload([], None))),
        (
            "download_custom_voice_audio",
            (VOICE_ID,),
            {},
            httpx.Response(200, content=A1, headers={"content-type": "audio/wav"}),
        ),
        ("update_custom_voice", (VOICE_ID,), {"tone": "calm"}, json_response(200, V1)),
        ("delete_custom_voice", (VOICE_ID,), {}, text_response(200, '{"deleted": true}')),
    )
    for method, args, kwargs, ok in recoverable:
        script.requests.clear()
        script.push(text_response(500, "try again"), ok)
        await _one_call(client, method, args, kwargs)
        assert len(script.requests) == 2
    for method, args, kwargs, _ok in recoverable:
        script.requests.clear()
        script.push(
            text_response(500, "a"),
            text_response(500, "b"),
            text_response(500, "c"),
        )
        with pytest.raises(CustomVoiceError) as caught:
            await _one_call(client, method, args, kwargs)
        assert caught.value.status_code == 500
        assert len(script.requests) == 3
    tight = env.client(retry_policy=_policy(1))
    script.requests.clear()
    script.push(text_response(500, "once"))
    with pytest.raises(CustomVoiceError):
        await drive(tight, "get_custom_voice", VOICE_ID)
    assert len(script.requests) == 1
    two = env.client(retry_policy=_policy(2))
    script.requests.clear()
    script.push(text_response(500, "a"), text_response(500, "b"))
    with pytest.raises(CustomVoiceError):
        await drive(two, "list_custom_voices")
    assert len(script.requests) == 2


@case
async def c24_no_retry_on_4xx_or_create(env: Env) -> None:
    script = env.install()
    client = env.client(retry_policy=_policy(3))
    calls = _error_calls() + [("iter_custom_voices", (), {})]
    for status in (400, 401, 403, 404):
        for method, args, kwargs in calls:
            script.requests.clear()
            script.queue.clear()
            script.push(text_response(status, "no"))
            with pytest.raises(CustomVoiceError) as caught:
                await _one_call(client, method, args, kwargs)
            assert caught.value.status_code == status
            assert len(script.requests) == 1
    script.requests.clear()
    script.push(text_response(500, "create failed"), json_response(201, V1))
    with pytest.raises(CustomVoiceError) as caught:
        await drive(client, "create_custom_voice", file=A1)
    assert caught.value.status_code == 500
    assert len(script.requests) == 1


@case(sync_only=True)
async def c25_voice_id_passes_to_tts(env: Env) -> None:
    script = env.install()
    script.push(json_response(201, V1))
    client = env.client()
    created = await drive(client, "create_custom_voice", file=A1)
    posted: list[dict[str, Any]] = []

    def _post(url: str, **kwargs: Any) -> httpx.Response:
        posted.append({"url": url, **kwargs})
        return httpx.Response(
            200,
            content=b"mp3",
            headers={"content-type": "audio/mpeg"},
            request=httpx.Request("POST", url),
        )

    env.monkeypatch.setattr("xaikit.client.httpx.post", _post)
    audio, content_type = client.synthesize_speech("Hello there", voice_id=created.voice_id)
    assert audio == b"mp3"
    assert content_type == "audio/mpeg"
    assert posted[0]["json"]["voice_id"] == VOICE_ID


@case(sync_only=True)
async def c26_voice_id_passes_to_tts_websocket(env: Env) -> None:
    script = env.install()
    script.push(json_response(201, V1))
    client = env.client()
    created = await drive(client, "create_custom_voice", file=A1)
    calls: list[dict[str, Any]] = []

    class FakeWS:
        def send(self, message: str | bytes) -> None:
            return None

        def recv(self, timeout: float | None = None) -> str:
            raise TimeoutError("no messages")

        def close(self) -> None:
            return None

    def _connect(uri: str, **kwargs: Any) -> FakeWS:
        calls.append({"uri": uri, **kwargs})
        return FakeWS()

    env.monkeypatch.setattr("xaikit.client.connect_tts_websocket", _connect)
    session = client.open_tts_session(voice=created.voice_id)
    query = parse_qs(urlsplit(calls[0]["uri"]).query)
    assert query["voice"] == [VOICE_ID]
    session.close()


@case(sync_only=True)
async def c27_voice_id_passes_to_realtime(env: Env) -> None:
    script = env.install()
    script.push(json_response(201, V1))
    client = env.client()
    created = await drive(client, "create_custom_voice", file=A1)
    sockets: list[Any] = []

    class FakeWS:
        def __init__(self) -> None:
            self.sent: list[str | bytes] = []

        def send(self, message: str | bytes) -> None:
            self.sent.append(message)

        def recv(self, timeout: float | None = None) -> str:
            raise TimeoutError("no messages")

        def close(self) -> None:
            return None

    def _connect(uri: str, **kwargs: Any) -> FakeWS:
        ws = FakeWS()
        sockets.append(ws)
        return ws

    env.monkeypatch.setattr("xaikit.client.connect_realtime_websocket", _connect)
    session = client.open_realtime_session(voice=created.voice_id)
    event = json.loads(sockets[0].sent[0])
    assert event["type"] == "session.update"
    assert event["session"]["voice"] == VOICE_ID
    session.close()


@case(sync_only=True)
async def c28_literal_voice_id_passthrough(env: Env) -> None:
    posted: list[dict[str, Any]] = []

    def _post(url: str, **kwargs: Any) -> httpx.Response:
        posted.append({"url": url, **kwargs})
        return httpx.Response(
            200,
            content=b"mp3",
            headers={"content-type": "audio/mpeg"},
            request=httpx.Request("POST", url),
        )

    env.monkeypatch.setattr("xaikit.client.httpx.post", _post)
    client = env.client()
    client.synthesize_speech("Hello there", voice_id=VOICE_ID)
    assert posted[0]["json"]["voice_id"] == VOICE_ID

    tts_calls: list[str] = []

    class FakeWS:
        def send(self, message: str | bytes) -> None:
            return None

        def recv(self, timeout: float | None = None) -> str:
            raise TimeoutError("no messages")

        def close(self) -> None:
            return None

    def _tts(uri: str, **kwargs: Any) -> FakeWS:
        tts_calls.append(uri)
        return FakeWS()

    env.monkeypatch.setattr("xaikit.client.connect_tts_websocket", _tts)
    session = client.open_tts_session(voice=VOICE_ID)
    assert parse_qs(urlsplit(tts_calls[0]).query)["voice"] == [VOICE_ID]
    session.close()

    realtime: list[Any] = []

    class RT:
        def __init__(self) -> None:
            self.sent: list[str | bytes] = []

        def send(self, message: str | bytes) -> None:
            self.sent.append(message)

        def close(self) -> None:
            return None

    def _rt(uri: str, **kwargs: Any) -> RT:
        ws = RT()
        realtime.append(ws)
        return ws

    env.monkeypatch.setattr("xaikit.client.connect_realtime_websocket", _rt)
    session = client.open_realtime_session(voice=VOICE_ID)
    event = json.loads(realtime[0].sent[0])
    assert event["session"]["voice"] == VOICE_ID
    session.close()


def _usage_client(env: Env) -> tuple[Any, InMemoryUsageSink, list[dict[str, Any]]]:
    sink = InMemoryUsageSink()
    client = env.client(
        usage_meter=UsageMeter(sink=sink),
        retry_policy=_policy(3),
    )
    recorded: list[dict[str, Any]] = []
    original = client._record

    def _wrap(**kwargs: Any) -> None:
        recorded.append(kwargs)
        original(**kwargs)

    client._record = _wrap  # type: ignore[method-assign]
    return client, sink, recorded


async def _usage_success(client: Any, method: str) -> None:
    kwargs = {
        "purpose": "demo.custom",
        "parent_id": "p1",
        "labels": {"request_id": "v1"},
    }
    if method == "create_custom_voice":
        await drive(client, method, file=A1, **kwargs)
    elif method == "list_custom_voices":
        await drive(client, method, **kwargs)
    elif method == "update_custom_voice":
        await drive(client, method, VOICE_ID, tone="calm", **kwargs)
    else:
        await drive(client, method, VOICE_ID, **kwargs)


@case
async def c31_usage_records(env: Env) -> None:
    script = env.install()
    ops = {
        "create_custom_voice": "custom_voices.create",
        "list_custom_voices": "custom_voices.list",
        "get_custom_voice": "custom_voices.get",
        "update_custom_voice": "custom_voices.update",
        "delete_custom_voice": "custom_voices.delete",
        "download_custom_voice_audio": "custom_voices.download",
    }
    success_payload = {
        "create_custom_voice": json_response(201, V1),
        "list_custom_voices": json_response(200, page_payload([VOICE_ID], None)),
        "get_custom_voice": json_response(200, V1),
        "update_custom_voice": json_response(200, V1),
        "delete_custom_voice": text_response(200, '{"deleted": true}'),
        "download_custom_voice_audio": httpx.Response(
            200, content=A1, headers={"content-type": "audio/wav"}
        ),
    }
    for method, operation in ops.items():
        script.queue.clear()
        script.push(success_payload[method])
        client, sink, recorded = _usage_client(env)
        await _usage_success(client, method)
        events = list(sink.iter_events())
        assert len(events) == 1
        event = events[0]
        assert event.model == operation
        assert event.modality == "tts"
        assert event.success is True
        assert event.error is None
        assert event.purpose == "demo.custom"
        assert event.parent_id == "p1"
        assert event.labels == {"request_id": "v1"}
        assert event.estimated_usd is None
        assert recorded[-1]["apply_price_table"] is False

        script.queue.clear()
        script.push(text_response(400, "nope"), text_response(200, "no"))
        client, sink, recorded = _usage_client(env)
        with pytest.raises(CustomVoiceError):
            await _usage_success(client, method)
        events = list(sink.iter_events())
        assert len(events) == 1
        assert events[0].success is False
        assert events[0].error == "CustomVoiceError"
        assert events[0].model == operation
        assert events[0].purpose == "demo.custom"
        assert events[0].parent_id == "p1"
        assert events[0].labels == {"request_id": "v1"}

    script.queue.clear()
    script.push(text_response(500, "a"), text_response(500, "b"), text_response(500, "c"))
    client, sink, _recorded = _usage_client(env)
    with pytest.raises(CustomVoiceError):
        await drive(
            client,
            "get_custom_voice",
            VOICE_ID,
            purpose="demo.custom",
            parent_id="p1",
            labels={"request_id": "v1"},
        )
    assert len(list(sink.iter_events())) == 1

    script.queue.clear()
    for ids, token in zip(PAGE_IDS, PAGE_TOKENS):
        script.push(json_response(200, page_payload(ids, token)))
    client, sink, _recorded = _usage_client(env)
    ids = await collect_ids(
        client,
        purpose="demo.custom",
        parent_id="p1",
        labels={"request_id": "v1"},
    )
    assert len(ids) == 5
    events = list(sink.iter_events())
    assert len(events) == 3
    assert [event.model for event in events] == ["custom_voices.list"] * 3
    assert all(event.success for event in events)


@case
async def c32_custom_base_url(env: Env) -> None:
    script = env.install()
    proxy = "https://proxy.example.test/v1"
    client = env.client(base_url=proxy, retry_policy=_policy(1))
    planned = [
        ("create_custom_voice", (), {"file": A1}, json_response(201, V1), f"{proxy}/custom-voices"),
        ("list_custom_voices", (), {}, json_response(200, page_payload([], None)), f"{proxy}/custom-voices"),
        ("get_custom_voice", (VOICE_ID,), {}, json_response(200, V1), f"{proxy}/custom-voices/{VOICE_ID}"),
        (
            "update_custom_voice",
            (VOICE_ID,),
            {"tone": "calm"},
            json_response(200, V1),
            f"{proxy}/custom-voices/{VOICE_ID}",
        ),
        (
            "delete_custom_voice",
            (VOICE_ID,),
            {},
            text_response(200, '{"deleted": true}'),
            f"{proxy}/custom-voices/{VOICE_ID}",
        ),
        (
            "download_custom_voice_audio",
            (VOICE_ID,),
            {},
            httpx.Response(200, content=A1, headers={"content-type": "audio/wav"}),
            f"{proxy}/custom-voices/{VOICE_ID}/audio",
        ),
    ]
    for method, args, kwargs, response, url in planned:
        script.requests.clear()
        script.push(response)
        await drive(client, method, *args, **kwargs)
        assert str(script.requests[0].url) == url
        assert "api.x.ai" not in str(script.requests[0].url)


@case
async def c33_signatures_match(_env: Env) -> None:
    names = (
        "create_custom_voice",
        "list_custom_voices",
        "iter_custom_voices",
        "get_custom_voice",
        "update_custom_voice",
        "delete_custom_voice",
        "download_custom_voice_audio",
    )
    for name in names:
        sync_sig = inspect.signature(getattr(XaiClient, name))
        async_sig = inspect.signature(getattr(AsyncXaiClient, name))
        sync_params = [item for item in sync_sig.parameters.values() if item.name != "self"]
        async_params = [item for item in async_sig.parameters.values() if item.name != "self"]
        assert [item.name for item in sync_params] == [item.name for item in async_params]
        assert [item.kind for item in sync_params] == [item.kind for item in async_params]
        assert [item.default for item in sync_params] == [item.default for item in async_params]
    update = inspect.signature(XaiClient.update_custom_voice)
    assert update.parameters["name"].default is UNSET
    assert update.parameters["name"].kind is inspect.Parameter.KEYWORD_ONLY
    assert update.parameters["voice_id"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    created = inspect.signature(XaiClient.create_custom_voice)
    assert created.parameters["file"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert created.parameters["name"].kind is inspect.Parameter.KEYWORD_ONLY


@case(sync_only=True)
async def c34_exports(_env: Env) -> None:
    import xaikit

    assert xaikit.XAI_CUSTOM_VOICES_URL == "https://api.x.ai/v1/custom-voices"
    assert xaikit.XAI_CUSTOM_VOICES_URL == XAI_CUSTOM_VOICES_URL
    for name in ("XAI_CUSTOM_VOICES_URL", "CustomVoice", "CustomVoicePage", "CustomVoiceError"):
        assert name in xaikit.__all__
        assert hasattr(xaikit, name)


def _literal_values(annotation: Any) -> set[str]:
    values: set[str] = set()
    origin = get_origin(annotation)
    if origin is Literal:
        values.update(str(item) for item in get_args(annotation))
        return values
    if origin is not None:
        for arg in get_args(annotation):
            values.update(_literal_values(arg))
    return values


@case(sync_only=True)
async def c35_model_literals(_env: Env) -> None:
    expected = {
        "gender": {"male", "female", "neutral"},
        "age": {"young", "middle-aged", "old"},
        "use_case": {
            "conversational",
            "narration",
            "characters",
            "educational",
            "advertisement",
            "social_media",
            "entertainment",
        },
        "tone": {
            "warm",
            "casual",
            "professional",
            "friendly",
            "authoritative",
            "expressive",
            "calm",
        },
    }
    for field, choices in expected.items():
        annotation = CustomVoice.model_fields[field].annotation
        assert annotation is not str
        assert _literal_values(annotation) == choices
    page_voices = CustomVoicePage.model_fields["voices"].annotation
    assert CustomVoice in get_args(page_voices) or get_args(page_voices) == (CustomVoice,)
    token = CustomVoicePage.model_fields["pagination_token"].annotation
    assert str in get_args(token) or token == (str | None)
    alien = dict(V1)
    alien["gender"] = "alien-new"
    alien["future_flag"] = True
    voice = CustomVoice.model_validate(alien)
    assert voice.gender == "alien-new"
    assert voice.model_dump()["future_flag"] is True
    assert isinstance(voice.created_at, str)
    empty = CustomVoicePage.model_validate({"voices": [], "pagination_token": None})
    assert empty.voices == []
    assert empty.pagination_token is None


@case(sync_only=True)
async def c36_docs_and_docstrings(_env: Env) -> None:
    sync_doc = inspect.getdoc(XaiClient.list_tts_voices) or ""
    async_doc = inspect.getdoc(AsyncXaiClient.list_tts_voices) or ""
    for doc in (sync_doc, async_doc):
        lowered = doc.lower()
        assert "not wrapped" not in lowered
        assert "does not wrap" not in lowered
        assert "create_custom_voice" in doc
        assert "list_custom_voices" in doc
    root = Path(__file__).resolve().parents[1]
    methods = (
        "create_custom_voice",
        "list_custom_voices",
        "iter_custom_voices",
        "get_custom_voice",
        "update_custom_voice",
        "delete_custom_voice",
        "download_custom_voice_audio",
    )
    for relative in (
        "docs/features/MediaRest.md",
        "docs/features/RealtimeVoice.md",
        "docs/features/ApiCoverage.md",
    ):
        text = (root / relative).read_text(encoding="utf-8")
        for method in methods:
            assert method in text
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "XK-CV-AC-1..9" in changelog or all(
        f"XK-CV-AC-{index}" in changelog for index in range(1, 10)
    )
    for index in range(1, 10):
        assert f"XK-CV-AC-{index}" in changelog
    typed = root / "src" / "xaikit" / "py.typed"
    assert typed.is_file()


@case
async def c_transport_retry_except_create(env: Env) -> None:
    script = env.install()
    client = env.client(retry_policy=_policy(3))
    script.push(httpx.ConnectError("connection refused"), json_response(200, V1))
    voice = await drive(client, "get_custom_voice", VOICE_ID)
    assert voice.voice_id == VOICE_ID
    assert len(script.requests) == 2
    script.requests.clear()
    script.push(httpx.ConnectError("connection refused"), json_response(201, V1))
    with pytest.raises(RuntimeError, match="Custom voice request failed"):
        await drive(client, "create_custom_voice", file=A1)
    assert len(script.requests) == 1


def run_case(env: Env, func: Callable[..., Any]) -> None:
    asyncio.run(func(env))
