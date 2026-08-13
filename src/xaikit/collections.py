"""xAI collections / documents helpers.

Wraps ``xai_sdk.sync.collections.Client`` (on ``xai_sdk.Client.collections``).
Public kit methods return JSON dicts — callers never import collections or
documents protobufs. Tests inject a fake by monkeypatching
:func:`call_collections_rpc`.

Create / get / list / delete / upload use the management channel. The SDK
reads ``XAI_MANAGEMENT_KEY`` from the environment when constructing
``xai_sdk.Client`` (search uses the regular API channel).
"""

from __future__ import annotations

import inspect
from typing import Any

_COLLECTION_OPS = frozenset(
    {"create", "get", "list", "delete", "upload_document", "search"}
)

_DOCUMENT_STATUS = {
    0: "unknown",
    1: "processing",
    2: "processed",
    3: "failed",
    4: "chunked",
    5: "embedding",
    6: "writing",
}


def call_collections_rpc(
    operation: str,
    *,
    sdk_client: Any = None,
    **kwargs: Any,
) -> Any:
    """Invoke one collections SDK method. Tests monkeypatch this (never hits gRPC).

    Returns JSON-dict-friendly values. *operation* is one of ``create``,
    ``get``, ``list``, ``delete``, ``upload_document``, ``search``.
    """
    op = (operation or "").strip()
    if op not in _COLLECTION_OPS:
        raise RuntimeError(f"Unknown collections operation: {operation!r}")
    if sdk_client is None:
        raise RuntimeError(
            "Collections SDK client is not available. Pass api_key= (not only "
            "provider=) or monkeypatch call_collections_rpc for offline tests."
        )
    collections_api = getattr(sdk_client, "collections", None)
    if collections_api is None:
        raise RuntimeError("SDK client has no collections subclient")

    if op == "create":
        create_kwargs: dict[str, Any] = {"name": kwargs.get("name")}
        if kwargs.get("model_name"):
            create_kwargs["model_name"] = kwargs["model_name"]
        if kwargs.get("chunk_configuration") is not None:
            create_kwargs["chunk_configuration"] = kwargs["chunk_configuration"]
        if kwargs.get("description"):
            create_kwargs["description"] = kwargs["description"]
        return collection_to_dict(collections_api.create(**create_kwargs))

    if op == "get":
        return collection_to_dict(collections_api.get(kwargs["collection_id"]))

    if op == "list":
        raw = collections_api.list(
            limit=kwargs.get("limit"),
            pagination_token=kwargs.get("pagination_token"),
        )
        return list_collections_to_dict(raw)

    if op == "delete":
        collection_id = kwargs["collection_id"]
        collections_api.delete(collection_id)
        return {"id": collection_id, "deleted": True}

    if op == "upload_document":
        raw = collections_api.upload_document(
            kwargs["collection_id"],
            kwargs["name"],
            kwargs["data"],
            fields=kwargs.get("fields"),
        )
        return document_to_dict(raw)

    raw = collections_api.search(
        kwargs["query"],
        kwargs["collection_ids"],
        limit=kwargs.get("limit"),
    )
    return search_to_dict(raw)


async def _await_rpc(result: Any) -> Any:
    if inspect.isawaitable(result):
        return await result
    return result


async def call_collections_rpc_async(
    operation: str,
    *,
    sdk_client: Any = None,
    **kwargs: Any,
) -> Any:
    """Async twin of :func:`call_collections_rpc`. Tests monkeypatch this."""
    op = (operation or "").strip()
    if op not in _COLLECTION_OPS:
        raise RuntimeError(f"Unknown collections operation: {operation!r}")
    if sdk_client is None:
        raise RuntimeError(
            "Collections SDK client is not available. Pass api_key= (not only "
            "provider=) or monkeypatch call_collections_rpc_async for offline tests."
        )
    collections_api = getattr(sdk_client, "collections", None)
    if collections_api is None:
        raise RuntimeError("SDK client has no collections subclient")

    if op == "create":
        create_kwargs: dict[str, Any] = {"name": kwargs.get("name")}
        if kwargs.get("model_name"):
            create_kwargs["model_name"] = kwargs["model_name"]
        if kwargs.get("chunk_configuration") is not None:
            create_kwargs["chunk_configuration"] = kwargs["chunk_configuration"]
        if kwargs.get("description"):
            create_kwargs["description"] = kwargs["description"]
        return collection_to_dict(
            await _await_rpc(collections_api.create(**create_kwargs))
        )

    if op == "get":
        return collection_to_dict(
            await _await_rpc(collections_api.get(kwargs["collection_id"]))
        )

    if op == "list":
        raw = await _await_rpc(
            collections_api.list(
                limit=kwargs.get("limit"),
                pagination_token=kwargs.get("pagination_token"),
            )
        )
        return list_collections_to_dict(raw)

    if op == "delete":
        collection_id = kwargs["collection_id"]
        await _await_rpc(collections_api.delete(collection_id))
        return {"id": collection_id, "deleted": True}

    if op == "upload_document":
        raw = await _await_rpc(
            collections_api.upload_document(
                kwargs["collection_id"],
                kwargs["name"],
                kwargs["data"],
                fields=kwargs.get("fields"),
            )
        )
        return document_to_dict(raw)

    raw = await _await_rpc(
        collections_api.search(
            kwargs["query"],
            kwargs["collection_ids"],
            limit=kwargs.get("limit"),
        )
    )
    return search_to_dict(raw)


