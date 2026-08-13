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

## Credentials and OAuth

Pass `api_key=` or a `CredentialStore` (`EnvCredentialStore` / `DictCredentialStore`). The kit does **not** hardcode xAI portal URLs. OAuth helpers take **caller-supplied** `authorize_url` and `token_url`.

```python
from xaikit import (
    build_oauth_authorize_url,
    exchange_oauth_code,
    oauth_is_configured,
)

# Your app supplies the IdP endpoints — not the kit.
authorize = "https://idp.example.com/authorize"
token = "https://idp.example.com/token"

assert oauth_is_configured(client_id="app-id", client_secret="app-secret")
url = build_oauth_authorize_url(
    client_id="app-id",
    redirect_uri="https://app.example.com/callback",
    state="nonce-1",
    authorize_url=authorize,
)
# tokens = exchange_oauth_code(
#     code,
#     client_id="app-id",
#     client_secret="app-secret",
#     redirect_uri="https://app.example.com/callback",
#     token_url=token,
# )
```

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

## Embeddings

REST embeddings on `XaiClient` (mocked HTTP in tests). `embed` posts JSON to `/v1/embeddings` and returns `{object, model, data, usage}` where `data` is `[{index, embedding}, …]`. Pin `model=` (OpenAPI examples use `v1`; there is no documented grok-embedding default). Empty input is rejected before HTTP.

```python
from xaikit import MockChatProvider, XaiClient

client = XaiClient(provider=MockChatProvider(), api_key="test-key")
# Live: XaiClient(api_key=os.environ["XAI_API_KEY"])

out = client.embed(["query: hello", "passage: world"], model="v1")
vectors = [row["embedding"] for row in out["data"]]
```

When a usage meter is attached, `purpose=` is required. Events use `modality="embed"`. The public pricing table has no embeddings rate, so the meter records tokens without inventing USD.

## Tokenizer

REST tokenize on `XaiClient` (mocked HTTP in tests). `tokenize` posts JSON to `/v1/tokenize-text` and returns `{tokens, count, model}` where `tokens` is `[{token_id, string, token_bytes}, …]` (plain dicts, not protobuf). `model=` defaults to the client's chat model. Empty text is rejected before HTTP.

```python
from xaikit import MockChatProvider, XaiClient

client = XaiClient(provider=MockChatProvider(), api_key="test-key")
# Live: XaiClient(api_key=os.environ["XAI_API_KEY"])

out = client.tokenize("Hello world")
n = out["count"]
pieces = [row["string"] for row in out["tokens"]]
```

When a usage meter is attached, `purpose=` is required. Events use `modality="tokenize"`. The public pricing table has no tokenizer rate, so the meter records the token count without inventing USD.

## Batch

SDK batch on `XaiClient` (mocked helper in tests — never hits gRPC). `create_batch` / `add_batch_requests` submit a job; `get_batch` polls status; `list_batch_results` reads completions as JSON dicts (no protobuf). Requests are chat-shaped dicts (`model`, `messages`, knobs). Empty name / batch id / requests are rejected before the RPC.

```python
from xaikit import MockChatProvider, XaiClient

client = XaiClient(provider=MockChatProvider(), api_key="test-key")
# Live: XaiClient(api_key=os.environ["XAI_API_KEY"])

job = client.create_batch("nightly-capitals")
client.add_batch_requests(
    job["id"],
    [
        {
            "messages": [{"role": "user", "content": "Capital of France?"}],
            "batch_request_id": "fr",
        }
    ],
)
status = client.get_batch(job["id"])
# status["state"]["num_pending"] / num_success / …
# results = client.list_batch_results(job["id"])
```

When a usage meter is attached, `purpose=` is required. Events use `modality="batch"`. The public pricing table has no batch rate, so the meter records purpose/success without inventing USD.

## Collections

SDK collections on `XaiClient` (mocked helper in tests — never hits gRPC). `create_collection` / `upload_document` / `search_collections` cover the upload-and-query path; `get_collection` / `list_collections` / `delete_collection` are included. Returns JSON dicts (no protobuf). Empty name / collection id / query / file bytes are rejected before the RPC.

Live create / get / list / delete / upload use xAI's management API. Set `XAI_MANAGEMENT_KEY` in the environment (the SDK reads it). Search uses the regular API key. This client does not take a second key argument.

```python
from xaikit import MockChatProvider, XaiClient

client = XaiClient(provider=MockChatProvider(), api_key="test-key")
# Live: XaiClient(api_key=os.environ["XAI_API_KEY"])  # plus XAI_MANAGEMENT_KEY in env

coll = client.create_collection("docs")
client.upload_document(coll["id"], "note.txt", b"hello world")
hits = client.search_collections("hello", coll["id"])
# hits["matches"][0]["chunk_content"] / file_id / score
```

When a usage meter is attached, `purpose=` is required. Events use `modality="collections"`. The public pricing table has no collections rate, so the meter records purpose/success without inventing USD.

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

Default model is `grok-voice-latest`. Constructor `voice_model=` overrides like `video_model=`. Custom `voice_id` strings on `voice=` work the same as built-in names like `eve`. REST STT/TTS stay on `transcribe` / `synthesize_speech`. Streaming STT is `open_stt_session`; streaming TTS is `open_tts_session` (not speech-to-speech).

