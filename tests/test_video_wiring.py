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
        client.generate_video("  ")


def test_generate_video_requires_purpose_when_metered() -> None:
    client = _client(usage_meter=UsageMeter(sink=InMemoryUsageSink()))
    with pytest.raises(ValueError, match="purpose"):
        client.generate_video("a cube", wait=False)


def test_generate_video_rejects_image_and_reference_images() -> None:
    client = _client()
    with pytest.raises(ValueError, match="reference_images"):
        client.generate_video(
            "x",
            image_url="https://example.com/a.png",
            reference_images=[{"url": "https://example.com/b.png"}],
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
        client.generate_video("a cube", purpose="demo.video.fail", wait=False)

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

    client.generate_video("sky", model="grok-imagine-video", wait=False)
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