def normalize_collection_ids(collection_ids: Any) -> list[str]:
    """Validate collection id(s) before the RPC helper."""
    if collection_ids is None:
        raise RuntimeError("Collection id is empty")
    if isinstance(collection_ids, str):
        items: list[Any] = [collection_ids]
    elif isinstance(collection_ids, (list, tuple)):
        items = list(collection_ids)
    else:
        raise RuntimeError("Collection ids must be a string or list of strings")
    if not items:
        raise RuntimeError("Collection id is empty")
    out: list[str] = []
    for item in items:
        cleaned = str(item or "").strip()
        if not cleaned:
            raise RuntimeError("Collection id is empty")
        out.append(cleaned)
    return out


def collection_to_dict(payload: Any) -> dict[str, Any]:
    """JSON dict for CollectionMetadata proto or an already-normalized dict."""
    if isinstance(payload, dict):
        out = dict(payload)
        cid = str(out.get("id") or out.get("collection_id") or "").strip()
        if not cid:
            raise RuntimeError("Collection response missing id")
        out["id"] = cid
        if "name" not in out and out.get("collection_name"):
            out["name"] = out["collection_name"]
        return out
    proto = getattr(payload, "proto", payload)
    cid = str(getattr(proto, "collection_id", "") or "").strip()
    if not cid:
        raise RuntimeError("Collection response missing id")
    out = {
        "id": cid,
        "name": getattr(proto, "collection_name", "") or "",
    }
    description = str(getattr(proto, "collection_description", "") or "").strip()
    if description:
        out["description"] = description
    count = getattr(proto, "documents_count", None)
    if count is not None:
        out["documents_count"] = int(count)
    size = getattr(proto, "total_file_size", None)
    if size is not None:
        out["total_file_size"] = int(size)
    created = _timestamp_json(getattr(proto, "created_at", None))
    if created:
        out["created_at"] = created
    index = getattr(proto, "index_configuration", None)
    model_name = str(getattr(index, "model_name", "") or "").strip() if index is not None else ""
    if model_name:
        out["model_name"] = model_name
    chunk = _chunk_config_to_dict(getattr(proto, "chunk_configuration", None))
    if chunk:
        out["chunk_configuration"] = chunk
    fields = [
        _field_definition_to_dict(item)
        for item in (getattr(proto, "field_definitions", None) or [])
    ]
    if fields:
        out["field_definitions"] = fields
    return out


def list_collections_to_dict(payload: Any) -> dict[str, Any]:
    """JSON dict for ``list`` — ``{collections, pagination_token}``."""
    if isinstance(payload, dict):
        rows = payload.get("collections") or []
        token = payload.get("pagination_token") or None
        return {
            "collections": [collection_to_dict(row) for row in rows],
            "pagination_token": token or None,
        }
    rows = getattr(payload, "collections", None) or []
    token = getattr(payload, "pagination_token", None) or None
    return {
        "collections": [collection_to_dict(row) for row in rows],
        "pagination_token": token or None,
    }


