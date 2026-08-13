"""Offline tests for OpenTelemetryUsageSink — mock opentelemetry.metrics (no extra)."""

from __future__ import annotations

import importlib
from typing import Any
from unittest.mock import MagicMock

import pytest

from xaikit import (
    CompositeUsageSink,
    InMemoryUsageSink,
    MockChatProvider,
    OpenTelemetryUsageSink,
    UsageEvent,
    UsageMeter,
    XaiClient,
    default_retry_policy,
)


def _meter_with_instruments() -> tuple[MagicMock, MagicMock, MagicMock]:
    calls = MagicMock(name="calls")
    tokens = MagicMock(name="tokens")
    meter = MagicMock(name="meter")

    def _create_counter(name: str, **_kwargs: Any) -> MagicMock:
        if name == "xaikit.usage.calls":
            return calls
        if name == "xaikit.usage.tokens":
            return tokens
        raise AssertionError(f"unexpected counter {name}")

    meter.create_counter.side_effect = _create_counter
    return meter, calls, tokens


def test_append_records_call_and_token_counters_with_attributes() -> None:
    meter, calls, tokens = _meter_with_instruments()
    sink = OpenTelemetryUsageSink(meter=meter)
    event = UsageEvent(
        purpose="demo.chat",
        model="grok-4.5",
        prompt_tokens=10,
        completion_tokens=5,
        modality="chat",
        success=True,
        error="TimeoutError",
    )
    sink.append(event)

    expected = {
        "purpose": "demo.chat",
        "model": "grok-4.5",
        "modality": "chat",
        "success": True,
    }
    calls.add.assert_called_once_with(1, attributes=expected)
    tokens.add.assert_called_once_with(15, attributes=expected)
    attr_keys = set(calls.add.call_args.kwargs["attributes"])
    assert "error" not in attr_keys
    assert "prompt" not in " ".join(attr_keys)


def test_append_skips_token_counter_when_tokens_unknown() -> None:
    meter, calls, tokens = _meter_with_instruments()
    sink = OpenTelemetryUsageSink(meter=meter)
    sink.append(
        UsageEvent(
            purpose="files.upload",
            model="",
            modality="files",
            success=False,
        )
    )
    calls.add.assert_called_once_with(
        1,
        attributes={
            "purpose": "files.upload",
            "model": "",
            "modality": "files",
            "success": False,
        },
    )
    tokens.add.assert_not_called()


def test_default_meter_uses_get_meter_xaikit(monkeypatch: pytest.MonkeyPatch) -> None:
    metrics = MagicMock()
    otel_meter, _, _ = _meter_with_instruments()
    metrics.get_meter.return_value = otel_meter

    def _import(name: str, package: str | None = None) -> Any:
        if name == "opentelemetry.metrics":
            return metrics
        return importlib.import_module(name, package)

    monkeypatch.setattr("xaikit.usage.importlib.import_module", _import)
    OpenTelemetryUsageSink()
    metrics.get_meter.assert_called_once_with("xaikit")
    names = [c.args[0] for c in otel_meter.create_counter.call_args_list]
    assert names == ["xaikit.usage.calls", "xaikit.usage.tokens"]


def test_injected_meter_does_not_import_opentelemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _import(name: str, package: str | None = None) -> Any:
        raise AssertionError(f"unexpected import {name}")

    monkeypatch.setattr("xaikit.usage.importlib.import_module", _import)
    meter, _, _ = _meter_with_instruments()
    OpenTelemetryUsageSink(meter=meter)


def test_missing_opentelemetry_raises_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _import(name: str, package: str | None = None) -> Any:
        if name == "opentelemetry.metrics":
            raise ImportError("No module named 'opentelemetry.metrics'")
        return importlib.import_module(name, package)

    monkeypatch.setattr("xaikit.usage.importlib.import_module", _import)
    with pytest.raises(RuntimeError, match=r"xaikit\[otel\]") as excinfo:
        OpenTelemetryUsageSink()
    assert "opentelemetry-api" in str(excinfo.value)


def test_iter_events_is_export_only() -> None:
    meter, _, _ = _meter_with_instruments()
    sink = OpenTelemetryUsageSink(meter=meter)
    with pytest.raises(NotImplementedError, match="export-only"):
        sink.iter_events()


def test_composite_memory_first_inspects_events() -> None:
    meter, calls, _ = _meter_with_instruments()
    memory = InMemoryUsageSink()
    otel = OpenTelemetryUsageSink(meter=meter)
    composite = CompositeUsageSink(memory, otel)
    meter_obj = UsageMeter(sink=composite)
    event = meter_obj.record(purpose="demo.chat", model="grok-4.5", modality="chat")
    assert list(memory.iter_events()) == [event]
    assert list(composite.iter_events()) == [event]
    calls.add.assert_called_once()


def test_append_propagates_meter_errors() -> None:
    meter, calls, _ = _meter_with_instruments()
    calls.add.side_effect = RuntimeError("otel down")
    sink = OpenTelemetryUsageSink(meter=meter)
    with pytest.raises(RuntimeError, match="otel down"):
        sink.append(UsageEvent(purpose="demo.chat", model="grok-4.5"))


def test_usage_meter_record_propagates_sink_errors() -> None:
    """UsageMeter.record does not swallow sink failures (client._record does)."""
    meter, calls, _ = _meter_with_instruments()
    calls.add.side_effect = RuntimeError("otel down")
    usage_meter = UsageMeter(sink=OpenTelemetryUsageSink(meter=meter))
    with pytest.raises(RuntimeError, match="otel down"):
        usage_meter.record(purpose="demo.chat", model="grok-4.5")


def test_client_chat_survives_otel_sink_error() -> None:
    """XaiClient._record logs meter/sink failures and still returns the reply."""
    meter, calls, _ = _meter_with_instruments()
    calls.add.side_effect = RuntimeError("otel down")
    client = XaiClient(
        provider=MockChatProvider(replies="hello"),
        model="grok-4.5",
        usage_meter=UsageMeter(sink=OpenTelemetryUsageSink(meter=meter)),
        retry_policy=default_retry_policy(max_attempts=1),
    )
    resp = client.chat(
        [{"role": "user", "content": "hi"}],
        purpose="demo.chat",
    )
    assert resp.content == "hello"
    calls.add.assert_called_once()
