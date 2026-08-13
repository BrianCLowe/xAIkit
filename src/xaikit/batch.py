"""xAI batch helpers.

Wraps ``xai_sdk.sync.batch.Client`` (on ``xai_sdk.Client.batch``). Public kit
methods return JSON dicts — callers never import ``batch_pb2``. Tests inject a
fake by monkeypatching :func:`call_batch_rpc`.
"""

from __future__ import annotations

from typing import Any

_BATCH_OPS = frozenset(
    {"create", "add", "get", "cancel", "list", "list_results"}
)


def call_batch_rpc(
    operation: str,
    *,
    sdk_client: Any = None,
    **kwargs: Any,
) -> Any:
    """Invoke one batch SDK method. Tests monkeypatch this (never hits gRPC).

    Returns JSON-dict-friendly values. *operation* is one of ``create``,
    ``add``, ``get``, ``cancel``, ``list``, ``list_results``.
    """
    op = (operation or "").strip()
    if op not in _BATCH_OPS:
        raise RuntimeError(f"Unknown batch operation: {operation!r}")
    if sdk_client is None:
        raise RuntimeError(
            "Batch SDK client is not available. Pass api_key= (not only "
            "provider=) or monkeypatch call_batch_rpc for offline tests."
        )
    batch_api = getattr(sdk_client, "batch", None)
    if batch_api is None:
        raise RuntimeError("SDK client has no batch subclient")

    if op == "create":
        name = kwargs.get("name")
        input_file_id = kwargs.get("input_file_id")
        if input_file_id is not None:
            raw = batch_api.create(name, input_file_id=input_file_id)
        else:
            raw = batch_api.create(name)
        return batch_to_dict(raw)

    if op == "add":
        batch_id = kwargs["batch_id"]
        requests = kwargs.get("requests") or []
        chats = [_chat_request_to_sdk(sdk_client, row) for row in requests]
        batch_api.add(batch_id, chats)
        return {"id": batch_id}

    if op == "get":
        return batch_to_dict(batch_api.get(kwargs["batch_id"]))

    if op == "cancel":
        return batch_to_dict(batch_api.cancel(kwargs["batch_id"]))

    if op == "list":
        raw = batch_api.list(
            limit=kwargs.get("limit"),
            pagination_token=kwargs.get("pagination_token"),
        )
        return list_batches_to_dict(raw)

    raw = batch_api.list_batch_results(
        kwargs["batch_id"],
        limit=kwargs.get("limit"),
        pagination_token=kwargs.get("pagination_token"),
    )
    return list_results_to_dict(raw)


def normalize_batch_requests(
    requests: Any,
    *,
    default_model: str,
) -> list[dict[str, Any]]:
    """Validate chat-shaped request dicts before the RPC helper."""
    if requests is None:
        raise RuntimeError("Batch requests are empty")
    if not isinstance(requests, (list, tuple)):
        raise RuntimeError("Batch requests must be a list of dicts")
    if not requests:
        raise RuntimeError("Batch requests are empty")
    fallback = (default_model or "").strip()
    out: list[dict[str, Any]] = []
    for i, req in enumerate(requests):
        if not isinstance(req, dict):
            raise RuntimeError(f"Batch request {i} is not a dict")
        messages = req.get("messages")
        if not isinstance(messages, list) or not messages:
            raise RuntimeError(f"Batch request {i} messages are empty")
        row = dict(req)
        if not str(row.get("model") or "").strip():
            if not fallback:
                raise RuntimeError(f"Batch request {i} model is empty")
            row["model"] = fallback
        else:
            row["model"] = str(row["model"]).strip()
        out.append(row)
    return out


def batch_to_dict(payload: Any) -> dict[str, Any]:
    """JSON dict for a Batch proto or an already-normalized dict."""
    if isinstance(payload, dict):
        out = dict(payload)
        bid = str(out.get("id") or out.get("batch_id") or "").strip()
        if not bid:
            raise RuntimeError("Batch response missing id")
        out["id"] = bid
        return out
    proto = getattr(payload, "proto", payload)
    bid = str(getattr(proto, "batch_id", "") or "").strip()
    if not bid:
        raise RuntimeError("Batch response missing id")
    out: dict[str, Any] = {
        "id": bid,
        "name": getattr(proto, "name", "") or "",
    }
    file_id = str(getattr(proto, "input_file_id", "") or "").strip()
    if file_id:
        out["input_file_id"] = file_id
    state = getattr(proto, "state", None)
    if state is not None:
        out["state"] = {
            "num_requests": int(getattr(state, "num_requests", 0) or 0),
            "num_pending": int(getattr(state, "num_pending", 0) or 0),
            "num_success": int(getattr(state, "num_success", 0) or 0),
            "num_error": int(getattr(state, "num_error", 0) or 0),
            "num_cancelled": int(getattr(state, "num_cancelled", 0) or 0),
        }
    created = _timestamp_json(getattr(proto, "create_time", None))
    if created:
        out["create_time"] = created
    expire = _timestamp_json(getattr(proto, "expire_time", None))
    if expire:
        out["expire_time"] = expire
    cancel = _timestamp_json(getattr(proto, "cancel_time", None))
    if cancel:
        out["cancel_time"] = cancel
    cancel_msg = str(getattr(proto, "cancel_by_xai_message", "") or "").strip()
    if cancel_msg:
        out["cancel_by_xai_message"] = cancel_msg
    return out


