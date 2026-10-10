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
    XAI_IMAGES_URL,
    XAI_VIDEOS_URL,
    XaiClient,
    default_retry_policy,
)

_JSON_ERROR = "JSONDecodeError: Expecting value: line 1 column 1 (char 0)"
_VIDEO_NON_JSON = "Video generation returned non-JSON response"
_VIDEO_UNEXPECTED = "Video generation returned unexpected payload"
_VIDEO_MISSING = "Video generation response missing request_id"
_IMAGINE_NON_JSON = "Imagine returned non-JSON response"
_UNEXPECTED_ERROR = f"RuntimeError: {_VIDEO_UNEXPECTED}"
_MISSING_ERROR = f"RuntimeError: {_VIDEO_MISSING}"
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


def _one_failed(
    sink: InMemoryUsageSink,
    *,
    modality: str,
    error: str,
    purpose: str,
    model: str,
) -> None:
    events = list(sink.iter_events())
    assert len(events) == 1, f"expected 1 failed event, recorded {len(events)}"
    ev = events[0]
    assert ev.success is False
    assert ev.modality == modality
    assert ev.error == error
    assert ev.purpose == purpose
    assert ev.parent_id == _PARENT
    assert ev.labels == _LABELS
    assert ev.model == model


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
        error=_JSON_ERROR,
        purpose="demo.video.nonjson",
        model=DEFAULT_VIDEO_MODEL,
    )


def test_xk_ac_meter_1_async_video_non_json_records_one_failed_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run() -> None:
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
            error=_JSON_ERROR,
            purpose="demo.video.nonjson",
            model=DEFAULT_VIDEO_MODEL,
        )

    asyncio.run(_run())


def test_xk_ac_meter_2_sync_video_json_array_records_one_failed_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        error=_UNEXPECTED_ERROR,
        purpose="demo.video.array",
        model=DEFAULT_VIDEO_MODEL,
    )


def test_xk_ac_meter_2_async_video_json_array_records_one_failed_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run() -> None:
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
            error=_UNEXPECTED_ERROR,
            purpose="demo.video.array",
            model=DEFAULT_VIDEO_MODEL,
        )

    asyncio.run(_run())


def test_xk_ac_meter_2_sync_video_object_missing_request_id_records_one_failed_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        error=_MISSING_ERROR,
        purpose="demo.video.noreqid",
        model=DEFAULT_VIDEO_MODEL,
    )


def test_xk_ac_meter_2_async_video_object_missing_request_id_records_one_failed_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run() -> None:
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
            error=_MISSING_ERROR,
            purpose="demo.video.noreqid",
            model=DEFAULT_VIDEO_MODEL,
        )

    asyncio.run(_run())


def test_xk_ac_meter_2_sync_video_empty_request_id_records_one_failed_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        error=_MISSING_ERROR,
        purpose="demo.video.emptyreq",
        model=DEFAULT_VIDEO_MODEL,
    )


def test_xk_ac_meter_2_async_video_empty_request_id_records_one_failed_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run() -> None:
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
            error=_MISSING_ERROR,
            purpose="demo.video.emptyreq",
            model=DEFAULT_VIDEO_MODEL,
        )

    asyncio.run(_run())


def test_xk_ac_meter_3_sync_imagine_non_json_records_one_failed_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        error=_JSON_ERROR,
        purpose="demo.imagine.nonjson",
        model=DEFAULT_IMAGE_MODEL,
    )


def test_xk_ac_meter_3_async_imagine_non_json_records_one_failed_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run() -> None:
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
            error=_JSON_ERROR,
            purpose="demo.imagine.nonjson",
            model=DEFAULT_IMAGE_MODEL,
        )

    asyncio.run(_run())


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
