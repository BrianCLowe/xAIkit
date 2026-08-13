"""Contract tests: Files REST wiring (URL, auth, multipart, metering)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from xaikit import (
    InMemoryUsageSink,
    MockChatProvider,
    UsageMeter,
    XAI_FILES_URL,
    XaiClient,
    default_retry_policy,
)
from xaikit.client import XAI_FILE_MAX_BYTES


def _client(*, usage_meter: UsageMeter | None = None, **kwargs: Any) -> XaiClient:
    return XaiClient(
        provider=MockChatProvider(),
        model="grok-3-mini",
        api_key="test-key",
        usage_meter=usage_meter,
        retry_policy=default_retry_policy(max_attempts=1),
        **kwargs,
    )


def _file_json(
    *,
    file_id: str = "file_abc123",
    filename: str = "note.txt",
    size: int = 5,
) -> dict[str, Any]:
    return {
        "id": file_id,
        "object": "file",
        "bytes": size,
        "created_at": 1762345678,
        "expires_at": None,
        "filename": filename,
        "purpose": "assistants",
    }


class _Capture:
    def __init__(self) -> None:
        self.posts: list[dict[str, Any]] = []
        self.gets: list[dict[str, Any]] = []
        self.deletes: list[dict[str, Any]] = []

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

    def install_delete(
        self, monkeypatch: pytest.MonkeyPatch, response: httpx.Response
    ) -> None:
        def _delete(url: str, **kwargs: Any) -> httpx.Response:
            self.deletes.append({"url": url, **kwargs})
            if response.request is not None:
                return response
            return httpx.Response(
                response.status_code,
                headers=response.headers,
                content=response.content,
                request=httpx.Request("DELETE", url),
            )

        monkeypatch.setattr("xaikit.client.httpx.delete", _delete)


def test_upload_file_posts_multipart_with_auth_filename_and_meters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    meter = UsageMeter(sink=sink)
    client = _client(usage_meter=meter)
    cap = _Capture()
    cap.install_post(
        monkeypatch,
        httpx.Response(
            200,
            json=_file_json(),
            request=httpx.Request("POST", XAI_FILES_URL),
        ),
    )

    out = client.upload_file(
        b"hello",
        "note.txt",
        content_type="text/plain",
        purpose="demo.files",
        parent_id="p1",
        labels={"request_id": "f1"},
    )

    assert out["id"] == "file_abc123"
    assert out["filename"] == "note.txt"
    assert out["bytes"] == 5
    assert out["created_at"] == 1762345678
    assert len(cap.posts) == 1
    call = cap.posts[0]
    assert call["url"] == XAI_FILES_URL
    assert call["headers"]["Authorization"] == "Bearer test-key"
    assert call["data"] == {"purpose": "assistants"}
    assert call["files"]["file"] == ("note.txt", b"hello", "text/plain")
    assert call["timeout"] == 120.0

    ev = list(sink.iter_events())[0]
    assert ev.purpose == "demo.files"
    assert ev.modality == "files"
    assert ev.model == "files"
    assert ev.success is True
    assert ev.parent_id == "p1"
    assert ev.labels["request_id"] == "f1"


def test_upload_file_file_purpose_is_multipart_not_meter_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    client = _client(usage_meter=UsageMeter(sink=sink))
    cap = _Capture()
    cap.install_post(
        monkeypatch,
        httpx.Response(
            200,
            json=_file_json(),
            request=httpx.Request("POST", XAI_FILES_URL),
        ),
    )

    client.upload_file(
        b"hello",
        "note.txt",
        purpose="demo.files.meter",
        file_purpose="assistants",
    )
    assert cap.posts[0]["data"] == {"purpose": "assistants"}
    assert list(sink.iter_events())[0].purpose == "demo.files.meter"


def test_upload_file_expires_after_precedes_file_part(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install_post(
        monkeypatch,
        httpx.Response(
            200,
            json=_file_json(),
            request=httpx.Request("POST", XAI_FILES_URL),
        ),
    )

    client.upload_file(b"hello", "note.txt", expires_after=86400)
    assert list(cap.posts[0]["data"].items()) == [
        ("expires_after", "86400"),
        ("purpose", "assistants"),
    ]


def test_upload_file_form_data_encodes_as_httpx_multipart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: list-of-tuples `data` + `files` crashes httpx encoding."""
    client = _client()
    cap = _Capture()
    cap.install_post(
        monkeypatch,
        httpx.Response(
            200,
            json=_file_json(),
            request=httpx.Request("POST", XAI_FILES_URL),
        ),
    )

    client.upload_file(
        b"hello",
        "note.txt",
        content_type="text/plain",
        expires_after=86400,
    )
    call = cap.posts[0]
    request = httpx.Request(
        "POST",
        call["url"],
        data=call["data"],
        files=call["files"],
    )
    body = request.read()
    assert b"expires_after" in body
    assert b"purpose" in body
    assert b"note.txt" in body
    assert body.find(b"expires_after") < body.find(b"note.txt")