def list_batches_to_dict(payload: Any) -> dict[str, Any]:
    """JSON dict for ``list`` — ``{batches, pagination_token}``."""
    if isinstance(payload, dict):
        rows = payload.get("batches") or []
        token = payload.get("pagination_token") or None
        return {
            "batches": [batch_to_dict(row) for row in rows],
            "pagination_token": token or None,
        }
    rows = getattr(payload, "batches", None) or []
    token = getattr(payload, "pagination_token", None) or None
    return {
        "batches": [batch_to_dict(row) for row in rows],
        "pagination_token": token or None,
    }


def list_results_to_dict(payload: Any) -> dict[str, Any]:
    """JSON dict for ``list_batch_results`` — ``{results, pagination_token}``."""
    if isinstance(payload, dict):
        rows = payload.get("results") or []
        token = payload.get("pagination_token") or None
        return {
            "results": [_result_to_dict(row) for row in rows],
            "pagination_token": token or None,
        }
    rows = getattr(payload, "results", None)
    if rows is None:
        proto = getattr(payload, "proto", None)
        rows = getattr(proto, "results", None) if proto is not None else None
        token = getattr(proto, "pagination_token", None) if proto is not None else None
    else:
        token = getattr(payload, "pagination_token", None)
    return {
        "results": [_result_to_dict(row) for row in (rows or [])],
        "pagination_token": token or None,
    }


def _result_to_dict(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return dict(result)
    proto = getattr(result, "proto", result)
    batch_request_id = str(getattr(proto, "batch_request_id", "") or "")
    error = getattr(proto, "error", None)
    code = int(getattr(error, "code", 0) or 0) if error is not None else 0
    out: dict[str, Any] = {
        "batch_request_id": batch_request_id,
        "success": code == 0,
        "error": None,
    }
    if code:
        out["error"] = {
            "code": code,
            "message": str(getattr(error, "message", "") or ""),
        }
    data = getattr(proto, "response", None)
    completion = _completion_from_result_data(data)
    if completion is not None:
        cid = str(getattr(completion, "id", "") or "").strip()
        if cid:
            out["id"] = cid
        model = str(getattr(completion, "model", "") or "").strip()
        if model:
            out["model"] = model
        text = _completion_text(completion)
        if text:
            out["content"] = text
        usage = _usage_from_completion(completion)
        if usage:
            out["usage"] = usage
    return out


def _completion_from_result_data(data: Any) -> Any | None:
    if data is None:
        return None
    has = getattr(data, "HasField", None)
    if callable(has):
        try:
            if has("completion_response"):
                return data.completion_response
        except (ValueError, KeyError):
            return None
        return None
    completion = getattr(data, "completion_response", None)
    if completion is None:
        return None
    if getattr(completion, "id", None) or getattr(completion, "outputs", None):
        return completion
    return None


def _completion_text(completion: Any) -> str:
    """Extract assistant text from a completion proto or SDK Response wrapper.

    Chat ``GetChatCompletionResponse`` uses ``CompletionMessage.content`` as a
    **string**, not repeated ``Content`` parts (those are on request messages).
    """
    direct = getattr(completion, "content", None)
    if isinstance(direct, str) and direct:
        return direct
    parts: list[str] = []
    for output in getattr(completion, "outputs", None) or []:
        message = getattr(output, "message", None)
        if message is None:
            continue
        content = getattr(message, "content", None)
        if isinstance(content, str):
            if content:
                parts.append(content)
            continue
        for item in content or []:
            text = getattr(item, "text", None)
            if text:
                parts.append(str(text))
    return "".join(parts)


def _usage_from_completion(completion: Any) -> dict[str, Any] | None:
    usage = getattr(completion, "usage", None)
    if usage is None:
        return None
    out: dict[str, Any] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = getattr(usage, key, None)
        if value is not None:
            out[key] = value
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


def _chat_request_to_sdk(sdk_client: Any, req: dict[str, Any]) -> Any:
    """Map a chat-shaped JSON dict onto ``sdk_client.chat.create`` (SDK batch.add)."""
    from xaikit.provider import _build_sdk_messages, _sdk_chat_kwargs

    model = str(req.get("model") or "").strip()
    if not model:
        raise RuntimeError("Batch request model is empty")
    messages = req.get("messages")
    if not isinstance(messages, list) or not messages:
        raise RuntimeError("Batch request messages are empty")
    thought = req.get("thought_level") or req.get("reasoning_effort")
    temperature = req.get("temperature")
    kwargs = _sdk_chat_kwargs(
        model=model,
        temperature=float(temperature) if temperature is not None else 0.7,
        max_tokens=req.get("max_tokens"),
        thought_level=str(thought).strip() if thought else None,
        tools=req.get("tools"),
        tool_choice=req.get("tool_choice"),
        parallel_tool_calls=req.get("parallel_tool_calls"),
        response_format=req.get("response_format"),
    )
    if req.get("top_p") is not None:
        kwargs["top_p"] = req["top_p"]
    if req.get("seed") is not None:
        kwargs["seed"] = req["seed"]
    batch_request_id = str(req.get("batch_request_id") or "").strip() or None
    chat_messages = _build_sdk_messages(
        messages,
        system_prompt=req.get("system_prompt"),
    )
    chat_api = getattr(sdk_client, "chat", None)
    if chat_api is None or not hasattr(chat_api, "create"):
        raise RuntimeError("SDK client has no chat.create for batch requests")
    return chat_api.create(
        messages=chat_messages,
        batch_request_id=batch_request_id,
        **kwargs,
    )
