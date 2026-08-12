# XaiKit

Extractable **xAI transport + living model catalog + connect + usage metering** as a library-first Python kit.

Built for apps that want a typed Grok/xAI client with purpose-tagged usage events, catalog resolve (`cheapest` / `best`), inject credential stores, and a mock provider for CI — without pulling in a multi-provider marketplace.

Primary consumers today: [Rivenquill](https://github.com/BrianCLowe/Rivenquill) (writing assistant) and sibling apps after cutover.

## Install

```bash
# From a release tag (Docker / CI / other repos)
uv add "xaikit @ git+https://github.com/BrianCLowe/xAIkit@v0.1.0"

# Or editable neighbor checkout
uv add --editable ../xAIkit
```

PyPI publish may follow once the API settles.

## Develop

```bash
uv sync --group dev
uv run pytest
uv run python scripts/smoke_meter_mock.py
```

## Quick usage

```python
from xaikit import (
    InMemoryUsageSink,
    MockChatProvider,
    UsageMeter,
    XaiClient,
)

meter = UsageMeter(sink=InMemoryUsageSink())
client = XaiClient(
    provider=MockChatProvider(replies="hi"),
    model="grok-4.5",
    usage_meter=meter,
)
resp = client.chat([{"role": "user", "content": "hello"}], purpose="demo.chat")
```

When `usage_meter` is attached, **purpose is required**. Without a meter, purpose is optional.

## Streaming

```python
for chunk in client.chat_stream(
    [{"role": "user", "content": "hello"}],
    purpose="demo.stream",
):
    print(chunk.delta, end="", flush=True)
```

## Opt-in dev completion traces *(default off)*

```python
from xaikit import CompletionTracer, InMemoryTraceSink, MockChatProvider, XaiClient

tracer = CompletionTracer(sink=InMemoryTraceSink())
client = XaiClient(
    provider=MockChatProvider(replies="hi"),
    model="grok-4.5",
    completion_tracer=tracer,
)
client.chat([{"role": "user", "content": "hello"}])
```

## Optional gap log *(companion — default off)*

```bash
uv run python -m xaikit.gaps --path ./gaps.jsonl
# or: xaikit-gaps --path ./gaps.jsonl --kind capability_gap
```

## HTTP mounts *(examples/docs only)*

Thin FastAPI samples under [`examples/`](examples/) — not required package surface.

## License

MIT
