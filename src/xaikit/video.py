"""Durable receive path for Imagine video starts and terminal results."""

from __future__ import annotations

from collections.abc import Callable, MutableSequence
from dataclasses import dataclass, field
from typing import Any, Union

VIDEO_INTO_REQUIRED = (
    "generate_video/extend_video require into= — a VideoInbox, list, or callback "
    "the app keeps. The kit delivers request_id as soon as xAI accepts the job, "
    "then the terminal result. A sibling failure can cancel the await; it must "
    "not void the receipt. Call inbox.cancel(request_id) only to stop listening."
)


@dataclass(frozen=True)
class VideoReceipt:
    """One video event: start (pending) or a terminal status."""

    request_id: str
    status: str
    payload: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class VideoInbox:
    """App-owned receive path for video work.

    Keep this object. The kit writes here even if ``asyncio.gather`` /
    ``TaskGroup`` cancels the await because a sibling failed. :meth:`cancel`
    is the only way to stop listening (it does not abort xAI-side generation).
    """

    def __init__(self) -> None:
        self.receipts: list[VideoReceipt] = []
        self._cancelled: set[str] = set()

    def deliver(self, receipt: VideoReceipt) -> None:
        self.receipts.append(receipt)

    def cancel(self, request_id: str) -> None:
        rid = (request_id or "").strip()
        if not rid or rid in self._cancelled:
            return
        self._cancelled.add(rid)
        self.deliver(
            VideoReceipt(request_id=rid, status="cancelled", error="cancelled")
        )

    def is_cancelled(self, request_id: str) -> bool:
        return (request_id or "").strip() in self._cancelled

    @property
    def request_ids(self) -> list[str]:
        seen: list[str] = []
        for receipt in self.receipts:
            if receipt.request_id and receipt.request_id not in seen:
                seen.append(receipt.request_id)
        return seen

    def latest(self, request_id: str) -> VideoReceipt | None:
        rid = (request_id or "").strip()
        for receipt in reversed(self.receipts):
            if receipt.request_id == rid:
                return receipt
        return None


VideoSink = Union[VideoInbox, MutableSequence[VideoReceipt], Callable[[VideoReceipt], None]]


def require_video_into(into: VideoSink | None) -> VideoSink:
    if into is None:
        raise TypeError(VIDEO_INTO_REQUIRED)
    if isinstance(into, (VideoInbox, MutableSequence)):
        return into
    if callable(into):
        return into
    raise TypeError(VIDEO_INTO_REQUIRED)


def deliver_video_receipt(into: VideoSink, receipt: VideoReceipt) -> None:
    if isinstance(into, VideoInbox):
        into.deliver(receipt)
        return
    if isinstance(into, MutableSequence):
        into.append(receipt)
        return
    into(receipt)


def video_sink_cancelled(into: VideoSink, request_id: str) -> bool:
    return isinstance(into, VideoInbox) and into.is_cancelled(request_id)


def video_receipt(
    payload: dict[str, Any],
    *,
    request_id: str,
    status: str,
    error: str | None = None,
) -> VideoReceipt:
    return VideoReceipt(
        request_id=request_id,
        status=status,
        payload=payload,
        error=error,
    )
