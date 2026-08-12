# XaiKit HTTP mount examples *(docs only)*

Thin FastAPI (Starlette-based) sample routes that wrap the typed `XaiClient` API.

**Not** product identity. **Not** shipped as a required package surface. Prefer calling `XaiClient` directly from app code; copy this pattern only when you intentionally want a REST boundary.

## What you get

| File | Role |
|------|------|
| `fastapi_mount.py` | `create_xaikit_router(client)` / `create_app(client)` — `GET /status`, `POST /chat` |
| `run_mock_server.py` | Offline demo server with `MockChatProvider` + optional usage meter |

## Run the mock server

FastAPI and uvicorn are **optional example deps** — they are **not** listed on the `xaikit` package.

From the **repo root**:

```bash
uv run --with fastapi --with "uvicorn[standard]" --package xaikit \
  python packages/xaikit/examples/run_mock_server.py
```

Smoke the endpoints:

```bash
curl -s http://127.0.0.1:8765/status
curl -s -X POST http://127.0.0.1:8765/chat \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"ping"}],"purpose":"example.chat"}'
```

`purpose` is required in this demo because the mock server attaches a `UsageMeter` (same rule as the typed API).

## Mount in your own FastAPI app

```python
from fastapi import FastAPI
from xaikit import MockChatProvider, XaiClient

# Copy fastapi_mount.py into your app, or add examples/ to PYTHONPATH while experimenting.
from fastapi_mount import create_xaikit_router

client = XaiClient(provider=MockChatProvider(replies="hi"), model="grok-3-mini")
app = FastAPI()
app.include_router(create_xaikit_router(client, prefix="/xaikit"))
```

Prefer calling `XaiClient` methods directly from agents and services. Use HTTP only when a REST boundary is intentional.

## Starlette

Same idea without FastAPI: inject an `XaiClient`, expose a `GET` status JSON route and a `POST` that parses JSON → `client.chat(...)` → JSON response. FastAPI here is just the thin ergonomic wrapper over Starlette.
