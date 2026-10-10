"""Unparseable 2xx bodies record one failed usage event, then raise.

XK-AC-METER-1, XK-AC-METER-2, XK-AC-METER-3. HTTP is mocked at
``httpx.post`` (sync) or ``httpx.AsyncClient`` (async). The usage sink is real.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from xaikit import (
    DEFAULT_IMAGE_MODEL,
    DEFAULT_VIDEO_MODEL,
    AsyncXaiClient,
    InMemoryUsageSink,
    MockChatProvider,
    UsageMeter,
    XAI_IMAGE_EDITS_URL,
    XAI_IMAGES_URL,
    XAI_VIDEO_EXTENSIONS_URL,
    XAI_VIDEOS_URL,
    XaiClient,
    default_retry_policy,
)

_VIDEO_NON_JSON = "Video generation returned non-JSON response"
_VIDEO_UNEXPECTED = "Video generation returned unexpected payload"
_VIDEO_MISSING = "Video generation response missing request_id"
_EXTEND_NON_JSON = "Video extension returned non-JSON response"
_EXTEND_UNEXPECTED = "Video extension returned unexpected payload"
_EXTEND_MISSING = "Video extension response missing request_id"
_IMAGINE_NON_JSON = "Imagine returned non-JSON response"
_EXTEND_MODEL = "grok-imagine-video"
_PARENT = "p1"
_LABELS = {"request_id": "v1"}


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


def _response(
    status_code: int,
    *,
    url: str,
    payload: Any = None,
    content: bytes | None = None,
) -> httpx.Response:
    kwargs: dict[str, Any] = {
        "status_code": status_code,
        "request": httpx.Request("POST", url),
    }
    if content is not None:
        kwargs["content"] = content
    else:
        kwargs["json"] = payload
    return httpx.Response(**kwargs)


def _install_post(monkeypatch: pytest.MonkeyPatch, response: httpx.Response) -> None:
    def _post(url: str, **kwargs: Any) -> httpx.Response:
        if response.request is not None:
            return response
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            content=response.content,
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("xaikit.client.httpx.post", _post)


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


def _sync_http_failure_usd(monkeypatch: pytest.MonkeyPatch, kind: str) -> float | None:
    """USD on a real HTTP 400 failure, the sibling path these cases must match."""
    sink = InMemoryUsageSink()
    client = _sync_client(sink)
    if kind == "video":
        _install_post(monkeypatch, _response(400, url=XAI_VIDEOS_URL, content=b"bad"))
        with pytest.raises(RuntimeError):
            client.generate_video(
                "a cube",
                purpose="demo.sibling",
                parent_id=_PARENT,
                labels=_LABELS,
                into=[],
                wait=False,
            )
    elif kind == "extend":
        _install_post(
            monkeypatch, _response(400, url=XAI_VIDEO_EXTENSIONS_URL, content=b"bad")
        )
        with pytest.raises(RuntimeError):
            client.extend_video(
                "a cube",
                video_url="https://example.com/clip.mp4",
                purpose="demo.sibling",
                parent_id=_PARENT,
                labels=_LABELS,
                into=[],
                wait=False,
            )
    elif kind == "imagine":
        _install_post(monkeypatch, _response(400, url=XAI_IMAGES_URL, content=b"bad"))
        with pytest.raises(RuntimeError):
            client.generate_image(
                "a cube",
                purpose="demo.sibling",
                parent_id=_PARENT,
                labels=_LABELS,
            )
    elif kind == "edit":
        _install_post(monkeypatch, _response(400, url=XAI_IMAGE_EDITS_URL, content=b"bad"))
        with pytest.raises(RuntimeError):
            client.edit_image(
                "a cube",
                image_url="https://example.com/src.png",
                purpose="demo.sibling",
                parent_id=_PARENT,
                labels=_LABELS,
            )
    else:
        raise AssertionError(kind)
    events = list(sink.iter_events())
    assert len(events) == 1
    assert events[0].success is False
    return events[0].estimated_usd


async def _async_http_failure_usd(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> float | None:
    sink = InMemoryUsageSink()
    client = _async_client(sink)
    if kind == "video":
        _install_async(monkeypatch, _response(400, url=XAI_VIDEOS_URL, content=b"bad"))
        with pytest.raises(RuntimeError):
            await client.generate_video(
                "a cube",
                purpose="demo.sibling",
                parent_id=_PARENT,
                labels=_LABELS,
                into=[],
                wait=False,
            )
    elif kind == "extend":
        _install_async(
            monkeypatch, _response(400, url=XAI_VIDEO_EXTENSIONS_URL, content=b"bad")
        )
        with pytest.raises(RuntimeError):
            await client.extend_video(
                "a cube",
                video_url="https://example.com/clip.mp4",
                purpose="demo.sibling",
                parent_id=_PARENT,
                labels=_LABELS,
                into=[],
                wait=False,
            )
    elif kind == "imagine":
        _install_async(monkeypatch, _response(400, url=XAI_IMAGES_URL, content=b"bad"))
        with pytest.raises(RuntimeError):
            await client.generate_image(
                "a cube",
                purpose="demo.sibling",
                parent_id=_PARENT,
                labels=_LABELS,
            )
    elif kind == "edit":
        _install_async(
            monkeypatch, _response(400, url=XAI_IMAGE_EDITS_URL, content=b"bad")
        )
        with pytest.raises(RuntimeError):
            await client.edit_image(
                "a cube",
                image_url="https://example.com/src.png",
                purpose="demo.sibling",
                parent_id=_PARENT,
                labels=_LABELS,
            )
    else:
        raise AssertionError(kind)
    events = list(sink.iter_events())
    assert len(events) == 1
    assert events[0].success is False
    return events[0].estimated_usd


def _one_failed(
    sink: InMemoryUsageSink,
    *,
    modality: str,
    raised: BaseException,
    estimated_usd: float | None,
    purpose: str,
    model: str,
) -> None:
    events = list(sink.iter_events())
    assert len(events) == 1, f"expected 1 failed event, recorded {len(events)}"
    ev = events[0]
    assert ev.success is False
    assert ev.modality == modality
    assert ev.error == str(raised)
    assert ev.purpose == purpose
    assert ev.parent_id == _PARENT
    assert ev.labels == _LABELS
    assert ev.model == model
    assert ev.estimated_usd == estimated_usd


def _one_success(
    sink: InMemoryUsageSink,
    *,
    modality: str,
    purpose: str,
    model: str,
) -> None:
    events = list(sink.iter_events())
    assert len(events) == 1, f"expected 1 success event, recorded {len(events)}"
    ev = events[0]
    assert ev.success is True
    assert ev.error is None
    assert ev.modality == modality
    assert ev.purpose == purpose
    assert ev.parent_id == _PARENT
    assert ev.labels == _LABELS
    assert ev.model == model


def test_xk_ac_meter_1_sync_video_non_json_records_one_failed_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sibling_usd = _sync_http_failure_usd(monkeypatch, "video")
    sink = InMemoryUsageSink()
    client = _sync_client(sink)
    _install_post(
        monkeypatch,
        _response(200, url=XAI_VIDEOS_URL, content=b"not-json"),
    )
    with pytest.raises(RuntimeError, match=rf"^{_VIDEO_NON_JSON}$") as raised:
        client.generate_video(
            "a cube",
            purpose="demo.video.nonjson",
            parent_id=_PARENT,
            labels=_LABELS,
            into=[],
            wait=False,
        )
    assert str(raised.value) == _VIDEO_NON_JSON
    assert isinstance(raised.value.__cause__, json.JSONDecodeError)
    _one_failed(
        sink,
        modality="video",
        raised=raised.value,
        estimated_usd=sibling_usd,
        purpose="demo.video.nonjson",
        model=DEFAULT_VIDEO_MODEL,
    )


def test_xk_ac_meter_1_async_video_non_json_records_one_failed_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run() -> None:
        sibling_usd = await _async_http_failure_usd(monkeypatch, "video")
        sink = InMemoryUsageSink()
        client = _async_client(sink)
        _install_async(
            monkeypatch,
            _response(200, url=XAI_VIDEOS_URL, content=b"not-json"),
        )
        with pytest.raises(RuntimeError, match=rf"^{_VIDEO_NON_JSON}$") as raised:
            await client.generate_video(
                "a cube",
                purpose="demo.video.nonjson",
                parent_id=_PARENT,
                labels=_LABELS,
                into=[],
                wait=False,
            )
        assert str(raised.value) == _VIDEO_NON_JSON
        assert isinstance(raised.value.__cause__, json.JSONDecodeError)
        _one_failed(
            sink,
            modality="video",
            raised=raised.value,
            estimated_usd=sibling_usd,
            purpose="demo.video.nonjson",
            model=DEFAULT_VIDEO_MODEL,
        )

    asyncio.run(_run())


def test_xk_ac_meter_2_sync_video_json_array_records_one_failed_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sibling_usd = _sync_http_failure_usd(monkeypatch, "video")
    sink = InMemoryUsageSink()
    client = _sync_client(sink)
    _install_post(monkeypatch, _response(200, url=XAI_VIDEOS_URL, payload=[]))
    with pytest.raises(RuntimeError, match=rf"^{_VIDEO_UNEXPECTED}$") as raised:
        client.generate_video(
            "a cube",
            purpose="demo.video.array",
            parent_id=_PARENT,
            labels=_LABELS,
            into=[],
            wait=False,
        )
    assert str(raised.value) == _VIDEO_UNEXPECTED
    assert raised.value.__cause__ is None
    _one_failed(
        sink,
        modality="video",
        raised=raised.value,
        estimated_usd=sibling_usd,
        purpose="demo.video.array",
        model=DEFAULT_VIDEO_MODEL,
    )


def test_xk_ac_meter_2_async_video_json_array_records_one_failed_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run() -> None:
        sibling_usd = await _async_http_failure_usd(monkeypatch, "video")
        sink = InMemoryUsageSink()
        client = _async_client(sink)
        _install_async(monkeypatch, _response(200, url=XAI_VIDEOS_URL, payload=[]))
        with pytest.raises(RuntimeError, match=rf"^{_VIDEO_UNEXPECTED}$") as raised:
            await client.generate_video(
                "a cube",
                purpose="demo.video.array",
                parent_id=_PARENT,
                labels=_LABELS,
                into=[],
                wait=False,
            )
        assert str(raised.value) == _VIDEO_UNEXPECTED
        assert raised.value.__cause__ is None
        _one_failed(
            sink,
            modality="video",
            raised=raised.value,
            estimated_usd=sibling_usd,
            purpose="demo.video.array",
            model=DEFAULT_VIDEO_MODEL,
        )

    asyncio.run(_run())


def test_xk_ac_meter_2_sync_video_object_missing_request_id_records_one_failed_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sibling_usd = _sync_http_failure_usd(monkeypatch, "video")
    sink = InMemoryUsageSink()
    client = _sync_client(sink)
    _install_post(
        monkeypatch,
        _response(200, url=XAI_VIDEOS_URL, payload={"status": "pending"}),
    )
    with pytest.raises(RuntimeError, match=rf"^{_VIDEO_MISSING}$") as raised:
        client.generate_video(
            "a cube",
            purpose="demo.video.noreqid",
            parent_id=_PARENT,
            labels=_LABELS,
            into=[],
            wait=False,
        )
    assert str(raised.value) == _VIDEO_MISSING
    assert raised.value.__cause__ is None
    _one_failed(
        sink,
        modality="video",
        raised=raised.value,
        estimated_usd=sibling_usd,
        purpose="demo.video.noreqid",
        model=DEFAULT_VIDEO_MODEL,
    )


def test_xk_ac_meter_2_async_video_object_missing_request_id_records_one_failed_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run() -> None:
        sibling_usd = await _async_http_failure_usd(monkeypatch, "video")
        sink = InMemoryUsageSink()
        client = _async_client(sink)
        _install_async(
            monkeypatch,
            _response(200, url=XAI_VIDEOS_URL, payload={"status": "pending"}),
        )
        with pytest.raises(RuntimeError, match=rf"^{_VIDEO_MISSING}$") as raised:
            await client.generate_video(
                "a cube",
                purpose="demo.video.noreqid",
                parent_id=_PARENT,
                labels=_LABELS,
                into=[],
                wait=False,
            )
        assert str(raised.value) == _VIDEO_MISSING
        assert raised.value.__cause__ is None
        _one_failed(
            sink,
            modality="video",
            raised=raised.value,
            estimated_usd=sibling_usd,
            purpose="demo.video.noreqid",
            model=DEFAULT_VIDEO_MODEL,
        )

    asyncio.run(_run())


def test_xk_ac_meter_2_sync_video_empty_request_id_records_one_failed_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sibling_usd = _sync_http_failure_usd(monkeypatch, "video")
    sink = InMemoryUsageSink()
    client = _sync_client(sink)
    _install_post(
        monkeypatch,
        _response(200, url=XAI_VIDEOS_URL, payload={"request_id": ""}),
    )
    with pytest.raises(RuntimeError, match=rf"^{_VIDEO_MISSING}$") as raised:
        client.generate_video(
            "a cube",
            purpose="demo.video.emptyreq",
            parent_id=_PARENT,
            labels=_LABELS,
            into=[],
            wait=False,
        )
    assert str(raised.value) == _VIDEO_MISSING
    assert raised.value.__cause__ is None
    _one_failed(
        sink,
        modality="video",
        raised=raised.value,
        estimated_usd=sibling_usd,
        purpose="demo.video.emptyreq",
        model=DEFAULT_VIDEO_MODEL,
    )


def test_xk_ac_meter_2_async_video_empty_request_id_records_one_failed_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run() -> None:
        sibling_usd = await _async_http_failure_usd(monkeypatch, "video")
        sink = InMemoryUsageSink()
        client = _async_client(sink)
        _install_async(
            monkeypatch,
            _response(200, url=XAI_VIDEOS_URL, payload={"request_id": ""}),
        )
        with pytest.raises(RuntimeError, match=rf"^{_VIDEO_MISSING}$") as raised:
            await client.generate_video(
                "a cube",
                purpose="demo.video.emptyreq",
                parent_id=_PARENT,
                labels=_LABELS,
                into=[],
                wait=False,
            )
        assert str(raised.value) == _VIDEO_MISSING
        assert raised.value.__cause__ is None
        _one_failed(
            sink,
            modality="video",
            raised=raised.value,
            estimated_usd=sibling_usd,
            purpose="demo.video.emptyreq",
            model=DEFAULT_VIDEO_MODEL,
        )

    asyncio.run(_run())


def test_xk_ac_meter_3_sync_imagine_non_json_records_one_failed_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sibling_usd = _sync_http_failure_usd(monkeypatch, "imagine")
    sink = InMemoryUsageSink()
    client = _sync_client(sink)
    _install_post(
        monkeypatch,
        _response(200, url=XAI_IMAGES_URL, content=b"not-json"),
    )
    with pytest.raises(RuntimeError, match=rf"^{_IMAGINE_NON_JSON}$") as raised:
        client.generate_image(
            "a cube",
            purpose="demo.imagine.nonjson",
            parent_id=_PARENT,
            labels=_LABELS,
        )
    assert str(raised.value) == _IMAGINE_NON_JSON
    assert isinstance(raised.value.__cause__, json.JSONDecodeError)
    _one_failed(
        sink,
        modality="imagine",
        raised=raised.value,
        estimated_usd=sibling_usd,
        purpose="demo.imagine.nonjson",
        model=DEFAULT_IMAGE_MODEL,
    )


def test_xk_ac_meter_3_async_imagine_non_json_records_one_failed_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run() -> None:
        sibling_usd = await _async_http_failure_usd(monkeypatch, "imagine")
        sink = InMemoryUsageSink()
        client = _async_client(sink)
        _install_async(
            monkeypatch,
            _response(200, url=XAI_IMAGES_URL, content=b"not-json"),
        )
        with pytest.raises(RuntimeError, match=rf"^{_IMAGINE_NON_JSON}$") as raised:
            await client.generate_image(
                "a cube",
                purpose="demo.imagine.nonjson",
                parent_id=_PARENT,
                labels=_LABELS,
            )
        assert str(raised.value) == _IMAGINE_NON_JSON
        assert isinstance(raised.value.__cause__, json.JSONDecodeError)
        _one_failed(
            sink,
            modality="imagine",
            raised=raised.value,
            estimated_usd=sibling_usd,
            purpose="demo.imagine.nonjson",
            model=DEFAULT_IMAGE_MODEL,
        )

    asyncio.run(_run())


def _assert_sync_unusable(
    monkeypatch: pytest.MonkeyPatch,
    *,
    kind: str,
    message: str,
    modality: str,
    model: str,
    purpose: str,
    response: httpx.Response,
    call: Any,
    json_cause: bool,
) -> None:
    sibling_usd = _sync_http_failure_usd(monkeypatch, kind)
    sink = InMemoryUsageSink()
    client = _sync_client(sink)
    _install_post(monkeypatch, response)
    with pytest.raises(RuntimeError, match=rf"^{message}$") as raised:
        call(client)
    assert str(raised.value) == message
    if json_cause:
        assert isinstance(raised.value.__cause__, json.JSONDecodeError)
    else:
        assert raised.value.__cause__ is None
    _one_failed(
        sink,
        modality=modality,
        raised=raised.value,
        estimated_usd=sibling_usd,
        purpose=purpose,
        model=model,
    )


async def _assert_async_unusable(
    monkeypatch: pytest.MonkeyPatch,
    *,
    kind: str,
    message: str,
    modality: str,
    model: str,
    purpose: str,
    response: httpx.Response,
    call: Any,
    json_cause: bool,
) -> None:
    sibling_usd = await _async_http_failure_usd(monkeypatch, kind)
    sink = InMemoryUsageSink()
    client = _async_client(sink)
    _install_async(monkeypatch, response)
    with pytest.raises(RuntimeError, match=rf"^{message}$") as raised:
        await call(client)
    assert str(raised.value) == message
    if json_cause:
        assert isinstance(raised.value.__cause__, json.JSONDecodeError)
    else:
        assert raised.value.__cause__ is None
    _one_failed(
        sink,
        modality=modality,
        raised=raised.value,
        estimated_usd=sibling_usd,
        purpose=purpose,
        model=model,
    )


def _extend_sync(client: XaiClient, purpose: str) -> None:
    client.extend_video(
        "a cube",
        video_url="https://example.com/clip.mp4",
        purpose=purpose,
        parent_id=_PARENT,
        labels=_LABELS,
        into=[],
        wait=False,
    )


async def _extend_async(client: AsyncXaiClient, purpose: str) -> None:
    await client.extend_video(
        "a cube",
        video_url="https://example.com/clip.mp4",
        purpose=purpose,
        parent_id=_PARENT,
        labels=_LABELS,
        into=[],
        wait=False,
    )


def _edit_sync(client: XaiClient, purpose: str) -> None:
    client.edit_image(
        "a cube",
        image_url="https://example.com/src.png",
        purpose=purpose,
        parent_id=_PARENT,
        labels=_LABELS,
    )


async def _edit_async(client: AsyncXaiClient, purpose: str) -> None:
    await client.edit_image(
        "a cube",
        image_url="https://example.com/src.png",
        purpose=purpose,
        parent_id=_PARENT,
        labels=_LABELS,
    )


def test_xk_ac_meter_1_sync_extend_video_non_json_records_one_failed_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_sync_unusable(
        monkeypatch,
        kind="extend",
        message=_EXTEND_NON_JSON,
        modality="video",
        model=_EXTEND_MODEL,
        purpose="demo.extend.nonjson",
        response=_response(200, url=XAI_VIDEO_EXTENSIONS_URL, content=b"not-json"),
        call=lambda client: _extend_sync(client, "demo.extend.nonjson"),
        json_cause=True,
    )


def test_xk_ac_meter_1_async_extend_video_non_json_records_one_failed_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(
        _assert_async_unusable(
            monkeypatch,
            kind="extend",
            message=_EXTEND_NON_JSON,
            modality="video",
            model=_EXTEND_MODEL,
            purpose="demo.extend.nonjson",
            response=_response(200, url=XAI_VIDEO_EXTENSIONS_URL, content=b"not-json"),
            call=lambda client: _extend_async(client, "demo.extend.nonjson"),
            json_cause=True,
        )
    )


def test_xk_ac_meter_2_sync_extend_video_json_array_records_one_failed_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_sync_unusable(
        monkeypatch,
        kind="extend",
        message=_EXTEND_UNEXPECTED,
        modality="video",
        model=_EXTEND_MODEL,
        purpose="demo.extend.array",
        response=_response(200, url=XAI_VIDEO_EXTENSIONS_URL, payload=[]),
        call=lambda client: _extend_sync(client, "demo.extend.array"),
        json_cause=False,
    )


def test_xk_ac_meter_2_async_extend_video_json_array_records_one_failed_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(
        _assert_async_unusable(
            monkeypatch,
            kind="extend",
            message=_EXTEND_UNEXPECTED,
            modality="video",
            model=_EXTEND_MODEL,
            purpose="demo.extend.array",
            response=_response(200, url=XAI_VIDEO_EXTENSIONS_URL, payload=[]),
            call=lambda client: _extend_async(client, "demo.extend.array"),
            json_cause=False,
        )
    )


def test_xk_ac_meter_2_sync_extend_video_missing_request_id_records_one_failed_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_sync_unusable(
        monkeypatch,
        kind="extend",
        message=_EXTEND_MISSING,
        modality="video",
        model=_EXTEND_MODEL,
        purpose="demo.extend.noreqid",
        response=_response(200, url=XAI_VIDEO_EXTENSIONS_URL, payload={"status": "pending"}),
        call=lambda client: _extend_sync(client, "demo.extend.noreqid"),
        json_cause=False,
    )


def test_xk_ac_meter_2_async_extend_video_missing_request_id_records_one_failed_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(
        _assert_async_unusable(
            monkeypatch,
            kind="extend",
            message=_EXTEND_MISSING,
            modality="video",
            model=_EXTEND_MODEL,
            purpose="demo.extend.noreqid",
            response=_response(
                200, url=XAI_VIDEO_EXTENSIONS_URL, payload={"status": "pending"}
            ),
            call=lambda client: _extend_async(client, "demo.extend.noreqid"),
            json_cause=False,
        )
    )


def test_xk_ac_meter_2_sync_extend_video_empty_request_id_records_one_failed_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_sync_unusable(
        monkeypatch,
        kind="extend",
        message=_EXTEND_MISSING,
        modality="video",
        model=_EXTEND_MODEL,
        purpose="demo.extend.emptyreq",
        response=_response(200, url=XAI_VIDEO_EXTENSIONS_URL, payload={"request_id": ""}),
        call=lambda client: _extend_sync(client, "demo.extend.emptyreq"),
        json_cause=False,
    )


def test_xk_ac_meter_2_async_extend_video_empty_request_id_records_one_failed_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(
        _assert_async_unusable(
            monkeypatch,
            kind="extend",
            message=_EXTEND_MISSING,
            modality="video",
            model=_EXTEND_MODEL,
            purpose="demo.extend.emptyreq",
            response=_response(
                200, url=XAI_VIDEO_EXTENSIONS_URL, payload={"request_id": ""}
            ),
            call=lambda client: _extend_async(client, "demo.extend.emptyreq"),
            json_cause=False,
        )
    )


def test_xk_ac_meter_3_sync_edit_image_non_json_records_one_failed_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_sync_unusable(
        monkeypatch,
        kind="edit",
        message=_IMAGINE_NON_JSON,
        modality="imagine",
        model=DEFAULT_IMAGE_MODEL,
        purpose="demo.edit.nonjson",
        response=_response(200, url=XAI_IMAGE_EDITS_URL, content=b"not-json"),
        call=lambda client: _edit_sync(client, "demo.edit.nonjson"),
        json_cause=True,
    )


def test_xk_ac_meter_3_async_edit_image_non_json_records_one_failed_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(
        _assert_async_unusable(
            monkeypatch,
            kind="edit",
            message=_IMAGINE_NON_JSON,
            modality="imagine",
            model=DEFAULT_IMAGE_MODEL,
            purpose="demo.edit.nonjson",
            response=_response(200, url=XAI_IMAGE_EDITS_URL, content=b"not-json"),
            call=lambda client: _edit_async(client, "demo.edit.nonjson"),
            json_cause=True,
        )
    )


def test_xk_ac_meter_regression_sync_success_and_401_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video_sink = InMemoryUsageSink()
    video = _sync_client(video_sink)
    _install_post(
        monkeypatch,
        _response(200, url=XAI_VIDEOS_URL, payload={"request_id": "req-ok"}),
    )
    out = video.generate_video(
        "a cube",
        purpose="demo.video",
        parent_id=_PARENT,
        labels=_LABELS,
        into=[],
        wait=False,
    )
    assert out["request_id"] == "req-ok"
    assert out["status"] == "pending"
    _one_success(
        video_sink,
        modality="video",
        purpose="demo.video",
        model=DEFAULT_VIDEO_MODEL,
    )

    image_sink = InMemoryUsageSink()
    image = _sync_client(image_sink)
    _install_post(
        monkeypatch,
        _response(
            200,
            url=XAI_IMAGES_URL,
            payload={"data": [{"url": "https://example.com/img.png"}]},
        ),
    )
    image_out = image.generate_image(
        "a cube",
        purpose="demo.imagine",
        parent_id=_PARENT,
        labels=_LABELS,
    )
    assert image_out["url"] == "https://example.com/img.png"
    _one_success(
        image_sink,
        modality="imagine",
        purpose="demo.imagine",
        model=DEFAULT_IMAGE_MODEL,
    )

    denied_video = InMemoryUsageSink()
    denied_video_client = _sync_client(denied_video)
    _install_post(
        monkeypatch,
        _response(401, url=XAI_VIDEOS_URL, content=b"unauthorized"),
    )
    with pytest.raises(RuntimeError, match="unauthorized"):
        denied_video_client.generate_video(
            "a cube",
            purpose="demo.video.401",
            parent_id=_PARENT,
            labels=_LABELS,
            into=[],
            wait=False,
        )
    assert list(denied_video.iter_events()) == []

    denied_image = InMemoryUsageSink()
    denied_image_client = _sync_client(denied_image)
    _install_post(
        monkeypatch,
        _response(401, url=XAI_IMAGES_URL, content=b"unauthorized"),
    )
    with pytest.raises(RuntimeError, match="unauthorized"):
        denied_image_client.generate_image(
            "a cube",
            purpose="demo.imagine.401",
            parent_id=_PARENT,
            labels=_LABELS,
        )
    assert list(denied_image.iter_events()) == []


def test_xk_ac_meter_regression_async_success_and_401_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run() -> None:
        video_sink = InMemoryUsageSink()
        video = _async_client(video_sink)
        _install_async(
            monkeypatch,
            _response(200, url=XAI_VIDEOS_URL, payload={"request_id": "req-ok"}),
        )
        out = await video.generate_video(
            "a cube",
            purpose="demo.video",
            parent_id=_PARENT,
            labels=_LABELS,
            into=[],
            wait=False,
        )
        assert out["request_id"] == "req-ok"
        assert out["status"] == "pending"
        _one_success(
            video_sink,
            modality="video",
            purpose="demo.video",
            model=DEFAULT_VIDEO_MODEL,
        )

        image_sink = InMemoryUsageSink()
        image = _async_client(image_sink)
        _install_async(
            monkeypatch,
            _response(
                200,
                url=XAI_IMAGES_URL,
                payload={"data": [{"url": "https://example.com/img.png"}]},
            ),
        )
        image_out = await image.generate_image(
            "a cube",
            purpose="demo.imagine",
            parent_id=_PARENT,
            labels=_LABELS,
        )
        assert image_out["url"] == "https://example.com/img.png"
        _one_success(
            image_sink,
            modality="imagine",
            purpose="demo.imagine",
            model=DEFAULT_IMAGE_MODEL,
        )

        denied_video = InMemoryUsageSink()
        denied_video_client = _async_client(denied_video)
        _install_async(
            monkeypatch,
            _response(401, url=XAI_VIDEOS_URL, content=b"unauthorized"),
        )
        with pytest.raises(RuntimeError, match="unauthorized"):
            await denied_video_client.generate_video(
                "a cube",
                purpose="demo.video.401",
                parent_id=_PARENT,
                labels=_LABELS,
                into=[],
                wait=False,
            )
        assert list(denied_video.iter_events()) == []

        denied_image = InMemoryUsageSink()
        denied_image_client = _async_client(denied_image)
        _install_async(
            monkeypatch,
            _response(401, url=XAI_IMAGES_URL, content=b"unauthorized"),
        )
        with pytest.raises(RuntimeError, match="unauthorized"):
            await denied_image_client.generate_image(
                "a cube",
                purpose="demo.imagine.401",
                parent_id=_PARENT,
                labels=_LABELS,
            )
        assert list(denied_image.iter_events()) == []

    asyncio.run(_run())
