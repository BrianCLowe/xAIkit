# XaiKit

Extractable **xAI transport + living model catalog + connect + usage metering** as a library-first Python kit.

Built for apps that want a typed Grok/xAI client with purpose-tagged usage events, catalog resolve (`cheapest` / `economy` / `best`), inject credential stores, and a mock provider for CI — without pulling in a multi-provider marketplace.

## Install

```bash
# From a release tag (Docker / CI / other repos)
uv add "xaikit @ git+https://github.com/BrianCLowe/xAIkit@v0.1.0"

# Or editable neighbor checkout
uv add --editable ../xAIkit
```

PyPI publish may follow once the API settles.

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

## Video generation

REST Imagine video on `XaiClient` (mocked HTTP in tests; live calls need `XAI_API_KEY`). Default `wait=True` polls until the clip is ready; `wait=False` returns `request_id` for `poll_video`.

```python
from xaikit import MockChatProvider, XaiClient

client = XaiClient(provider=MockChatProvider(), api_key="test-key")
# Live: XaiClient(api_key=os.environ["XAI_API_KEY"])

started = client.generate_video(
    "A red cube rotating on a table",
    duration=8,
    aspect_ratio="16:9",
    resolution="480p",
    wait=False,
)
status = client.poll_video(started["request_id"])
# bytes = client.download_video(status["url"])  # when status == "done"
```

`extend_video(prompt, video_url=...)` continues a clip. Default model is `grok-imagine-video-1.5`.

## Realtime voice

Speech-to-speech over the documented xAI realtime WebSocket (`wss://api.x.ai/v1/realtime`). No mic, recorder, or playground in this library — apps own capture/playback. Offline tests mock the socket.

```python
from xaikit import MockChatProvider, XaiClient, decode_realtime_audio

client = XaiClient(provider=MockChatProvider(), api_key="test-key")
# Live: XaiClient(api_key=os.environ["XAI_API_KEY"])

with client.open_realtime_session(
    voice="eve",
    instructions="You are a helpful assistant.",
) as session:
    session.send_text("Hello!")
    event = session.recv(timeout=30)
    # audio bytes: decode_realtime_audio(event)  # when type is response.output_audio.delta
    # session.send_audio(pcm16_bytes)
```

Default model is `grok-voice-latest`. Constructor `voice_model=` overrides like `video_model=`. REST STT/TTS stay on `transcribe` / `synthesize_speech`.

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

Contributor / agent docs (not part of the installed package): [`docs/Master_Index.md`](docs/Master_Index.md).