def document_to_dict(payload: Any) -> dict[str, Any]:
    """JSON dict for DocumentMetadata proto or an already-normalized dict."""
    if isinstance(payload, dict):
        out = dict(payload)
        did = str(out.get("id") or out.get("file_id") or "").strip()
        if not did:
            raise RuntimeError("Document response missing id")
        out["id"] = did
        return out
    proto = getattr(payload, "proto", payload)
    meta = getattr(proto, "file_metadata", None)
    did = str(getattr(meta, "file_id", "") or getattr(proto, "file_id", "") or "").strip()
    if not did:
        raise RuntimeError("Document response missing id")
    out: dict[str, Any] = {"id": did}
    name = str(getattr(meta, "name", "") or "").strip() if meta is not None else ""
    if name:
        out["name"] = name
    if meta is not None:
        size = getattr(meta, "size_bytes", None)
        if size is not None:
            out["size_bytes"] = int(size)
        content_type = str(getattr(meta, "content_type", "") or "").strip()
        if content_type:
            out["content_type"] = content_type
    status = _document_status(getattr(proto, "status", None))
    if status:
        out["status"] = status
    error = str(getattr(proto, "error_message", "") or "").strip()
    if error:
        out["error_message"] = error
    chunk_count = getattr(proto, "chunk_count", None)
    if chunk_count is not None:
        out["chunk_count"] = int(chunk_count)
    fields = getattr(proto, "fields", None)
    if fields:
        out["fields"] = dict(fields)
    return out


def search_to_dict(payload: Any) -> dict[str, Any]:
    """JSON dict for SearchResponse — ``{matches}``."""
    if isinstance(payload, dict):
        rows = payload.get("matches") or []
        return {"matches": [_search_match_to_dict(row) for row in rows]}
    rows = getattr(payload, "matches", None) or []
    return {"matches": [_search_match_to_dict(row) for row in rows]}


def _search_match_to_dict(match: Any) -> dict[str, Any]:
    if isinstance(match, dict):
        return dict(match)
    proto = getattr(match, "proto", match)
    out: dict[str, Any] = {
        "file_id": str(getattr(proto, "file_id", "") or ""),
        "chunk_id": str(getattr(proto, "chunk_id", "") or ""),
        "chunk_content": str(getattr(proto, "chunk_content", "") or ""),
        "score": float(getattr(proto, "score", 0.0) or 0.0),
    }
    ids = [str(item) for item in (getattr(proto, "collection_ids", None) or [])]
    if ids:
        out["collection_ids"] = ids
    return out


def _document_status(raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        cleaned = raw.strip()
        return cleaned or None
    try:
        code = int(raw)
    except (TypeError, ValueError):
        return str(raw)
    return _DOCUMENT_STATUS.get(code, str(code))


def _field_definition_to_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return dict(item)
    out: dict[str, Any] = {"key": str(getattr(item, "key", "") or "")}
    for key in ("required", "inject_into_chunk", "unique"):
        out[key] = bool(getattr(item, key, False))
    description = str(getattr(item, "description", "") or "").strip()
    if description:
        out["description"] = description
    return out


def _chunk_config_to_dict(cfg: Any) -> dict[str, Any] | None:
    if cfg is None:
        return None
    if isinstance(cfg, dict):
        return dict(cfg)
    out: dict[str, Any] = {}
    for key in ("strip_whitespace", "inject_name_into_chunks"):
        if getattr(cfg, key, False):
            out[key] = True
    chars = getattr(cfg, "chars_configuration", None)
    if chars is not None and (
        getattr(chars, "max_chunk_size_chars", 0) or getattr(chars, "chunk_overlap_chars", 0)
    ):
        out["chars_configuration"] = {
            "max_chunk_size_chars": int(getattr(chars, "max_chunk_size_chars", 0) or 0),
            "chunk_overlap_chars": int(getattr(chars, "chunk_overlap_chars", 0) or 0),
        }
    tokens = getattr(cfg, "tokens_configuration", None)
    if tokens is not None and (
        getattr(tokens, "max_chunk_size_tokens", 0) or getattr(tokens, "chunk_overlap_tokens", 0)
    ):
        row: dict[str, Any] = {
            "max_chunk_size_tokens": int(getattr(tokens, "max_chunk_size_tokens", 0) or 0),
            "chunk_overlap_tokens": int(getattr(tokens, "chunk_overlap_tokens", 0) or 0),
        }
        encoding = str(getattr(tokens, "encoding_name", "") or "").strip()
        if encoding:
            row["encoding_name"] = encoding
        out["tokens_configuration"] = row
    return out or None


def _timestamp_json(ts: Any) -> str | None:
    if ts is None:
        return None
    seconds = getattr(ts, "seconds", None)
    nanos = getattr(ts, "nanos", None)
    if not seconds and not nanos:
        return None
    to_json = getattr(ts, "ToJsonString", None)
    if callable(to_json):
        text = to_json()
        return str(text) if text else None
    return None
