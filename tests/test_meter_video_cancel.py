"""Cancelling a video wait records exactly one usage event.

XK-AC-METER-4. HTTP is mocked at ``httpx.post`` / ``httpx.get`` (sync) or
``httpx.AsyncClient`` (async). The usage sink is a real ``InMemoryUsageSink``.

Terminal rows (done, failed, expired, timeout, poll HTTP error) pin the
events the wait loop already records. They pass before the cancel change.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from xaikit import (
    DEFAULT_VIDEO_MODEL,
    AsyncXaiClient,
    InMemoryUsageSink,
    MockChatProvider,
    UsageMeter,
    VideoInbox,
    VideoReceipt,
    XAI_VIDEO_EXTENSIONS_URL,
    XAI_VIDEOS_URL,
    XaiClient,
    default_retry_policy,
)
from xaikit.usage import UsageEvent

_PURPOSE = "demo.video"
_PARENT = "p1"
_LABELS = {"request_id": "v1"}
_RID = "req-meter"
_EXTEND_MODEL = "grok-imagine-video"
_POLL_HTTP_ERROR = "RuntimeError: Video poll failed (500): boom"


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


def _view(event: UsageEvent) -> dict[str, Any]:
    raw = event.model_dump(mode="python")
    raw.pop("timestamp", None)
    return raw


def _event(
    *,
    success: bool,
    error: str | None,
    estimated_usd: float | None,
    model: str = DEFAULT_VIDEO_MODEL,
    purpose: str = _PURPOSE,
    parent_id: str = _PARENT,
    labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "purpose": purpose,
        "model": model,
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "estimated_usd": estimated_usd,
        "parent_id": parent_id,
        "labels": dict(_LABELS if labels is None else labels),
        "success": success,
        "thought_level": None,
        "error": error,
        "modality": "video",
    }


# 8s at 720p on grok-imagine-video-1.5. 8 * 0.14.
_GENERATE_CANCEL_USD = 1.12
# 4s and no resolution on grok-imagine-video. Default per-second rate.
_EXTEND_CANCEL_USD = 0.2


def _cancelled_event(*, estimated_usd: float, **overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "success": False,
        "error": "video_cancelled",
        "estimated_usd": estimated_usd,
    }
    fields.update(overrides)
    return _event(**fields)


class _CancelOnPending(VideoInbox):
    """Cancel when the pending receipt arrives, before the wait polls."""

    def __init__(self, repeats: int = 1) -> None:
        super().__init__()
        self.repeats = repeats

    def deliver(self, receipt: VideoReceipt) -> None:
        super().deliver(receipt)
        if receipt.status != "pending":
            return
        for _ in range(self.repeats):
            self.cancel(receipt.request_id)


class _CancelOnDone(VideoInbox):
    """Cancel while the done receipt is delivered, after the success record."""

    def deliver(self, receipt: VideoReceipt) -> None:
        super().deliver(receipt)
        if receipt.status == "done":
            self.cancel(receipt.request_id)


class _Script:
    def __init__(
        self,
        polls: list[Any],
        *,
        request_id: str = _RID,
        on_get: Any = None,
    ) -> None:
        self.polls = list(polls)
        self.request_id = request_id
        self.on_get = on_get
        self.posts: list[dict[str, Any]] = []
        self.gets: list[str] = []

    def install_sync(self, monkeypatch: pytest.MonkeyPatch) -> None:
        script = self

        def _post(url: str, **kwargs: Any) -> httpx.Response:
            script.posts.append({"url": url, "json": kwargs.get("json")})
            return httpx.Response(
                200,
                json={"request_id": script.request_id},
                request=httpx.Request("POST", url),
            )

        def _get(url: str, **kwargs: Any) -> httpx.Response:
            return script._poll(url)

        monkeypatch.setattr("xaikit.client.httpx.post", _post)
        monkeypatch.setattr("xaikit.client.httpx.get", _get)

    def install_async(self, monkeypatch: pytest.MonkeyPatch) -> None:
        script = self

        class FakeAsyncClient:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            async def __aenter__(self) -> FakeAsyncClient:
                return self

            async def __aexit__(self, *args: Any) -> bool:
                return False

            async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
                if method == "POST":
                    script.posts.append({"url": url, "json": kwargs.get("json")})
                    return httpx.Response(
                        200,
                        json={"request_id": script.request_id},
                        request=httpx.Request("POST", url),
                    )
                return script._poll(url)

        monkeypatch.setattr("xaikit.async_client.httpx.AsyncClient", FakeAsyncClient)

    def _poll(self, url: str) -> httpx.Response:
        self.gets.append(url)
        if self.on_get is not None:
            self.on_get(len(self.gets))
        if not self.polls:
            body: Any = {"status": "pending"}
        else:
            body = self.polls.pop(0)
        if isinstance(body, int):
            return httpx.Response(
                body,
                content=b"boom",
                request=httpx.Request("GET", url),
            )
        return httpx.Response(
            200,
            json=body,
            request=httpx.Request("GET", url),
        )


def _views(sink: InMemoryUsageSink) -> list[dict[str, Any]]:
    return [_view(event) for event in sink.iter_events()]


def _generate(client: XaiClient, into: Any, **kwargs: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "purpose": _PURPOSE,
        "parent_id": _PARENT,
        "labels": _LABELS,
        "into": into,
        "wait": True,
        "interval": 0,
        "timeout": 30,
        "duration": 8,
        "resolution": "720p",
    }
    fields.update(kwargs)
    return client.generate_video("a cube", **fields)


def _extend(client: XaiClient, into: Any, **kwargs: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "purpose": _PURPOSE,
        "parent_id": _PARENT,
        "labels": _LABELS,
        "into": into,
        "wait": True,
        "interval": 0,
        "timeout": 30,
        "duration": 4,
        "video_url": "https://example.com/clip.mp4",
    }
    fields.update(kwargs)
    return client.extend_video("keep going", **fields)


_DONE_BODY = {
    "status": "done",
    "model": DEFAULT_VIDEO_MODEL,
    "video": {"url": "https://example.com/out.mp4", "duration": 8},
    "usage": {"cost_in_usd_ticks": 800_000_000},
}
_FAILED_BODY = {
    "status": "failed",
    "model": "other-model",
    "error": {"message": "moderation"},
}
_EXPIRED_BODY = {"status": "expired", "error": "expired"}

# Priced from the poll payload ticks (done) or from duration x resolution
# (failed, expired). Timeout and poll HTTP error attach no usage.
_TERMINALS: dict[str, dict[str, Any]] = {
    "done": {
        "polls": [_DONE_BODY],
        "call": {"duration": 8, "resolution": "720p", "timeout": 30},
        "raises": None,
        "event": _event(success=True, error=None, estimated_usd=0.08),
    },
    "failed": {
        "polls": [_FAILED_BODY],
        "call": {"duration": 4, "resolution": "720p", "timeout": 30},
        "raises": "failed",
        "event": _event(success=False, error="video_failed", estimated_usd=0.56),
    },
    "expired": {
        "polls": [_EXPIRED_BODY],
        "call": {"duration": 5, "resolution": "720p", "timeout": 30},
        "raises": "expired",
        "event": _event(success=False, error="video_expired", estimated_usd=0.7),
    },
    "timeout": {
        "polls": [{"status": "pending"}],
        "call": {"duration": 8, "resolution": "720p", "timeout": 0},
        "raises": "timed out",
        "event": _event(success=False, error="video_timeout", estimated_usd=None),
    },
    "poll_http": {
        "polls": [500],
        "call": {"duration": 8, "resolution": "720p", "timeout": 30},
        "raises": "Video poll failed",
        "event": _event(success=False, error=_POLL_HTTP_ERROR, estimated_usd=None),
    },
}


@pytest.mark.parametrize("client_kind", ["sync", "async"])
@pytest.mark.parametrize("terminal", list(_TERMINALS))
def test_wait_terminal_usage_event_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    client_kind: str,
    terminal: str,
) -> None:
    spec = _TERMINALS[terminal]
    sink = InMemoryUsageSink()
    script = _Script(spec["polls"])
    if client_kind == "sync":
        script.install_sync(monkeypatch)
        client: XaiClient = _sync_client(sink)
        if spec["raises"] is None:
            out = _generate(client, [], **spec["call"])
            assert out["status"] == "done"
            assert out["request_id"] == _RID
        else:
            with pytest.raises(RuntimeError, match=spec["raises"]):
                _generate(client, [], **spec["call"])
    else:
        script.install_async(monkeypatch)

        async def _run() -> None:
            client_async = _async_client(sink)
            if spec["raises"] is None:
                out = await _generate(client_async, [], **spec["call"])
                assert out["status"] == "done"
                assert out["request_id"] == _RID
            else:
                with pytest.raises(RuntimeError, match=spec["raises"]):
                    await _generate(client_async, [], **spec["call"])

        asyncio.run(_run())

    assert len(script.posts) == 1
    assert script.posts[0]["url"] == XAI_VIDEOS_URL
    assert _views(sink) == [spec["event"]]


def test_sync_cancel_before_poll_records_one_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    script = _Script([])
    script.install_sync(monkeypatch)
    inbox = _CancelOnPending()
    with pytest.raises(RuntimeError, match=f"Video generation cancelled: request_id={_RID}"):
        _generate(_sync_client(sink), inbox, duration=8, resolution="720p")
    assert len(script.posts) == 1
    assert script.gets == []
    assert _views(sink) == [_cancelled_event(estimated_usd=_GENERATE_CANCEL_USD)]
    assert inbox.latest(_RID) is not None
    assert inbox.latest(_RID).status == "cancelled"


def test_async_cancel_before_poll_records_one_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    script = _Script([])
    script.install_async(monkeypatch)

    async def _run() -> None:
        inbox = _CancelOnPending()
        with pytest.raises(
            RuntimeError, match=f"Video generation cancelled: request_id={_RID}"
        ):
            await _generate(_async_client(sink), inbox, duration=8, resolution="720p")
        assert inbox.latest(_RID) is not None
        assert inbox.latest(_RID).status == "cancelled"

    asyncio.run(_run())
    assert len(script.posts) == 1
    assert script.gets == []
    assert _views(sink) == [_cancelled_event(estimated_usd=_GENERATE_CANCEL_USD)]


def test_sync_double_cancel_records_one_event(monkeypatch: pytest.MonkeyPatch) -> None:
    sink = InMemoryUsageSink()
    script = _Script([])
    script.install_sync(monkeypatch)
    inbox = _CancelOnPending(repeats=2)
    with pytest.raises(RuntimeError, match="cancelled"):
        _generate(_sync_client(sink), inbox, duration=8, resolution="720p")
    assert script.gets == []
    assert _views(sink) == [_cancelled_event(estimated_usd=_GENERATE_CANCEL_USD)]


def test_sync_extend_cancel_records_one_event(monkeypatch: pytest.MonkeyPatch) -> None:
    sink = InMemoryUsageSink()
    script = _Script([])
    script.install_sync(monkeypatch)
    inbox = _CancelOnPending()
    with pytest.raises(RuntimeError, match=f"Video extension cancelled: request_id={_RID}"):
        _extend(_sync_client(sink), inbox)
    assert len(script.posts) == 1
    assert script.posts[0]["url"] == XAI_VIDEO_EXTENSIONS_URL
    assert script.posts[0]["json"]["model"] == _EXTEND_MODEL
    assert script.gets == []
    assert _views(sink) == [
        _cancelled_event(estimated_usd=_EXTEND_CANCEL_USD, model=_EXTEND_MODEL)
    ]


def test_async_extend_cancel_records_one_event(monkeypatch: pytest.MonkeyPatch) -> None:
    sink = InMemoryUsageSink()
    script = _Script([])
    script.install_async(monkeypatch)

    async def _run() -> None:
        inbox = _CancelOnPending()
        with pytest.raises(
            RuntimeError, match=f"Video extension cancelled: request_id={_RID}"
        ):
            await _extend(_async_client(sink), inbox)
        assert inbox.latest(_RID) is not None
        assert inbox.latest(_RID).status == "cancelled"

    asyncio.run(_run())
    assert len(script.posts) == 1
    assert script.posts[0]["url"] == XAI_VIDEO_EXTENSIONS_URL
    assert script.posts[0]["json"]["model"] == _EXTEND_MODEL
    assert script.gets == []
    assert _views(sink) == [
        _cancelled_event(estimated_usd=_EXTEND_CANCEL_USD, model=_EXTEND_MODEL)
    ]


def test_sync_cancel_after_done_keeps_done_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    script = _Script([_DONE_BODY])
    script.install_sync(monkeypatch)
    inbox = _CancelOnDone()
    out = _generate(_sync_client(sink), inbox)
    assert out["status"] == "done"
    assert inbox.latest(_RID) is not None
    assert inbox.latest(_RID).status == "cancelled"
    assert _views(sink) == [_event(success=True, error=None, estimated_usd=0.08)]


def test_async_cancel_after_pending_polls_records_one_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    inbox = VideoInbox()

    def _cancel_on_third(count: int) -> None:
        if count == 3:
            inbox.cancel(_RID)

    script = _Script([], on_get=_cancel_on_third)
    script.install_async(monkeypatch)

    async def _run() -> None:
        with pytest.raises(RuntimeError, match=f"Video generation cancelled: request_id={_RID}"):
            await _generate(_async_client(sink), inbox, duration=8, resolution="720p")

    asyncio.run(_run())
    assert len(script.gets) == 3
    assert _views(sink) == [_cancelled_event(estimated_usd=_GENERATE_CANCEL_USD)]


def test_async_double_cancel_records_one_event(monkeypatch: pytest.MonkeyPatch) -> None:
    sink = InMemoryUsageSink()
    inbox = VideoInbox()

    def _cancel_twice(count: int) -> None:
        if count == 3:
            inbox.cancel(_RID)
            inbox.cancel(_RID)

    script = _Script([], on_get=_cancel_twice)
    script.install_async(monkeypatch)

    async def _run() -> None:
        with pytest.raises(RuntimeError, match="cancelled"):
            await _generate(_async_client(sink), inbox, duration=8, resolution="720p")

    asyncio.run(_run())
    assert len(script.gets) == 3
    assert _views(sink) == [_cancelled_event(estimated_usd=_GENERATE_CANCEL_USD)]


def test_async_cancel_after_done_keeps_done_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    script = _Script([_DONE_BODY])
    script.install_async(monkeypatch)

    async def _run() -> None:
        inbox = _CancelOnDone()
        out = await _generate(_async_client(sink), inbox)
        assert out["status"] == "done"
        assert inbox.latest(_RID) is not None
        assert inbox.latest(_RID).status == "cancelled"

    asyncio.run(_run())
    assert _views(sink) == [_event(success=True, error=None, estimated_usd=0.08)]


def test_async_sibling_cancelled_error_records_one_terminal_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    state = {"release": False}
    script = _Script([])

    def _release_done(count: int) -> None:
        if state["release"]:
            script.polls.append(_DONE_BODY)

    script.on_get = _release_done
    script.install_async(monkeypatch)

    async def _run() -> None:
        client = _async_client(sink)
        task = asyncio.create_task(
            _generate(
                client,
                [],
                purpose="demo.ok",
                labels={"request_id": "ok"},
                interval=0.01,
                timeout=30,
            )
        )
        for _ in range(50):
            if script.gets:
                break
            await asyncio.sleep(0.01)
        assert script.gets
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        state["release"] = True
        leftover = list(client._inflight_video_waits)
        assert leftover
        await asyncio.wait_for(asyncio.gather(*leftover), timeout=2)

    asyncio.run(_run())
    assert _views(sink) == [
        _event(
            success=True,
            error=None,
            estimated_usd=0.08,
            purpose="demo.ok",
            labels={"request_id": "ok"},
        )
    ]


@pytest.mark.parametrize("client_kind", ["sync", "async"])
def test_cancel_estimated_usd_matches_failed_for_same_request(
    monkeypatch: pytest.MonkeyPatch,
    client_kind: str,
) -> None:
    same = {"duration": 8, "resolution": "720p"}
    failed_sink = InMemoryUsageSink()
    failed_script = _Script([_FAILED_BODY])
    cancel_sink = InMemoryUsageSink()
    cancel_script = _Script([])
    if client_kind == "sync":
        failed_script.install_sync(monkeypatch)
        with pytest.raises(RuntimeError, match="failed"):
            _generate(_sync_client(failed_sink), [], **same)
        cancel_script.install_sync(monkeypatch)
        with pytest.raises(RuntimeError, match="cancelled"):
            _generate(_sync_client(cancel_sink), _CancelOnPending(), **same)
    else:
        failed_script.install_async(monkeypatch)

        async def _fail() -> None:
            with pytest.raises(RuntimeError, match="failed"):
                await _generate(_async_client(failed_sink), [], **same)

        asyncio.run(_fail())
        cancel_script.install_async(monkeypatch)

        async def _cancel() -> None:
            with pytest.raises(RuntimeError, match="cancelled"):
                await _generate(_async_client(cancel_sink), _CancelOnPending(), **same)

        asyncio.run(_cancel())

    failed_views = _views(failed_sink)
    cancel_views = _views(cancel_sink)
    assert failed_views == [_event(success=False, error="video_failed", estimated_usd=1.12)]
    assert cancel_views == [
        _cancelled_event(estimated_usd=failed_views[0]["estimated_usd"])
    ]
    assert cancel_views[0]["estimated_usd"] == failed_views[0]["estimated_usd"] == 1.12
    assert cancel_script.gets == []


def test_async_inner_wait_cancel_records_no_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    polling = asyncio.Event()

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
                    json={"request_id": _RID},
                    request=httpx.Request("POST", url),
                )
            polling.set()
            await asyncio.Event().wait()
            return httpx.Response(
                200,
                json={"status": "pending"},
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr("xaikit.async_client.httpx.AsyncClient", FakeAsyncClient)

    async def _run() -> None:
        client = _async_client(sink)
        outer = asyncio.create_task(
            _generate(client, [], duration=8, resolution="720p", timeout=30)
        )
        for _ in range(50):
            if polling.is_set() and client._inflight_video_waits:
                break
            await asyncio.sleep(0.01)
        assert len(client._inflight_video_waits) == 1
        inner = next(iter(client._inflight_video_waits))
        assert inner is not outer
        inner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await inner
        with pytest.raises(asyncio.CancelledError):
            await outer

    asyncio.run(_run())
    events = _views(sink)
    assert [event["error"] for event in events] == []
    assert len(events) == 0
