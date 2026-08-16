<p align="center">
  <img src="https://raw.githubusercontent.com/BrianCLowe/xAIkit/master/docs/readme-header.jpg" alt="xAIkit — kit for interacting with xAI models and APIs" width="100%" />
</p>

# xAIkit

**`0.1.0`.** Not an official xAI package. The API may still change. Problems or feedback: [open an issue](https://github.com/BrianCLowe/xAIkit/issues).

**Unofficial** Python kit for the **xAI (Grok) API** — one typed client, living model catalog, usage metering, media, and realtime voice. Not a multi-provider SDK.

Requires **Python 3.10+**, the same floor as the official [xAI Python SDK](https://github.com/xai-org/xai-sdk-python).

Built for apps that want a typed Grok/xAI client with purpose-tagged usage events, catalog resolve (`cheapest` / `economy` / `best`), inject credential stores, and a mock provider for CI — without pulling in a multi-provider marketplace.

## What it does

A **Python library for the Grok / xAI API** — one typed client so your app can chat, generate images and video, speak, search collections, and meter what each feature costs. Not a chatbot UI. Not LiteLLM, OpenRouter, or another multi-provider gateway. Just xAI, as a kit you drop into an existing codebase.

| You want to… | xAIkit gives you |
| --- | --- |
| **Call Grok from Python** (chat, stream, tools, vision, structured JSON) | `XaiClient` and `AsyncXaiClient` — same method names; JSON dicts, not protobuf |
| **Generate or edit images**, make video, or do speech on xAI | Imagine generate/edit, video + extend, REST + streaming STT/TTS, realtime speech-to-speech |
| **Pick a model** without hardcoding IDs that churn | `resolve_model("cheapest" \| "economy" \| "best")` per role (`chat` / `image` / `video` / `voice`); `pin=` still wins |
| **See what a feature costs** (tokens, estimated USD, OpenTelemetry) | Purpose-tagged `UsageMeter` — `purpose=` is required when a meter is attached |
| **Test without an API key** or live spend | `MockChatProvider` + `inject_catalog` — CI stays offline |
| **Keep keys out of the browser** for realtime voice | Server-side `create_realtime_client_secret` (and the `sec-websocket-protocol` helper) |
| **Bring your own credentials / IdP** | `api_key=` or a `CredentialStore`; OAuth URLs are caller-supplied, never hardcoded |
| **Use the rest of the xAI surface** | Files, embeddings, tokenize, batch, collections, Responses, priority and deferred chat |

Not an official xAI package. Domain schemas and the tool loop stay in your app.

## How this differs from the official SDK

The official [xAI Python SDK](https://github.com/xai-org/xai-sdk-python) (`xai_sdk`) is the gRPC client xAI ships. xAIkit **uses it for live chat** and adds a kit around it:

| | Official SDK | xAIkit |
| --- | --- | --- |
| Status | Official | Unofficial kit (this repo / `xaikit-py`) |
| Chat live path | `xai_sdk.Client` / protobuf | Same SDK under `XaiClient`; you see **JSON dicts**, not protobuf |
| Tests without a key | You mock gRPC | `MockChatProvider` + `inject_catalog` |
| Model pick | You hardcode ids | `resolve_model("cheapest" \| "economy" \| "best")` per role |
| Cost | None | Purpose-tagged `UsageMeter` + a copied public price table (estimates, not invoices) |
| REST / WS extras | Separate HTTP/WS samples | Image, video, STT/TTS, realtime voice, Files, batch, collections on the same client |
| Auth | API key | API key, `CredentialStore`, or **caller-supplied** OAuth URLs — no User types, no grok.com login |

Install stays `xaikit-py`; `import xaikit`. You can use both packages in one app.

## Install

The import stays `xaikit` (the PyPI name is `xaikit-py` because `xaikit` was too close to an existing explainable-AI project).

```bash
uv add xaikit-py
# or: pip install xaikit-py

# From a git tag
uv add "xaikit-py @ git+https://github.com/BrianCLowe/xAIkit@v0.1.0"

# Editable neighbor checkout
uv add --editable ../xAIkit
```

## Problems and feedback

If something breaks, the docs are wrong, or an API is missing, [open an issue](https://github.com/BrianCLowe/xAIkit/issues). Include the package version (`python -c "import xaikit; print(xaikit.__version__)"`), how you installed (PyPI / git / editable), and a short repro. Redact API keys.

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

Async twin (`AsyncXaiClient`) uses the same method names; REST uses `httpx.AsyncClient` and live chat uses `xai_sdk.AsyncClient`. `MockChatProvider` works with both clients:

```python
import asyncio
from xaikit import AsyncXaiClient, MockChatProvider

async def main() -> None:
    client = AsyncXaiClient(provider=MockChatProvider(replies="hi"), model="grok-4.5")
    resp = await client.chat([{"role": "user", "content": "hello"}])
    print(resp.content)

asyncio.run(main())
```

When `usage_meter` is attached, **purpose is required**. Without a meter, purpose is optional.

### Pricing estimates *(not invoices)*

`UsageMeter` can attach a `PriceTable`. The bootstrap table is a **manual copy** of xAI’s public list prices — not a live billing feed and not an invoice.

- **Source:** [docs.x.ai/developers/pricing](https://docs.x.ai/developers/pricing) (chat also [docs.x.ai/docs/models](https://docs.x.ai/docs/models))
- **Last copied into the kit:** `default_price_table().fetched` (also `PRICE_TABLE_FETCHED`)
- **Refresh:** re-read those pages and update the dicts in `src/xaikit/pricing.py` (kit release), **or** overlay JSON with `load_price_table("prices.json")` / `save_price_table_template("prices.json")` without waiting on a kit bump. There is no auto-fetch on import.
- **No public rate → no invented USD.** Embeddings, tokenizer, batch, collections, Responses, Files, REST TTS, and similar still record purpose/tokens/success; `estimated_usd` stays unset.

```python
from xaikit import PRICE_TABLE_FETCHED, PRICE_TABLE_SOURCE_URL, default_price_table

table = default_price_table()
assert table.source_url == PRICE_TABLE_SOURCE_URL
assert table.fetched == PRICE_TABLE_FETCHED
# table.price_for("grok-4.6").input_per_million
```

Optional OpenTelemetry export (`pip install 'xaikit-py[otel]'`): `OpenTelemetryUsageSink` increments `xaikit.usage.calls` / `xaikit.usage.tokens` (attributes: purpose, model, modality, success). It is export-only — pair with `InMemoryUsageSink` via `CompositeUsageSink` to inspect events.

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

This is **not** grok.com / SuperGrok login. A Grok subscription’s **weekly usage pool** (Settings → Usage in the Grok app) has no public API. The kit does not scrape it, does not show “how much you have left,” and does not mint User/Session objects. `UsageMeter` only records calls **your app** made through `XaiClient`. Team API prepaid remaining lives in the [xAI Console](https://console.x.ai) Usage Explorer (a management-key billing API, not OAuth).

## Catalog resolve

Callers pass `cheapest` / `economy` / `best` (and optional `role=`). Chat is the default pool. Pin still wins when `pin=` is set.

```python
from xaikit import ModelInfo, feature_options, inject_catalog, resolve_model, resolve_model_selection

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
extend_id = resolve_model(intent="best", role="video", need="video_extend")
```

`role` is `chat` | `image` | `video` | `voice`. Offline tests inject fixtures with `inject_catalog` — do not hit the network.

`feature_options(model=)` lists extra capabilities for settings UIs (not role tags). No model → Grok 4.6 chat extras (`web_search`, `x_search`, `code_execution`, `file_attachments`, `collections_search`, `image_understanding`, `x_video_understanding`, `mcp`). Imagine quality (`grok-imagine-video`) reports `video_extend` / `video_edit` / `r2v`; `grok-imagine-video-1.5` reports `1080p` / `r2v` and not extend. Unknown or older SKUs return `[]`. Pass the same ids as `need=` on resolve so `best` is best for that job (quality over 1.5 when the job is extend).

When `model` is omitted, chat resolve falls back to `BOOTSTRAP_MODEL` (`grok-4.6`). Offline with no API key or fixture, `list_models` injects `grok-4.6` plus cheaper-band `grok-4.3`. Pass `persist_path=` to write a JSON snapshot after a live SDK fetch and reload it later; there is no default disk path.

## Image generation and edit

REST Imagine images on `XaiClient` (mocked HTTP in tests; live calls need `XAI_API_KEY`). `edit_image` posts JSON to `/v1/images/edits` (not OpenAI multipart). One source is a public URL, data URI, or a `file_id` from `upload_file`. Pass `images=` (2–3 entries, mixable kinds) for multi-image edit; the prompt may refer to `<IMAGE_0>`, `<IMAGE_1>`, `<IMAGE_2>`.

```python
from xaikit import MockChatProvider, XaiClient

client = XaiClient(provider=MockChatProvider(), api_key="test-key")
# Live: XaiClient(api_key=os.environ["XAI_API_KEY"])

out = client.generate_image(
    "A red cube on a table",
    aspect_ratio="1:1",
    resolution="2k",
    response_format="b64_json",
)
# quality= ("low" | "medium") is grok-imagine-image-2.0 only
edited = client.edit_image(
    "Make it a pencil sketch",
    image_url=out["url"],  # or image_file_id="file-..."
)
# edited["url"] / edited["b64_json"] / edited["file_id"]
# collage = client.edit_image(
#     "Put <IMAGE_0> in the style of <IMAGE_1>",
#     images=["https://example.com/a.png", {"file_id": "file-style"}],
# )
```

Default model is `grok-imagine-image-quality`. Optional generate knobs: `aspect_ratio` (Imagine list, including `auto` / `19.5:9` / `20:9`), `resolution` (`1k` | `2k`), `response_format` (`b64_json`), and `quality` (`low` | `medium`) on `grok-imagine-image-2.0` only. Unknown aspect/resolution values are omitted. When Imagine returns `file_output.file_id`, both methods surface it as `file_id`.

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

REST embeddings on `XaiClient` (mocked HTTP in tests). `embed` posts JSON to `/v1/embeddings` and returns `{object, model, data, usage}` where `data` is `[{index, embedding}, …]`. `model=` is required — the kit does not invent a default. List live ids with `GET /v1/embedding-models` (OpenAPI’s `v1` is an example and may 404; some teams have an empty roster). Collections index models are not this endpoint. Empty input is rejected before HTTP.

```python
from xaikit import MockChatProvider, XaiClient

client = XaiClient(provider=MockChatProvider(), api_key="test-key")
# Live: XaiClient(api_key=os.environ["XAI_API_KEY"])

out = client.embed(["query: hello", "passage: world"], model="your-embed-sku")
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

SDK batch on `XaiClient` (mocked helper in tests — never hits gRPC). `create_batch` / `add_batch_requests` submit a job; `get_batch` polls status; `list_batch_results` reads completions as JSON dicts (no protobuf). Requests are chat-shaped dicts (`model`, `messages`, knobs). Live Batch rejects `grok-4.6` and `grok-4.5`; omitted model and those SKUs remap to `grok-4.3` (`need=batch`). Unknown pins stay. Empty name / batch id / requests are rejected before the RPC.

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

Live create / get / list / delete / upload use xAI's management API. Set `XAI_MANAGEMENT_KEY` in the environment (the SDK reads it). Search uses the regular API key. This client does not take a second key argument. A collection id can 404 on search until it is visible/indexed on the inference side — the kit does not wait or retry.

```python
from xaikit import MockChatProvider, XaiClient

client = XaiClient(provider=MockChatProvider(), api_key="test-key")
# Live: XaiClient(api_key=os.environ["XAI_API_KEY"])  # plus XAI_MANAGEMENT_KEY in env

coll = client.create_collection("docs")
# coll["id"] / coll["name"]
listed = client.list_collections()
# listed["collections"]
got = client.get_collection(coll["id"])
client.upload_document(coll["id"], "note.txt", b"hello world")
hits = client.search_collections("hello", coll["id"])
# hits["matches"][0]["chunk_content"] / file_id / score
# client.delete_collection(coll["id"])
```

When a usage meter is attached, `purpose=` is required. Events use `modality="collections"`. The public pricing table has no collections rate, so the meter records purpose/success without inventing USD.

## Video generation

REST Imagine video on `XaiClient` (mocked HTTP in tests; live calls need `XAI_API_KEY`). `into=` is required — a `VideoInbox`, list, or callback the app keeps. The kit delivers `request_id` as soon as xAI accepts the job, then the terminal result. Do not rely on the return value alone: a sibling failure can cancel the await (`asyncio.gather` / `TaskGroup`) without voiding the receipt. `inbox.cancel(request_id)` is the only way to stop listening. Default `wait=True` polls until the clip is ready; `wait=False` returns `request_id` for `poll_video`.

```python
from xaikit import MockChatProvider, VideoInbox, XaiClient

client = XaiClient(provider=MockChatProvider(), api_key="test-key")
# Live: XaiClient(api_key=os.environ["XAI_API_KEY"])

inbox = VideoInbox()
started = client.generate_video(
    "A red cube rotating on a table",
    duration=8,
    aspect_ratio="16:9",
    resolution="480p",
    into=inbox,
    wait=False,
)
status = client.poll_video(started["request_id"])
# bytes = client.download_video(status["url"])  # when status == "done"
# status["error"] is set when status is failed / expired (same text wait raises)
# inbox.receipts still has the ticket if a parallel await is cancelled
```

`extend_video(prompt, video_url=..., into=inbox)` continues a clip. Generate defaults to `grok-imagine-video-1.5`; extend remaps that SKU to `grok-imagine-video` (1.5 cannot extend). `1080p` is kept on 1.5 for text-to-video and image-to-video; reference-to-video and older `grok-imagine-video` send `720p` instead.

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
    for _ in range(8):
        event = session.recv(timeout=30)
        pcm = decode_realtime_audio(event) if isinstance(event, dict) else None
        if pcm:
            break  # app owns playback; this library has no speaker
    # session.send_audio(pcm16_bytes)  # app owns capture; this library has no mic
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

REST unary synthesis stays on `synthesize_speech`. Optional knobs match the streaming set (`codec`, `sample_rate`, `bit_rate`, `speed`, `optimize_streaming_latency`, `text_normalization`, `with_timestamps`, `replace`) and nest `codec` / `sample_rate` / `bit_rate` as `output_format` on the wire. Text over 15,000 characters is rejected before HTTP. `with_timestamps=True` returns a JSON envelope (`application/json`) instead of raw audio bytes.

```python
audio, content_type = client.synthesize_speech(
    "Hello from REST TTS.",
    voice_id="eve",
    codec="wav",
    sample_rate=24000,
    speed=1.0,
)
```

Offline tests mock the socket.

List built-in TTS voices (not team-scoped custom clones):

```python
voices = client.list_tts_voices()
# voices[0]["voice_id"] / ["name"] / ["language"]
# client.get_tts_voice("eve")
```

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

## Priority processing and deferred chat

Optional `service_tier="priority"` (or `"default"`) on `chat` / `chat_stream` / `chat_json` and `create_response`. Omit the knob for default. Invalid values are rejected before the network.

Deferred completions are a separate REST pair — not a second return type on `chat`:

```python
from xaikit import MockChatProvider, XaiClient

client = XaiClient(provider=MockChatProvider(), api_key="test-key")
# Live: XaiClient(api_key=os.environ["XAI_API_KEY"])

ticket = client.create_deferred_chat([{"role": "user", "content": "126/3=?"}])
# ticket["request_id"]
# result = client.get_deferred_chat(ticket["request_id"])
# result["status"] is "pending" (HTTP 202) or "complete" (HTTP 200 + completion fields)
```

Create and pending get meter `modality="chat"` without tokens. A complete get may record `usage` tokens. No invented USD.

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
