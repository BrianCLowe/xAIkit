"""Contract tests: batch SDK wiring (helper kwargs, guards, metering)."""

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
from xaikit.batch import call_batch_rpc, list_results_to_dict


def _client(*, usage_meter: UsageMeter | None = None, **kwargs: Any) -> XaiClient:
    kwargs.setdefault("model", "grok-3-mini")
    return XaiClient(
        provider=MockChatProvider(),
        api_key="test-key",
        usage_meter=usage_meter,
        retry_policy=default_retry_policy(max_attempts=1),
        **kwargs,
    )


class _RpcCapture:
    def __init__(self, returns: Any | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.returns = returns if returns is not None else {"id": "batch_1", "name": "job"}

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _rpc(operation: str, *, sdk_client: Any = None, **kwargs: Any) -> Any:
            self.calls.append({"operation": operation, **kwargs})
            if callable(self.returns):
                return self.returns(operation, **kwargs)
            return self.returns

        monkeypatch.setattr("xaikit.client.call_batch_rpc", _rpc)


def test_create_batch_passes_helper_kwargs_and_meters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    meter = UsageMeter(sink=sink)
    client = _client(usage_meter=meter)
    cap = _RpcCapture({"id": "batch_1", "name": "nightly", "state": {"num_requests": 0}})
    cap.install(monkeypatch)

    out = client.create_batch(
        "nightly",
        input_file_id="file_abc",
        purpose="demo.batch",
        parent_id="p1",
        labels={"request_id": "b1"},
    )

    assert out["id"] == "batch_1"
    assert out["name"] == "nightly"
    assert len(cap.calls) == 1
    call = cap.calls[0]
    assert call["operation"] == "create"
    assert call["name"] == "nightly"
    assert call["input_file_id"] == "file_abc"

    ev = list(sink.iter_events())[0]
    assert ev.purpose == "demo.batch"
    assert ev.modality == "batch"
    assert ev.model == "batch"
    assert ev.success is True
    assert ev.estimated_usd is None
    assert ev.parent_id == "p1"
    assert ev.labels["request_id"] == "b1"


def test_add_batch_requests_passes_chat_shaped_dicts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _RpcCapture({"id": "batch_1"})
    cap.install(monkeypatch)

    requests = [
        {
            "messages": [{"role": "user", "content": "capital of France?"}],
            "temperature": 0.2,
            "max_tokens": 32,
            "batch_request_id": "fr",
        }
    ]
    out = client.add_batch_requests("batch_1", requests)
    assert out["id"] == "batch_1"
    call = cap.calls[0]
    assert call["operation"] == "add"
    assert call["batch_id"] == "batch_1"
    assert call["requests"][0]["model"] == "grok-3-mini"
    assert call["requests"][0]["messages"][0]["content"] == "capital of France?"
    assert call["requests"][0]["batch_request_id"] == "fr"
    assert call["requests"][0]["temperature"] == 0.2
    assert call["requests"][0]["max_tokens"] == 32


def test_add_batch_requests_contracts_4_6_and_4_5(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(model="grok-4.6")
    cap = _RpcCapture({"id": "batch_1"})
    cap.install(monkeypatch)

    client.add_batch_requests(
        "batch_1",
        [{"messages": [{"role": "user", "content": "hi"}]}],
    )
    assert cap.calls[0]["requests"][0]["model"] == "grok-4.3"

    cap.calls.clear()
    client.add_batch_requests(
        "batch_1",
        [{"model": "grok-4.5", "messages": [{"role": "user", "content": "hi"}]}],
    )
    assert cap.calls[0]["requests"][0]["model"] == "grok-4.3"

    cap.calls.clear()
    client.add_batch_requests(
        "batch_1",
        [{"model": "grok-4.3", "messages": [{"role": "user", "content": "hi"}]}],
    )
    assert cap.calls[0]["requests"][0]["model"] == "grok-4.3"


def test_get_and_list_results_helper_kwargs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()

    def _returns(operation: str, **kwargs: Any) -> Any:
        if operation == "get":
            return {
                "id": kwargs["batch_id"],
                "name": "nightly",
                "state": {"num_pending": 1, "num_success": 0},
            }
        if operation == "list_results":
            return {
                "results": [
                    {
                        "batch_request_id": "fr",
                        "success": True,
                        "content": "Paris",
                    }
                ],
                "pagination_token": None,
            }
        raise AssertionError(operation)

    cap = _RpcCapture(_returns)
    cap.install(monkeypatch)

    status = client.get_batch("batch_1")
    assert status["id"] == "batch_1"
    assert status["state"]["num_pending"] == 1

    results = client.list_batch_results("batch_1", limit=10)
    assert results["results"][0]["content"] == "Paris"
    ops = [c["operation"] for c in cap.calls]
    assert ops == ["get", "list_results"]
    assert cap.calls[0]["batch_id"] == "batch_1"
    assert cap.calls[1]["batch_id"] == "batch_1"
    assert cap.calls[1]["limit"] == 10


def test_list_and_cancel_helper_kwargs(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client()

    def _returns(operation: str, **kwargs: Any) -> Any:
        if operation == "list":
            return {
                "batches": [{"id": "batch_1", "name": "nightly"}],
                "pagination_token": "next",
            }
        if operation == "cancel":
            return {"id": kwargs["batch_id"], "name": "nightly"}
        raise AssertionError(operation)

    cap = _RpcCapture(_returns)
    cap.install(monkeypatch)

    listed = client.list_batches(limit=5, pagination_token="tok")
    assert listed["batches"][0]["id"] == "batch_1"
    assert listed["pagination_token"] == "next"
    cancelled = client.cancel_batch("batch_1")
    assert cancelled["id"] == "batch_1"
    assert cap.calls[0]["operation"] == "list"
    assert cap.calls[0]["limit"] == 5
    assert cap.calls[0]["pagination_token"] == "tok"
    assert cap.calls[1]["operation"] == "cancel"
    assert cap.calls[1]["batch_id"] == "batch_1"


def test_empty_name_id_and_requests_rejected_before_rpc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    cap = _RpcCapture()
    cap.install(monkeypatch)

    with pytest.raises(RuntimeError, match="empty"):
        client.create_batch("   ")
    with pytest.raises(RuntimeError, match="empty"):
        client.get_batch("")
    with pytest.raises(RuntimeError, match="empty"):
        client.add_batch_requests("batch_1", [])
    with pytest.raises(RuntimeError, match="empty"):
        client.add_batch_requests(
            "batch_1",
            [{"model": "grok-3-mini", "messages": []}],
        )
    with pytest.raises(RuntimeError, match="empty"):
        client.list_batch_results("  ")
    with pytest.raises(RuntimeError, match="empty"):
        client.cancel_batch(None)  # type: ignore[arg-type]
    assert cap.calls == []


def test_create_batch_requires_purpose_when_metered() -> None:
    client = _client(usage_meter=UsageMeter(sink=InMemoryUsageSink()))
    with pytest.raises(ValueError, match="purpose"):
        client.create_batch("nightly")


def test_create_batch_failure_records_failed_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = InMemoryUsageSink()
    client = _client(usage_meter=UsageMeter(sink=sink))

    def _boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("offline")

    monkeypatch.setattr("xaikit.client.call_batch_rpc", _boom)
    with pytest.raises(RuntimeError, match="Batch create failed"):
        client.create_batch("nightly", purpose="demo.batch.fail")

    ev = list(sink.iter_events())[0]
    assert ev.success is False
    assert ev.modality == "batch"
    assert ev.purpose == "demo.batch.fail"
    assert ev.model == "batch"
    assert ev.estimated_usd is None


def test_create_batch_without_helper_and_sdk_raises() -> None:
    client = _client()
    with pytest.raises(RuntimeError, match="Batch"):
        client.create_batch("nightly")


def test_call_batch_rpc_create_and_add_use_sdk_subclient() -> None:
    created: list[dict[str, Any]] = []
    added: list[dict[str, Any]] = []

    class _Chat:
        proto = object()
        _batch_request_id = "fr"

        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    class _FakeSdk:
        def __init__(self) -> None:
            self.chat = SimpleNamespace(create=self._create_chat)
            self.batch = SimpleNamespace(create=self._create, add=self._add)

        def _create(self, name: str, *, input_file_id: str | None = None) -> Any:
            created.append({"name": name, "input_file_id": input_file_id})
            return SimpleNamespace(
                batch_id="batch_9",
                name=name,
                input_file_id=input_file_id or "",
                state=SimpleNamespace(
                    num_requests=0,
                    num_pending=0,
                    num_success=0,
                    num_error=0,
                    num_cancelled=0,
                ),
            )

        def _create_chat(self, **kwargs: Any) -> _Chat:
            return _Chat(**kwargs)

        def _add(self, batch_id: str, batch_requests: list[Any]) -> None:
            added.append({"batch_id": batch_id, "n": len(batch_requests)})

    sdk = _FakeSdk()
    out = call_batch_rpc(
        "create",
        sdk_client=sdk,
        name="nightly",
        input_file_id="file_1",
    )
    assert out["id"] == "batch_9"
    assert out["name"] == "nightly"
    assert out["input_file_id"] == "file_1"
    assert created == [{"name": "nightly", "input_file_id": "file_1"}]

    added_out = call_batch_rpc(
        "add",
        sdk_client=sdk,
        batch_id="batch_9",
        requests=[
            {
                "model": "grok-3-mini",
                "messages": [{"role": "user", "content": "hi"}],
                "batch_request_id": "fr",
            }
        ],
    )
    assert added_out == {"id": "batch_9"}
    assert added == [{"batch_id": "batch_9", "n": 1}]


def test_list_results_maps_proto_completion_string_content() -> None:
    """Live SDK results use CompletionMessage.content as a string, not parts."""
    from xai_sdk.batch import ListBatchResultsResponse
    from xai_sdk.proto import batch_pb2, chat_pb2

    completion = chat_pb2.GetChatCompletionResponse(id="cmpl_1", model="grok-3-mini")
    output = completion.outputs.add()
    output.message.content = "Paris"
    completion.usage.prompt_tokens = 4
    completion.usage.completion_tokens = 1
    completion.usage.total_tokens = 5

    row = batch_pb2.BatchResult(batch_request_id="fr")
    row.response.completion_response.CopyFrom(completion)
    page = batch_pb2.ListBatchResultsResponse()
    page.results.append(row)
    page.pagination_token = "next"

    mapped = list_results_to_dict(ListBatchResultsResponse(page))
    assert mapped["pagination_token"] == "next"
    result = mapped["results"][0]
    assert result["batch_request_id"] == "fr"
    assert result["success"] is True
    assert result["content"] == "Paris"
    assert result["model"] == "grok-3-mini"
    assert result["id"] == "cmpl_1"
    assert result["usage"] == {
        "prompt_tokens": 4,
        "completion_tokens": 1,
        "total_tokens": 5,
    }