def test_upload_file_rejects_empty_bytes_without_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install_post(
        monkeypatch,
        httpx.Response(
            200,
            json=_file_json(),
            request=httpx.Request("POST", XAI_FILES_URL),
        ),
    )
    with pytest.raises(RuntimeError, match="empty"):
        client.upload_file(b"", "note.txt")
    assert cap.posts == []


def test_upload_file_rejects_empty_filename_without_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install_post(
        monkeypatch,
        httpx.Response(
            200,
            json=_file_json(),
            request=httpx.Request("POST", XAI_FILES_URL),
        ),
    )
    with pytest.raises(RuntimeError, match="empty"):
        client.upload_file(b"hello", "  ")
    assert cap.posts == []


def test_upload_file_rejects_oversized_without_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install_post(
        monkeypatch,
        httpx.Response(
            200,
            json=_file_json(),
            request=httpx.Request("POST", XAI_FILES_URL),
        ),
    )
    monkeypatch.setattr("xaikit.client.XAI_FILE_MAX_BYTES", 8)
    with pytest.raises(RuntimeError, match="exceeds"):
        client.upload_file(b"123456789", "big.bin")
    assert cap.posts == []
    assert XAI_FILE_MAX_BYTES == 50 * 1024 * 1024


def test_upload_file_requires_purpose_when_metered() -> None:
    client = _client(usage_meter=UsageMeter(sink=InMemoryUsageSink()))
    with pytest.raises(ValueError, match="purpose"):
        client.upload_file(b"hello", "note.txt")


def test_upload_file_http_error_records_failed_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    meter = UsageMeter(sink=sink)
    client = _client(usage_meter=meter)

    def _boom(*_a: Any, **_k: Any) -> httpx.Response:
        raise httpx.ConnectError("offline")

    monkeypatch.setattr("xaikit.client.httpx.post", _boom)
    with pytest.raises(RuntimeError, match="Files request failed"):
        client.upload_file(b"hello", "note.txt", purpose="demo.files.fail")

    ev = list(sink.iter_events())[0]
    assert ev.success is False
    assert ev.modality == "files"
    assert ev.purpose == "demo.files.fail"


def test_upload_file_http_status_error_records_failed_usage(
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
            request=httpx.Request("POST", XAI_FILES_URL),
        ),
    )
    with pytest.raises(RuntimeError, match="Files failed \\(400\\)"):
        client.upload_file(b"hello", "note.txt", purpose="demo.files.http")
    ev = list(sink.iter_events())[0]
    assert ev.success is False
    assert ev.modality == "files"


def test_get_file_url_auth_and_meters(monkeypatch: pytest.MonkeyPatch) -> None:
    sink = InMemoryUsageSink()
    client = _client(usage_meter=UsageMeter(sink=sink))
    cap = _Capture()
    file_id = "file_abc123"
    url = f"{XAI_FILES_URL}/{file_id}"
    cap.install_get(
        monkeypatch,
        httpx.Response(
            200,
            json=_file_json(file_id=file_id),
            request=httpx.Request("GET", url),
        ),
    )

    out = client.get_file(file_id, purpose="demo.files.get")
    assert out["id"] == file_id
    assert len(cap.gets) == 1
    assert cap.gets[0]["url"] == url
    assert cap.gets[0]["headers"]["Authorization"] == "Bearer test-key"
    ev = list(sink.iter_events())[0]
    assert ev.modality == "files"
    assert ev.purpose == "demo.files.get"
    assert ev.success is True


def test_get_file_rejects_empty_id_without_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _Capture()
    cap.install_get(
        monkeypatch,
        httpx.Response(
            200,
            json=_file_json(),
            request=httpx.Request("GET", XAI_FILES_URL),
        ),
    )
    with pytest.raises(RuntimeError, match="empty"):
        client.get_file("  ")
    assert cap.gets == []


def test_delete_file_url_auth_and_meters(monkeypatch: pytest.MonkeyPatch) -> None:
    sink = InMemoryUsageSink()
    client = _client(usage_meter=UsageMeter(sink=sink))
    cap = _Capture()
    file_id = "file_abc123"
    url = f"{XAI_FILES_URL}/{file_id}"
    cap.install_delete(
        monkeypatch,
        httpx.Response(
            200,
            json={"id": file_id, "deleted": True, "object": "file"},
            request=httpx.Request("DELETE", url),
        ),
    )

    out = client.delete_file(file_id, purpose="demo.files.delete")
    assert out["id"] == file_id
    assert out["deleted"] is True
    assert cap.deletes[0]["url"] == url
    assert cap.deletes[0]["headers"]["Authorization"] == "Bearer test-key"
    ev = list(sink.iter_events())[0]
    assert ev.modality == "files"
    assert ev.success is True


def test_get_file_requires_purpose_when_metered() -> None:
    client = _client(usage_meter=UsageMeter(sink=InMemoryUsageSink()))
    with pytest.raises(ValueError, match="purpose"):
        client.get_file("file_abc123")
