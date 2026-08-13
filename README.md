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

## Catalog resolve

Callers pass `cheapest` / `economy` / `best` (and optional `role=`). Chat is the default pool. Pin still wins when `pin=` is set.

```python
from xaikit import ModelInfo, inject_catalog, resolve_model, resolve_model_selection

inject_catalog(
    [
        ModelInfo(id="grok-4.6", capabilities=["chat"], input_per_million=20.0, created=2),
        ModelInfo(id="grok-imagine-image", capabilities=["image"], created=1),
        ModelInfo(id="grok-imagine-image-quality", capabilities=["image"], created=2),
    ]
)

chat_id = resolve_model(intent="economy")  # role="chat" default
image = resolve_model_selection(intent="best", role="image")
video_id = resolve_model(intent="cheapest", role="video")
voice_id = resolve_model(intent="economy", role="voice")
```

`role` is `chat` | `image` | `video` | `voice`. Offline tests inject fixtures with `inject_catalog` — do not hit the network.

## Image generation and edit

REST Imagine images on `XaiClient` (mocked HTTP in tests; live calls need `XAI_API_KEY`). `edit_image` posts JSON to `/v1/images/edits` (not OpenAI multipart). Source image is a public URL, data URI, or a `file_id` from `upload_file`.

```python
from xaikit import MockChatProvider, XaiClient

client = XaiClient(provider=MockChatProvider(), api_key="test-key")
# Live: XaiClient(api_key=os.environ["XAI_API_KEY"])

out = client.generate_image("A red cube on a table", aspect_ratio="1:1")
edited = client.edit_image(
    "Make it a pencil sketch",
    image_url=out["url"],  # or image_file_id="file-..."
)
# edited["url"] / edited["b64_json"] / edited["file_id"]
```

Default model is `grok-imagine-image-quality`. When Imagine returns `file_output.file_id`, both methods surface it as `file_id`.

## Files

REST Files on `XaiClient` (mocked HTTP in tests). `upload_file` posts multipart to `/v1/files` and returns `{id, filename, bytes, created_at, …}`. Kit `purpose=` is the usage-meter tag; `file_purpose=` (default `"assistants"`) is the upstream multipart field. Optional `get_file` / `delete_file` hit `/v1/files/{file_id}`.

```python
from xaikit import MockChatProvider, XaiClient

client = XaiClient(provider=MockChatProvider(), api_key="test-key")
meta = client.upload_file(b"hello", "note.txt", content_type="text/plain")
# meta["id"] is the opaque file_id
# client.get_file(meta["id"])
# client.delete_file(meta["id"])
```

Uploads larger than 50 MB are rejected before HTTP.

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
