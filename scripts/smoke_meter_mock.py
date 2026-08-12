#!/usr/bin/env python3
"""Exercise path: metered mock chat + in-memory sink (no live key).

Run from repo root::

    uv run --package xaikit python packages/xaikit/scripts/smoke_meter_mock.py
"""

from __future__ import annotations

from xaikit import (
    InMemoryUsageSink,
    MockChatProvider,
    UsageMeter,
    XaiClient,
    default_price_table,
    default_retry_policy,
)


def main() -> None:
    sink = InMemoryUsageSink()
    meter = UsageMeter(sink=sink, price_table=default_price_table())
    provider = MockChatProvider(
        replies={"summary": "smoke ok", "confidence": 0.9},
        default_usage={"prompt_tokens": 100, "completion_tokens": 40},
    )
    client = XaiClient(
        provider=provider,
        model="grok-3-mini",
        usage_meter=meter,
        thought_level="low",
        retry_policy=default_retry_policy(max_attempts=1, backoff_seconds=0.0),
    )

    text = client.chat(
        [{"role": "user", "content": "ping"}],
        purpose="smoke.chat",
    )
    data = client.chat_json(
        "return a summary object",
        purpose="smoke.json",
        parent_id="smoke-run",
    )

    events = list(sink.iter_events())
    rollups = meter.rollup_by_purpose()
    print("chat content:", text.content)
    print("json keys:", sorted(data.keys()))
    print("event_count:", len(events))
    print("rollup_by_purpose:")
    for r in rollups:
        print(
            f"  {r.key}: events={r.event_count} "
            f"tokens={r.total_tokens} usd~={r.estimated_usd}"
        )
    if len(events) < 2:
        raise SystemExit("smoke failed: expected ≥2 metered events")
    print("smoke_meter_mock: OK")


if __name__ == "__main__":
    main()
