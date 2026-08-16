"""Contract tests: Imagine video REST wiring (URL, auth, body, poll, metering)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from xaikit import (
    DEFAULT_VIDEO_MODEL,
    InMemoryUsageSink,
    MockChatProvider,
    UsageMeter,
    XAI_VIDEO_EXTENSIONS_URL,
    XAI_VIDEO_STATUS_URL,
    XAI_VIDEOS_URL,
    XaiClient,
    default_price_table,
    default_retry_policy,
    prefer_latest_video_model,
)
from xaikit.types import ModelInfo


def _client(*, usage_meter: UsageMeter | None = None, **kwargs: Any) -> XaiClient:
    return XaiClient(
        provider=MockChatProvider(),
        model="grok-3-mini",
        api_key="test-key",
        usage_meter=usage_meter,
        retry_policy=default_retry_policy(max_attempts=1),
        **kwargs,
    )


def _json_response(
    method: str,
    url: str,
    status_code: int,
    payload: dict[str, Any] | None = None,
    content: bytes | None = None,
) -> httpx.Response:
    kwargs: dict[str, Any] = {
        "status_code": status_code,
        "request": httpx.Request(method, url),
    }
    if content is not None:
        kwargs["content"] = content
    else:
        kwargs["json"] = payload if payload is not None else {}
    return httpx.Response(**kwargs)


class _HttpCapture:
    def __init__(self) -> None:
        self.posts: list[dict[str, Any]] = []
        self.gets: list[dict[str, Any]] = []

    def install_post(
        self,
        monkeypatch: pytest.MonkeyPatch,
        response: httpx.Response,
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

    def install_gets(
        self,
        monkeypatch: pytest.MonkeyPatch,
        responses: list[httpx.Response],
    ) -> None:
        idx = {"n": 0}

        def _get(url: str, **kwargs: Any) -> httpx.Response:
            self.gets.append({"url": url, **kwargs})
            i = idx["n"]
            idx["n"] = i + 1
            response = responses[min(i, len(responses) - 1)]
            if response.request is not None:
                return response
            return httpx.Response(
                response.status_code,
                headers=response.headers,
                content=response.content,
                request=httpx.Request("GET", url),
            )

        monkeypatch.setattr("xaikit.client.httpx.get", _get)


def test_generate_video_t2v_posts_url_auth_and_json_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    meter = UsageMeter(sink=sink)
    client = _client(usage_meter=meter)
    cap = _HttpCapture()
    cap.install_post(
        monkeypatch,
        _json_response(
            "POST",
            XAI_VIDEOS_URL,
            200,
            {"request_id": "req-t2v"},
        ),
    )

    out = client.generate_video(
        "  a red cube spinning  ",
        duration=8,
        aspect_ratio="16:9",
        resolution="720p",
        into=[],
        wait=False,
        purpose="demo.video",
        parent_id="p1",
        labels={"request_id": "v1"},
    )

    assert out["request_id"] == "req-t2v"
    assert out["status"] == "pending"
    assert len(cap.posts) == 1
    call = cap.posts[0]
    assert call["url"] == XAI_VIDEOS_URL
    assert call["headers"]["Authorization"] == "Bearer test-key"
    assert call["json"] == {
        "model": DEFAULT_VIDEO_MODEL,
        "prompt": "a red cube spinning",
        "duration": 8,
        "aspect_ratio": "16:9",
        "resolution": "720p",
    }
    assert call["timeout"] == 60.0

    ev = list(sink.iter_events())[0]
    assert ev.purpose == "demo.video"
    assert ev.modality == "video"
    assert ev.model == DEFAULT_VIDEO_MODEL
    assert ev.success is True
    assert ev.parent_id == "p1"
    assert ev.labels["request_id"] == "v1"


def test_generate_video_rejects_empty_prompt_without_http() -> None:
    client = _client()
    with pytest.raises(RuntimeError, match="empty"):
        client.generate_video("  ", into=[])


def test_generate_video_requires_purpose_when_metered() -> None:
    client = _client(usage_meter=UsageMeter(sink=InMemoryUsageSink()))
    with pytest.raises(ValueError, match="purpose"):
        client.generate_video("a cube", into=[], wait=False)


def test_generate_video_rejects_image_and_reference_images() -> None:
    client = _client()
    with pytest.raises(ValueError, match="reference_images"):
        client.generate_video(
            "x",
            image_url="https://example.com/a.png",
            reference_images=[{"url": "https://example.com/b.png"}],
            into=[],
        wait=False,
        )


def test_generate_video_i2v_sends_image_url_and_may_omit_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _HttpCapture()
    cap.install_post(
        monkeypatch,
        _json_response("POST", XAI_VIDEOS_URL, 200, {"request_id": "req-i2v"}),
    )

    client.generate_video(
        image_url="https://example.com/still.png",
        into=[],
        wait=False,
    )

    body = cap.posts[0]["json"]
    assert body["image"] == {"url": "https://example.com/still.png"}
    assert "prompt" not in body
    assert "reference_images" not in body


def test_generate_video_r2v_sends_reference_images_and_audios(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _HttpCapture()
    cap.install_post(
        monkeypatch,
        _json_response("POST", XAI_VIDEOS_URL, 200, {"request_id": "req-r2v"}),
    )

    client.generate_video(
        "walk the runway",
        reference_images=[{"url": "https://example.com/ref.png"}],
        reference_audios=[{"voice_id": "eve"}],
        into=[],
        wait=False,
    )

    body = cap.posts[0]["json"]
    assert body["prompt"] == "walk the runway"
    assert body["reference_images"] == [{"url": "https://example.com/ref.png"}]
    assert body["reference_audios"] == [{"voice_id": "eve"}]
    assert "image" not in body


def test_extend_video_posts_extensions_url_with_video_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _HttpCapture()
    cap.install_post(
        monkeypatch,
        _json_response(
            "POST",
            XAI_VIDEO_EXTENSIONS_URL,
            200,
            {"request_id": "req-ext"},
        ),
    )

    out = client.extend_video(
        "zoom out to the skyline",
        video_url="https://example.com/clip.mp4",
        duration=6,
        into=[],
        wait=False,
    )

    assert out["request_id"] == "req-ext"
    call = cap.posts[0]
    assert call["url"] == XAI_VIDEO_EXTENSIONS_URL
    assert call["headers"]["Authorization"] == "Bearer test-key"
    assert call["json"] == {
        "model": DEFAULT_VIDEO_MODEL,
        "prompt": "zoom out to the skyline",
        "video": {"url": "https://example.com/clip.mp4"},
        "duration": 6,
    }
    assert "resolution" not in call["json"]
    assert "aspect_ratio" not in call["json"]


def test_generate_video_wait_polls_pending_then_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("xaikit.client.time.sleep", lambda *_a, **_k: None)
    sink = InMemoryUsageSink()
    meter = UsageMeter(sink=sink)
    client = _client(usage_meter=meter)
    cap = _HttpCapture()
    cap.install_post(
        monkeypatch,
        _json_response("POST", XAI_VIDEOS_URL, 200, {"request_id": "req-wait"}),
    )
    status_url = XAI_VIDEO_STATUS_URL.format(request_id="req-wait")
    cap.install_gets(
        monkeypatch,
        [
            _json_response("GET", status_url, 200, {"status": "pending"}),
            _json_response(
                "GET",
                status_url,
                200,
                {
                    "status": "done",
                    "video": {
                        "url": "https://example.com/out.mp4",
                        "duration": 8,
                        "respect_moderation": True,
                    },
                    "model": DEFAULT_VIDEO_MODEL,
                    "usage": {"cost_in_usd_ticks": 800_000_000},
                },
            ),
        ],
    )

    out = client.generate_video(
        "a cube",
        into=[],
        wait=True,
        interval=0,
        purpose="demo.video.wait",
    )

    assert out["url"] == "https://example.com/out.mp4"
    assert out["status"] == "done"
    assert out["request_id"] == "req-wait"
    assert out["duration"] == 8
    assert out["respect_moderation"] is True
    assert len(cap.gets) == 2
    assert cap.gets[0]["url"] == status_url
    assert cap.gets[0]["headers"]["Authorization"] == "Bearer test-key"

    ev = list(sink.iter_events())[0]
    assert ev.purpose == "demo.video.wait"
    assert ev.modality == "video"
    assert ev.success is True
    assert ev.estimated_usd == pytest.approx(0.08)


def test_poll_video_gets_status_path_and_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client()
    cap = _HttpCapture()
    status_url = XAI_VIDEO_STATUS_URL.format(request_id="abc-123")
    cap.install_gets(
        monkeypatch,
        [
            _json_response(
                "GET",
                status_url,
                200,
                {"status": "pending", "progress": 10},
            )
        ],
    )

    out = client.poll_video("abc-123")

    assert out["status"] == "pending"
    assert out["request_id"] == "abc-123"
    assert cap.gets[0]["url"] == status_url
    assert cap.gets[0]["headers"]["Authorization"] == "Bearer test-key"


def test_video_http_error_records_failed_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    sink = InMemoryUsageSink()
    meter = UsageMeter(sink=sink)
    client = _client(usage_meter=meter)

    def _boom(*_a: Any, **_k: Any) -> httpx.Response:
        raise httpx.ConnectError("offline")

    monkeypatch.setattr("xaikit.client.httpx.post", _boom)
    with pytest.raises(RuntimeError, match="Video generation request failed"):
        client.generate_video("a cube", purpose="demo.video.fail", into=[], wait=False)

    ev = list(sink.iter_events())[0]
    assert ev.success is False
    assert ev.modality == "video"
    assert ev.purpose == "demo.video.fail"


def test_download_video_gets_url_and_returns_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _HttpCapture()
    cap.install_gets(
        monkeypatch,
        [_json_response("GET", "https://example.com/out.mp4", 200, content=b"mp4bytes")],
    )

    data = client.download_video("https://example.com/out.mp4")

    assert data == b"mp4bytes"
    assert cap.gets[0]["url"] == "https://example.com/out.mp4"
    assert "Authorization" not in (cap.gets[0].get("headers") or {})


def test_download_video_rejects_empty_url() -> None:
    client = _client()
    with pytest.raises(RuntimeError, match="empty"):
        client.download_video("  ")


def test_generate_video_default_model_constant() -> None:
    client = _client()
    assert client.video_model == DEFAULT_VIDEO_MODEL
    assert DEFAULT_VIDEO_MODEL == "grok-imagine-video-1.5"


def test_generate_video_per_call_model_override(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(video_model="client-default-video")
    cap = _HttpCapture()
    cap.install_post(
        monkeypatch,
        _json_response("POST", XAI_VIDEOS_URL, 200, {"request_id": "req-ov"}),
    )

    client.generate_video("sky", model="grok-imagine-video", into=[], wait=False)
    assert cap.posts[0]["json"]["model"] == "grok-imagine-video"


def test_prefer_latest_video_model_picks_newest_imagine_id() -> None:
    cat = [
        ModelInfo(id="grok-4.5", capabilities=["chat"], created=9),
        ModelInfo(id="grok-imagine-video", capabilities=["video"], created=1),
        ModelInfo(id="grok-imagine-video-1.5", capabilities=["video"], created=2),
    ]
    assert prefer_latest_video_model(cat) == "grok-imagine-video-1.5"
    assert prefer_latest_video_model([]) == DEFAULT_VIDEO_MODEL
    assert prefer_latest_video_model(None) == DEFAULT_VIDEO_MODEL


def test_prefer_latest_video_model_does_not_change_chat_resolve() -> None:
    from xaikit.catalog import prefer_latest_model, resolve_model_selection

    cat = [
        ModelInfo(id="grok-4.5", capabilities=["chat"], created=2),
        ModelInfo(id="grok-imagine-video-1.5", capabilities=["video"], created=99),
    ]
    assert prefer_latest_model(cat) == "grok-4.5"
    sel = resolve_model_selection(catalog=cat)
    assert sel.model_id == "grok-4.5"


def test_default_price_table_video_per_second_rates() -> None:
    table = default_price_table()
    v15 = table.price_for("grok-imagine-video-1.5")
    assert v15.per_second_usd == 0.08
    assert table.estimate_usd(
        "grok-imagine-video-1.5", duration_seconds=8, resolution="480p"
    ) == pytest.approx(0.64)
    assert table.estimate_usd(
        "grok-imagine-video-1.5", duration_seconds=1, resolution="1080p"
    ) == pytest.approx(0.25)
    base = table.price_for("grok-imagine-video")
    assert base.per_second_usd == 0.05
    assert table.estimate_usd(
        "grok-imagine-video", duration_seconds=1, resolution="720p"
    ) == pytest.approx(0.07)


def test_contract_video_resolution_matrix() -> None:
    from xaikit.client import _contract_video_resolution

    assert (
        _contract_video_resolution("1080p", "grok-imagine-video-1.5") == "1080p"
    )
    assert (
        _contract_video_resolution(
            "1080p", "grok-imagine-video-1.5", is_r2v=True
        )
        == "720p"
    )
    assert _contract_video_resolution("1080p", "grok-imagine-video") == "720p"
    assert (
        _contract_video_resolution("720p", "grok-imagine-video", is_r2v=True)
        == "720p"
    )
    assert _contract_video_resolution("480p", "grok-imagine-video-1.5") == "480p"
    assert _contract_video_resolution(None, "grok-imagine-video-1.5") is None
    with pytest.raises(ValueError, match="resolution"):
        _contract_video_resolution("4k", "grok-imagine-video-1.5")


def test_generate_video_1_5_t2v_keeps_1080p(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client()
    cap = _HttpCapture()
    cap.install_post(
        monkeypatch,
        _json_response("POST", XAI_VIDEOS_URL, 200, {"request_id": "req-1080-t2v"}),
    )

    client.generate_video("a cube", resolution="1080p", into=[], wait=False)

    assert cap.posts[0]["json"]["model"] == DEFAULT_VIDEO_MODEL
    assert cap.posts[0]["json"]["resolution"] == "1080p"


def test_generate_video_1_5_i2v_keeps_1080p(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client()
    cap = _HttpCapture()
    cap.install_post(
        monkeypatch,
        _json_response("POST", XAI_VIDEOS_URL, 200, {"request_id": "req-1080-i2v"}),
    )

    client.generate_video(
        image_url="https://example.com/still.png",
        resolution="1080p",
        into=[],
        wait=False,
    )

    body = cap.posts[0]["json"]
    assert body["image"] == {"url": "https://example.com/still.png"}
    assert body["resolution"] == "1080p"


def test_generate_video_1_5_r2v_contracts_1080p_to_720p(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _HttpCapture()
    cap.install_post(
        monkeypatch,
        _json_response("POST", XAI_VIDEOS_URL, 200, {"request_id": "req-1080-r2v"}),
    )

    client.generate_video(
        "walk the runway",
        resolution="1080p",
        reference_images=[{"url": "https://example.com/ref.png"}],
        into=[],
        wait=False,
    )

    body = cap.posts[0]["json"]
    assert body["reference_images"] == [{"url": "https://example.com/ref.png"}]
    assert body["resolution"] == "720p"


def test_generate_video_older_t2v_contracts_1080p_to_720p(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _HttpCapture()
    cap.install_post(
        monkeypatch,
        _json_response("POST", XAI_VIDEOS_URL, 200, {"request_id": "req-1080-old"}),
    )

    client.generate_video(
        "a cube",
        model="grok-imagine-video",
        resolution="1080p",
        into=[],
        wait=False,
    )

    body = cap.posts[0]["json"]
    assert body["model"] == "grok-imagine-video"
    assert body["resolution"] == "720p"


def test_generate_video_rejects_unknown_resolution_without_http() -> None:
    client = _client()
    with pytest.raises(ValueError, match="resolution"):
        client.generate_video("a cube", resolution="4k", into=[], wait=False)


def test_async_generate_video_contracts_1080p_like_sync(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from xaikit import AsyncXaiClient

    class _AsyncHttpCapture:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def install(self) -> None:
            capture = self

            class FakeAsyncClient:
                def __init__(self, *args: Any, **kwargs: Any) -> None:
                    pass

                async def __aenter__(self) -> FakeAsyncClient:
                    return self

                async def __aexit__(self, *args: Any) -> bool:
                    return False

                async def request(
                    self, method: str, url: str, **kwargs: Any
                ) -> httpx.Response:
                    capture.calls.append({"method": method, "url": url, **kwargs})
                    return httpx.Response(
                        200,
                        json={"request_id": "req-async-1080"},
                        request=httpx.Request(method, url),
                    )

            monkeypatch.setattr(
                "xaikit.async_client.httpx.AsyncClient", FakeAsyncClient
            )

    async def _run() -> None:
        client = AsyncXaiClient(
            provider=MockChatProvider(),
            model="grok-3-mini",
            api_key="test-key",
            retry_policy=default_retry_policy(max_attempts=1, backoff_seconds=0.0),
        )
        cap = _AsyncHttpCapture()
        cap.install()

        await client.generate_video("a cube", resolution="1080p", into=[], wait=False)
        assert cap.calls[0]["json"]["resolution"] == "1080p"

        cap.calls.clear()
        await client.generate_video(
            "walk",
            resolution="1080p",
            reference_images=[{"url": "https://example.com/ref.png"}],
            into=[],
        wait=False,
        )
        assert cap.calls[0]["json"]["resolution"] == "720p"

        cap.calls.clear()
        await client.generate_video(
            "a cube",
            model="grok-imagine-video",
            resolution="1080p",
            into=[],
        wait=False,
        )
        assert cap.calls[0]["json"]["resolution"] == "720p"

        cap.calls.clear()
        await client.extend_video(
            "zoom out",
            video_url="https://example.com/clip.mp4",
            into=[],
        wait=False,
        )
        ext = cap.calls[0]["json"]
        assert "resolution" not in ext
        assert "aspect_ratio" not in ext

    asyncio.run(_run())


def test_generate_video_requires_into() -> None:
    client = _client()
    with pytest.raises(TypeError, match="into"):
        client.generate_video("a cube", wait=False)  # type: ignore[call-arg]


def test_generate_video_delivers_pending_then_done_to_inbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from xaikit import VideoInbox

    monkeypatch.setattr("xaikit.client.time.sleep", lambda *_a, **_k: None)
    client = _client()
    cap = _HttpCapture()
    cap.install_post(
        monkeypatch,
        _json_response("POST", XAI_VIDEOS_URL, 200, {"request_id": "req-inbox"}),
    )
    status_url = XAI_VIDEO_STATUS_URL.format(request_id="req-inbox")
    cap.install_gets(
        monkeypatch,
        [
            _json_response("GET", status_url, 200, {"status": "pending"}),
            _json_response(
                "GET",
                status_url,
                200,
                {
                    "status": "done",
                    "video": {"url": "https://example.com/out.mp4", "duration": 4},
                },
            ),
        ],
    )
    inbox = VideoInbox()
    out = client.generate_video("a cube", into=inbox, wait=True, interval=0)
    assert out["request_id"] == "req-inbox"
    assert inbox.request_ids == ["req-inbox"]
    assert [r.status for r in inbox.receipts] == ["pending", "done"]
    assert inbox.latest("req-inbox") is not None
    assert inbox.latest("req-inbox").payload["url"] == "https://example.com/out.mp4"


def test_async_sibling_failure_still_delivers_other_video(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from xaikit import AsyncXaiClient, VideoInbox

    class FakeAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> FakeAsyncClient:
            return self

        async def __aexit__(self, *args: Any) -> bool:
            return False

        async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
            body = kwargs.get("json") or {}
            prompt = str(body.get("prompt") or "")
            if method == "POST":
                rid = "req-fail" if prompt == "fail" else "req-ok"
                return httpx.Response(
                    200,
                    json={"request_id": rid},
                    request=httpx.Request(method, url),
                )
            if url.endswith("/req-fail"):
                return httpx.Response(
                    200,
                    json={"status": "failed", "error": "moderation"},
                    request=httpx.Request(method, url),
                )
            return httpx.Response(
                200,
                json={
                    "status": "done",
                    "video": {"url": "https://example.com/ok.mp4", "duration": 3},
                },
                request=httpx.Request(method, url),
            )

    monkeypatch.setattr("xaikit.async_client.httpx.AsyncClient", FakeAsyncClient)

    async def _run() -> None:
        client = AsyncXaiClient(
            provider=MockChatProvider(),
            model="grok-3-mini",
            api_key="test-key",
            retry_policy=default_retry_policy(max_attempts=1, backoff_seconds=0.0),
        )
        inbox = VideoInbox()
        with pytest.raises(RuntimeError, match="failed"):
            await asyncio.gather(
                client.generate_video(
                    "fail", into=inbox, wait=True, interval=0, timeout=5
                ),
                client.generate_video(
                    "ok", into=inbox, wait=True, interval=0, timeout=5
                ),
            )
        leftover = list(client._inflight_video_waits)
        if leftover:
            await asyncio.gather(*leftover, return_exceptions=True)
        assert "req-fail" in inbox.request_ids
        assert "req-ok" in inbox.request_ids
        assert inbox.latest("req-ok") is not None
        assert inbox.latest("req-ok").status == "done"
        assert inbox.latest("req-fail") is not None
        assert inbox.latest("req-fail").status == "failed"

    asyncio.run(_run())


def test_video_inbox_cancel_stops_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from xaikit import AsyncXaiClient, VideoInbox

    polls = {"n": 0}

    class FakeAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> FakeAsyncClient:
            return self

        async def __aexit__(self, *args: Any) -> bool:
            return False

        async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
            if method == "POST":
                return httpx.Response(
                    200,
                    json={"request_id": "req-cancel"},
                    request=httpx.Request(method, url),
                )
            polls["n"] += 1
            return httpx.Response(
                200,
                json={"status": "pending"},
                request=httpx.Request(method, url),
            )

    monkeypatch.setattr("xaikit.async_client.httpx.AsyncClient", FakeAsyncClient)

    async def _run() -> None:
        client = AsyncXaiClient(
            provider=MockChatProvider(),
            model="grok-3-mini",
            api_key="test-key",
            retry_policy=default_retry_policy(max_attempts=1, backoff_seconds=0.0),
        )
        inbox = VideoInbox()
        task = asyncio.create_task(
            client.generate_video(
                "stay pending", into=inbox, wait=True, interval=0.01, timeout=30
            )
        )
        for _ in range(50):
            if inbox.request_ids:
                break
            await asyncio.sleep(0.01)
        assert inbox.request_ids == ["req-cancel"]
        inbox.cancel("req-cancel")
        with pytest.raises(RuntimeError, match="cancelled"):
            await task
        assert inbox.latest("req-cancel") is not None
        assert inbox.latest("req-cancel").status == "cancelled"

    asyncio.run(_run())
