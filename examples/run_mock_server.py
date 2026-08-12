#!/usr/bin/env python3
"""Run the examples/docs FastAPI mount with a MockChatProvider (no live key).

From repo root (FastAPI/uvicorn are *not* xaikit package deps)::

    uv run --with fastapi --with "uvicorn[standard]" --package xaikit \\
      python packages/xaikit/examples/run_mock_server.py

Then::

    curl -s http://127.0.0.1:8765/status
    curl -s -X POST http://127.0.0.1:8765/chat \\
      -H "Content-Type: application/json" \\
      -d '{"messages":[{"role":"user","content":"ping"}],"purpose":"example.chat"}'
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow `python …/run_mock_server.py` to import sibling fastapi_mount.py
_EXAMPLES = Path(__file__).resolve().parent
if str(_EXAMPLES) not in sys.path:
    sys.path.insert(0, str(_EXAMPLES))

from fastapi_mount import create_app  # noqa: E402
from xaikit import (  # noqa: E402
    InMemoryUsageSink,
    MockChatProvider,
    UsageMeter,
    XaiClient,
    default_price_table,
)


def build_demo_client() -> XaiClient:
    meter = UsageMeter(
        sink=InMemoryUsageSink(),
        price_table=default_price_table(),
    )
    return XaiClient(
        provider=MockChatProvider(
            replies="hello from xaikit example mount",
            default_usage={"prompt_tokens": 10, "completion_tokens": 8},
        ),
        model="grok-3-mini",
        usage_meter=meter,
        thought_level="low",
    )


def main() -> None:
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit(
            "uvicorn is required to run this example (not an xaikit package dep). "
            'Install ephemerally: uv run --with fastapi --with "uvicorn[standard]" '
            "--package xaikit python packages/xaikit/examples/run_mock_server.py"
        ) from exc

    app = create_app(build_demo_client())
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")


if __name__ == "__main__":
    main()
