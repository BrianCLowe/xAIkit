"""Contract tests: collections SDK wiring (helper kwargs, guards, metering)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from xaikit import (
    InMemoryUsageSink,
    MockChatProvider,
    UsageMeter,
    XaiClient,
    default_retry_policy,
)
from xaikit.collections import (
    call_collections_rpc,
    collection_to_dict,
    document_to_dict,
    search_to_dict,
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


class _RpcCapture:
    def __init__(self, returns: Any | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.returns = (
            returns if returns is not None else {"id": "col_1", "name": "docs"}
        )

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _rpc(operation: str, *, sdk_client: Any = None, **kwargs: Any) -> Any:
            self.calls.append({"operation": operation, **kwargs})
            if callable(self.returns):
                return self.returns(operation, **kwargs)
            return self.returns

        monkeypatch.setattr("xaikit.client.call_collections_rpc", _rpc)


def test_create_collection_passes_helper_kwargs_and_meters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    meter = UsageMeter(sink=sink)
    client = _client(usage_meter=meter)
    cap = _RpcCapture({"id": "col_1", "name": "docs", "model_name": "v1"})
    cap.install(monkeypatch)

    out = client.create_collection(
        "docs",
        model_name="v1",
        description="notes",
        purpose="demo.collections",
        parent_id="p1",
        labels={"request_id": "c1"},
    )

    assert out["id"] == "col_1"
    assert out["name"] == "docs"
    assert len(cap.calls) == 1
    call = cap.calls[0]
    assert call["operation"] == "create"
    assert call["name"] == "docs"
    assert call["model_name"] == "v1"
    assert call["description"] == "notes"

    ev = list(sink.iter_events())[0]
    assert ev.purpose == "demo.collections"
    assert ev.modality == "collections"
    assert ev.model == "collections"
    assert ev.success is True
    assert ev.estimated_usd is None
    assert ev.parent_id == "p1"
    assert ev.labels["request_id"] == "c1"


def test_upload_and_search_helper_kwargs(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client()

    def _returns(operation: str, **kwargs: Any) -> Any:
        if operation == "upload_document":
            return {"id": "file_1", "name": kwargs["name"]}
        if operation == "search":
            return {
                "matches": [
                    {
                        "file_id": "file_1",
                        "chunk_content": "hello world",
                        "score": 0.91,
                    }
                ]
            }
        raise AssertionError(operation)

    cap = _RpcCapture(_returns)
    cap.install(monkeypatch)

    uploaded = client.upload_document("col_1", "note.txt", b"hello world", fields={"k": "v"})
    assert uploaded["id"] == "file_1"
    hits = client.search_collections("hello", ["col_1"], limit=5)
    assert hits["matches"][0]["chunk_content"] == "hello world"
    assert cap.calls[0]["operation"] == "upload_document"
    assert cap.calls[0]["collection_id"] == "col_1"
    assert cap.calls[0]["name"] == "note.txt"
    assert cap.calls[0]["data"] == b"hello world"
    assert cap.calls[0]["fields"] == {"k": "v"}
    assert cap.calls[1]["operation"] == "search"
    assert cap.calls[1]["query"] == "hello"
    assert cap.calls[1]["collection_ids"] == ["col_1"]
    assert cap.calls[1]["limit"] == 5


def test_search_accepts_single_collection_id_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _RpcCapture({"matches": []})
    cap.install(monkeypatch)
    client.search_collections("hello", "col_1")
    assert cap.calls[0]["collection_ids"] == ["col_1"]


def test_get_list_and_delete_helper_kwargs(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client()

    def _returns(operation: str, **kwargs: Any) -> Any:
        if operation == "get":
            return {"id": kwargs["collection_id"], "name": "docs"}
        if operation == "list":
            return {
                "collections": [{"id": "col_1", "name": "docs"}],
                "pagination_token": "next",
            }
        if operation == "delete":
            return {"id": kwargs["collection_id"], "deleted": True}
        raise AssertionError(operation)

    cap = _RpcCapture(_returns)
    cap.install(monkeypatch)

    got = client.get_collection("col_1")
    assert got["id"] == "col_1"
    listed = client.list_collections(limit=5, pagination_token="tok")
    assert listed["collections"][0]["id"] == "col_1"
    assert listed["pagination_token"] == "next"
    deleted = client.delete_collection("col_1")
    assert deleted["id"] == "col_1"
    assert deleted["deleted"] is True
    assert [c["operation"] for c in cap.calls] == ["get", "list", "delete"]
    assert cap.calls[1]["limit"] == 5
    assert cap.calls[1]["pagination_token"] == "tok"


def test_empty_name_id_query_and_bytes_rejected_before_rpc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _RpcCapture()
    cap.install(monkeypatch)

    with pytest.raises(RuntimeError, match="empty"):
        client.create_collection("   ")
    with pytest.raises(RuntimeError, match="empty"):
        client.get_collection("")
    with pytest.raises(RuntimeError, match="empty"):
        client.delete_collection("  ")
    with pytest.raises(RuntimeError, match="empty"):
        client.upload_document("", "note.txt", b"hello")
    with pytest.raises(RuntimeError, match="empty"):
        client.upload_document("col_1", "  ", b"hello")
    with pytest.raises(RuntimeError, match="empty"):
        client.upload_document("col_1", "note.txt", b"")
    with pytest.raises(RuntimeError, match="empty"):
        client.search_collections("   ", ["col_1"])
    with pytest.raises(RuntimeError, match="empty"):
        client.search_collections("hello", [])
    with pytest.raises(RuntimeError, match="empty"):
        client.search_collections("hello", ["  "])
    assert cap.calls == []


def test_create_collection_requires_purpose_when_metered() -> None:
    client = _client(usage_meter=UsageMeter(sink=InMemoryUsageSink()))
    with pytest.raises(ValueError, match="purpose"):
        client.create_collection("docs")


def test_create_collection_failure_records_failed_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    client = _client(usage_meter=UsageMeter(sink=sink))

    def _boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("offline")

    monkeypatch.setattr("xaikit.client.call_collections_rpc", _boom)
    with pytest.raises(RuntimeError, match="Collection create failed"):
        client.create_collection("docs", purpose="demo.collections.fail")

    ev = list(sink.iter_events())[0]
    assert ev.success is False
    assert ev.modality == "collections"
    assert ev.purpose == "demo.collections.fail"
    assert ev.model == "collections"
    assert ev.estimated_usd is None


def test_create_collection_without_helper_and_sdk_raises() -> None:
    client = _client()
    with pytest.raises(RuntimeError, match="Collections"):
        client.create_collection("docs")


def test_call_collections_rpc_create_upload_search_use_sdk_subclient() -> None:
    created: list[dict[str, Any]] = []
    uploaded: list[dict[str, Any]] = []
    searched: list[dict[str, Any]] = []

    class _FakeSdk:
        def __init__(self) -> None:
            self.collections = SimpleNamespace(
                create=self._create,
                upload_document=self._upload,
                search=self._search,
            )

        def _create(self, name: str, **kwargs: Any) -> Any:
            created.append({"name": name, **kwargs})
            return SimpleNamespace(
                collection_id="col_9",
                collection_name=name,
                collection_description=kwargs.get("description") or "",
                documents_count=0,
                total_file_size=0,
                index_configuration=SimpleNamespace(
                    model_name=kwargs.get("model_name") or ""
                ),
            )

        def _upload(
            self,
            collection_id: str,
            name: str,
            data: bytes,
            fields: dict[str, str] | None = None,
        ) -> Any:
            uploaded.append(
                {
                    "collection_id": collection_id,
                    "name": name,
                    "data": data,
                    "fields": fields,
                }
            )
            return SimpleNamespace(
                file_metadata=SimpleNamespace(
                    file_id="file_9",
                    name=name,
                    size_bytes=len(data),
                    content_type="text/plain",
                ),
                fields=fields or {},
                status=2,
                error_message="",
                chunk_count=1,
            )

        def _search(
            self,
            query: str,
            collection_ids: list[str],
            limit: int | None = None,
        ) -> Any:
            searched.append(
                {"query": query, "collection_ids": collection_ids, "limit": limit}
            )
            return SimpleNamespace(
                matches=[
                    SimpleNamespace(
                        file_id="file_9",
                        chunk_id="chk_1",
                        chunk_content="hello",
                        score=0.5,
                        collection_ids=collection_ids,
                    )
                ]
            )

    sdk = _FakeSdk()
    out = call_collections_rpc(
        "create",
        sdk_client=sdk,
        name="docs",
        model_name="v1",
        description="notes",
    )
    assert out["id"] == "col_9"
    assert out["name"] == "docs"
    assert out["model_name"] == "v1"
    assert created == [{"name": "docs", "model_name": "v1", "description": "notes"}]

    doc = call_collections_rpc(
        "upload_document",
        sdk_client=sdk,
        collection_id="col_9",
        name="note.txt",
        data=b"hello",
        fields={"title": "note"},
    )
    assert doc["id"] == "file_9"
    assert doc["name"] == "note.txt"
    assert doc["status"] == "processed"
    assert uploaded[0]["data"] == b"hello"

    hits = call_collections_rpc(
        "search",
        sdk_client=sdk,
        query="hello",
        collection_ids=["col_9"],
        limit=3,
    )
    assert hits["matches"][0]["chunk_content"] == "hello"
    assert searched == [
        {"query": "hello", "collection_ids": ["col_9"], "limit": 3}
    ]


def test_collection_and_search_map_protos() -> None:
    from xai_sdk.proto import collections_pb2, documents_pb2

    meta = collections_pb2.CollectionMetadata(
        collection_id="col_1",
        collection_name="docs",
        collection_description="notes",
        documents_count=2,
    )
    mapped = collection_to_dict(meta)
    assert mapped["id"] == "col_1"
    assert mapped["name"] == "docs"
    assert mapped["description"] == "notes"
    assert mapped["documents_count"] == 2

    doc = collections_pb2.DocumentMetadata(status=collections_pb2.DOCUMENT_STATUS_PROCESSED)
    doc.file_metadata.file_id = "file_1"
    doc.file_metadata.name = "note.txt"
    mapped_doc = document_to_dict(doc)
    assert mapped_doc["id"] == "file_1"
    assert mapped_doc["status"] == "processed"

    page = documents_pb2.SearchResponse()
    match = page.matches.add()
    match.file_id = "file_1"
    match.chunk_content = "hello"
    match.score = 0.8
    match.collection_ids.append("col_1")
    hits = search_to_dict(page)
    assert hits["matches"][0]["file_id"] == "file_1"
    assert hits["matches"][0]["chunk_content"] == "hello"
    assert hits["matches"][0]["collection_ids"] == ["col_1"]