Mint a short-lived token on the **server** so the long-lived API key never reaches the browser. Pass `value` to the client (`Authorization: Bearer <token>`, or `realtime_client_secret_protocol(token)` for `sec-websocket-protocol`).

```python
from xaikit import MockChatProvider, XaiClient, realtime_client_secret_protocol

client = XaiClient(provider=MockChatProvider(), api_key="test-key")
# Live: XaiClient(api_key=os.environ["XAI_API_KEY"])  # server-side only

secret = client.create_realtime_client_secret(expires_after=300)
token = secret["value"]
# Client WS: Authorization: Bearer {token}
protocol = realtime_client_secret_protocol(token)  # "xai-client-secret.{token}"
```

## Streaming speech-to-text

Unary-transcribe over `wss://api.x.ai/v1/stt`. Send raw PCM bytes (not base64). This is not the realtime voice (STS) socket.

```python
from xaikit import MockChatProvider, XaiClient

client = XaiClient(provider=MockChatProvider(), api_key="test-key")
# Live: XaiClient(api_key=os.environ["XAI_API_KEY"])

pcm16_bytes = bytes(3200)  # 100 ms of 16 kHz s16le PCM — apps own capture
with client.open_stt_session(language="en", interim_results=True) as session:
    session.send_audio(pcm16_bytes)
    session.audio_done()
    for event in session.events():
        if event.get("type") == "transcript.partial":
            print(event.get("text"))
        elif event.get("type") == "transcript.done":
            break
```

REST file transcription stays on `transcribe`. Offline tests mock the socket.

## Streaming text-to-speech

Bidirectional TTS over `wss://api.x.ai/v1/tts`. Send text deltas; receive base64 `audio.delta` chunks. This is not the realtime voice (STS) socket.

```python
from xaikit import MockChatProvider, XaiClient, decode_tts_audio

client = XaiClient(provider=MockChatProvider(), api_key="test-key")
# Live: XaiClient(api_key=os.environ["XAI_API_KEY"])

with client.open_tts_session(language="en", voice="eve", codec="mp3") as session:
    session.send_text("Hello from streaming TTS.")
    session.text_done()
    for event in session.events():
        chunk = decode_tts_audio(event)
        if chunk:
            pass  # apps own playback
        elif event.get("type") == "audio.done":
            break
```

REST unary synthesis stays on `synthesize_speech`. Offline tests mock the socket.

## Streaming

```python
for chunk in client.chat_stream(
    [{"role": "user", "content": "hello"}],
    purpose="demo.stream",
):
    print(chunk.delta, end="", flush=True)
```

## Tools, vision, and structured JSON

The kit wraps xAI chat extras as JSON dicts. It does **not** run tools — the app owns the loop.

```python
from xaikit import MockChatProvider, XaiClient

weather_tool = {
    "name": "get_weather",
    "description": "Get the weather for a city.",
    "parameters": {
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
    },
}
client = XaiClient(
    provider=MockChatProvider(
        replies=[
            "a cube",
            {
                "tool_calls": [
                    {"id": "call_1", "name": "get_weather", "arguments": {"city": "NYC"}},
                ],
            },
            {"title": "blue"},
        ]
    ),
    model="grok-4.5",
)

# Vision: content may be a string or a list of parts
client.chat(
    [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "What is in this image?"},
                {"type": "image_url", "url": "https://example.com/cube.png"},
            ],
        }
    ]
)

# Tools: defs in, tool_calls out (arguments are parsed JSON, typically a dict)
resp = client.chat(
    [{"role": "user", "content": "Weather in NYC?"}],
    tools=[weather_tool],
    tool_choice="auto",
)
# resp.tool_calls → [{"id": "call_1", "name": "get_weather", "arguments": {"city": "NYC"}}]
# App runs the function, then sends the assistant turn + tool result:
# client.chat([
#     {"role": "user", "content": "Weather in NYC?"},
#     {"role": "assistant", "content": "", "tool_calls": resp.tool_calls},
#     {"role": "tool", "content": "72F", "tool_call_id": resp.tool_calls[0]["id"]},
# ], tools=[weather_tool])

# Native structured outputs (fence-stripping remains the fallback)
schema = {
    "type": "object",
    "properties": {"title": {"type": "string"}},
    "required": ["title"],
}
data = client.chat_json("Name a color", schema=schema)
```

## Responses API (built-in tools)

Additive REST wrap of `POST /v1/responses`. **Chat remains the default text path** (`chat` / `chat_stream`). Built-in server tools (web search, X search, code interpreter, collections/`file_search`, image generation) are **opt-in** — they are never sent unless you pass `tools=`.

```python
from xaikit import MockChatProvider, XaiClient

client = XaiClient(provider=MockChatProvider(), api_key="test-key")
# Live: XaiClient(api_key=os.environ["XAI_API_KEY"])

out = client.create_response(
    "What is 101*3?",
    tools=[{"type": "code_interpreter"}],  # omit tools= for text-only
)
# out["id"] / out["output"] / out["usage"]
# client.get_response(out["id"])
```

When a usage meter is attached, `purpose=` is required. Events use `modality="responses"`. The public pricing table has no Responses/tools rate, so the meter records tokens without inventing USD.

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
