# ApiCoverage

**Last Updated**: 2026-08-13 *(async client twin)*  
**Related TODO**: [ApiCoverage-TODO.md](ApiCoverage-TODO.md)

## Overview

Target contract for **the rest of xAIkit** — every xAI surface this kit will wrap that is not already a Document Map row. Video and realtime voice have their own stems; this file is the **finished-kit spec** for everything else, not a parking lot of maybe-laters.

xAIkit’s product is one library: typed `XaiClient` (plus catalog / meter / credentials), mock-testable, purpose-tagged usage, no UI, no multi-provider SDK. Remaining surfaces attach to that client. They do **not** get a second architecture when someone picks them up.

Implement order after video: **realtime voice**, then **no order**. Split a surface into its own map row only when implementation starts if the stem would otherwise bloat — the contract below still applies.

## Target kit

| Surface | Home when built | In tree today |
|---------|-----------------|---------------|
| Chat complete / stream | [ClientChat](ClientChat.md) | Yes |
| Tools / function calling | [ClientChat](ClientChat.md) — same `chat` / `chat_stream` | Yes |
| Vision / multimodal parts | [ClientChat](ClientChat.md) — message parts, not a second API | Yes |
| Native structured outputs | [ClientChat](ClientChat.md) — `chat_json` grows to schema/SDK | Yes |
| Catalog resolve | [Catalog](Catalog.md) — `cheapest` / `economy` / `best` per **role** | Yes |
| Image generate | [MediaRest](MediaRest.md) | Yes |
| Image edit / i2i | [MediaRest](MediaRest.md) — `edit_image` beside generate | Yes |
| STT / TTS (REST) | [MediaRest](MediaRest.md) | Yes |
| Streaming STT (non-STS) | [MediaRest](MediaRest.md) | Yes |
| Streaming TTS (non-STS) | [MediaRest](MediaRest.md) | Yes |
| Video | [VideoGeneration](VideoGeneration.md) | No |
| Realtime voice / STS | [RealtimeVoice](RealtimeVoice.md) | Yes |
| Files upload / `file_id` | `XaiClient` files helpers (this spec until a map row) | Yes |
| Embeddings | `XaiClient` (this spec) | Yes |
| Tokenizer | `XaiClient` or `xaikit` helper (this spec) | Yes |
| Batch | `XaiClient` (this spec) | Yes |
| Collections / documents | `XaiClient` (this spec) | Yes |
| Responses / built-in agent tools | Additive wrap — **do not replace** `chat` | Yes |
| Async twin | Optional parallel API (`aio`) — **not** a rewrite of sync | Yes |
| Service tier / deferred | Pass-through knob when a method already exists | Yes |
| Auth subclient / User types | Out of kit — [ConnectAuth](ConnectAuth.md) stays stores + OAuth helpers | N/A |

## Architecture / Contract

- **Owns**: target shape for unsplit surfaces; inventory vs `xai_sdk` + xAI docs; ranking
- **Does not own**: shipped chat/media/catalog/connect behavior (those specs); video; realtime voice
- **Public API (target)**: methods on `XaiClient` / `AsyncXaiClient` or a thin submodule imported from `xaikit`. Same `api_key` / `CredentialStore` / `UsageMeter` / mock-or-httpx-contract tests

### Shared rules *(every new method)*

- Wrap upstream (`xai_sdk` or documented REST/WS). Do not invent a parallel protocol.
- Empty-input guards before the network.
- Purpose required when a meter is attached; success and failure usage; modality tag per surface.
- Failures → `RuntimeError` (or documented typed error); meter/trace must not swallow the user-facing error.
- Offline contract tests (mocked HTTP/SDK/WS). Optional live: `XAITKIT_LIVE=1` + `XAI_API_KEY`.
- No UI. No private app names in examples.

### Catalog roles

Same three intents, applied to a **role-filtered** pool (`chat` \| `image` \| `video` \| `voice`). One price band → all three pick flagship. Coding SKUs stay out of general **chat** unless the catalog is coding-only. Image/video/voice pools do not use the chat coding skip. See [Catalog](Catalog.md).

### Files *(on `XaiClient` — unblocks `file_id`)*

- `upload_file(data, filename, *, purpose=…, content_type=…, file_purpose="assistants", expires_after=…)` → `{id, filename, bytes, created_at, …}` via `POST https://api.x.ai/v1/files` multipart (`file` + upstream `purpose` + optional `expires_after` before `file`). Constant `XAI_FILES_URL`.
- Kit `purpose=` is the usage-meter tag (required when a meter is attached). `file_purpose=` is the multipart field (default `"assistants"`). Response `purpose` echoes the multipart value, not the meter tag.
- `get_file(file_id, *, purpose=…)` / `delete_file(file_id, *, purpose=…)` → `GET`/`DELETE /v1/files/{file_id}`.
- Empty `data` / `filename` / `file_id` and uploads over 50 MB are rejected before HTTP. Failures → `RuntimeError`. Meter success and failure with `modality="files"`.
- Video and image **accept** `url` **or** `file_id`. Text-to-video / text-to-image must not wait on Files. I2V/edit may take URL first, `file_id` when Files exists.
- Imagine `storage_options` / `file_output.file_id` on generate/edit is in-scope for MediaRest/Video when wrapping those response fields.
- Chat-with-files / vision attachments stay on [ClientChat](ClientChat.md) — not this slice.

### Chat extras *(live on ClientChat)*

- **Tools**: pass tool defs into `chat` / `chat_stream`; return tool calls on `CompletionResponse`; accept tool-result messages on the next turn. App owns the tool loop.
- **Vision**: message content is not only `str` — image (and later video) parts (`url` / `file_id` / data). `MockChatProvider` records parts.
- **Structured outputs**: `chat_json` uses xAI schema / `response_format`; fence-stripping stays fallback.
- **Responses API / built-in tools** (web, X, code, collections, image-in-chat): additive. Do **not** migrate the paved path off `chat`.
- **Service tier**: optional `service_tier=` (`"default"` | `"priority"`) on `chat` / `chat_stream` / `chat_json` and `create_response`. Omit when `None` (same as `"default"`). Invalid values are rejected before the network. Live chat forwards to SDK `chat.create(service_tier=)`. `CompletionResponse.service_tier` echoes the provider/API value when present; Responses JSON is returned as-is.
- **Deferred chat**: `create_deferred_chat(messages, …)` POST `https://api.x.ai/v1/chat/completions` with `deferred: true` → `{request_id}`. `get_deferred_chat(request_id)` GET `{XAI_DEFERRED_CHAT_URL}/{request_id}` (`https://api.x.ai/v1/chat/deferred-completion`). 200 → `{status: "complete", …completion JSON}`; 202 → `{status: "pending"}` (poll without an exception). Result available once within 24h. SDK has no `deferred=` on `chat.create` and no getter — REST via httpx. Empty messages / empty `request_id` rejected before HTTP. Failures → `RuntimeError`. Purpose required when metered; `modality="chat"`. Create and get-pending (202) meter purpose/success without tokens; 200 may record tokens from `usage`. No invented USD. 401 skips the meter.

### Media extras *(target — live on MediaRest)*

- **Image edit**: `POST /v1/images/edits` JSON (not multipart) on [MediaRest](MediaRest.md). Knobs: model, prompt, source image, `n`, aspect/response_format as upstream allows. Same return shape as `generate_image` plus `file_id` when present.
- **Streaming STT**: unary-transcribe over `wss://api.x.ai/v1/stt` on [MediaRest](MediaRest.md) (`open_stt_session` / `SttSession`). Not speech-to-speech (that is [RealtimeVoice](RealtimeVoice.md)).
- **Streaming TTS**: bidirectional TTS over `wss://api.x.ai/v1/tts` on [MediaRest](MediaRest.md) (`open_tts_session` / `TtsSession`). Not STS (`/v1/realtime`). REST `synthesize_speech` stays.

### Other `XaiClient` surfaces *(target — this spec)*

- **Embeddings**: `embed(texts: str | list[str], *, model=…, purpose=…, parent_id=…, labels=…)` → REST envelope `{object, model, data, usage}` where `data` is `[{index, embedding}, …]`. Constant `XAI_EMBEDDINGS_URL` (`POST https://api.x.ai/v1/embeddings`). Wrap documented REST via httpx (`xai_sdk` has no embeddings module). `model=` is required — no kit default. OpenAPI `v1` is an example and may 404; some teams have an empty `GET /v1/embedding-models` roster. Collections index models are not this endpoint. Empty string / empty list / blank items / lists over 128 are rejected before HTTP. Failures → `RuntimeError`. Meter success and failure with `modality="embed"` (tokens from response `usage`, no invented USD). Pin `model=`; do not add catalog `role=embed` (Catalog roles stay `chat` \| `image` \| `video` \| `voice`).
- **Tokenizer**: `tokenize(text, *, model=…, purpose=…, parent_id=…, labels=…)` → `{tokens, count, model}` where `tokens` is `[{token_id, string, token_bytes}, …]` (JSON dicts, no protobuf). Constant `XAI_TOKENIZE_URL` (`POST https://api.x.ai/v1/tokenize-text`). Wrap documented REST via httpx. `model=` defaults to the client's chat `self.model`. Empty/blank text is rejected before HTTP. Failures → `RuntimeError`. Meter success and failure with `modality="tokenize"` (count from the token list, no invented USD). Works with `provider=` mocks (no live SDK required).
- **Batch**: submit + poll/results on `XaiClient` via `xai_sdk.Client.batch` (not invented REST). Public methods return JSON dicts (no `batch_pb2`). `create_batch(name, *, input_file_id=…, purpose=…)` → `{id, name, …}`. `add_batch_requests(batch_id, requests, *, purpose=…)` takes chat-shaped dicts (`model`, `messages`, knobs). Live Batch rejects `grok-4.6` / `grok-4.5`; omitted model and those known SKUs remap via `need=batch` to `grok-4.3`. Unknown pins stay. `get_batch` / `cancel_batch` / `list_batches` / `list_batch_results` wrap the matching SDK methods. Empty name / batch id / requests are rejected before RPC. Failures → `RuntimeError`. Purpose required when metered; meter success and failure with `modality="batch"` (no invented USD). Offline tests monkeypatch `call_batch_rpc` (like realtime WS). Works with `provider=` mocks when the helper is patched.
- **Collections / documents**: upload/query on `XaiClient` via `xai_sdk.Client.collections` (not a RAG product, not invented REST). Public methods return JSON dicts (no collections/documents protobufs). Honest wrap: `create_collection(name, *, model_name=…, chunk_configuration=…, description=…, purpose=…)` → `{id, name, …}`; `get_collection` / `list_collections` / `delete_collection`; `upload_document(collection_id, name, data, *, fields=…, purpose=…)`; `search_collections(query, collection_ids, *, limit=…, purpose=…)` → `{matches}` (`collection_ids` is a string or list). Empty name / collection id / query / file bytes are rejected before RPC. Failures → `RuntimeError`. Purpose required when metered; meter success and failure with `modality="collections"` (no invented USD). Offline tests monkeypatch `call_collections_rpc`. Create/get/list/delete/upload use the management channel — `XaiClient` passes `XAI_MANAGEMENT_KEY` from the environment into `xai_sdk.Client` (no second kit auth param). Search uses the regular API key. A new collection id can 404 on search until it is visible/indexed on the inference side — the kit does not wait or retry.
- **Responses / built-in agent tools**: additive REST wrap — **do not replace** `chat` / `chat_stream`. `create_response(input, *, model=…, tools=…, purpose=…)` → REST JSON dict via `POST https://api.x.ai/v1/responses`. Constant `XAI_RESPONSES_URL`. Optional `get_response(response_id, *, purpose=…)` → `GET /v1/responses/{response_id}`. `input` is a string or list (OpenAPI `ModelInput`). `model=` defaults to the client's chat model. Built-in tools (`web_search`, `x_search`, `code_interpreter`, `file_search`, `image_generation`, plus pass-through of other documented `ModelTool` types) are **opt-in** — omitted from the body unless `tools=` is passed; never default-on. Empty input / blank string / empty list / empty response id / more than 128 tools are rejected before HTTP. Failures → `RuntimeError`. Purpose required when metered; meter success and failure with `modality="responses"`. `create_response` records tokens from `usage` `input_tokens`/`output_tokens`; `get_response` meters purpose/success only (does not re-count stored generation tokens). No invented USD. Works with `provider=` mocks (httpx is patched in tests).

### Out of kit

- Product login, User/Session, billing dashboards, multi-provider routing, playground UI.
- Replacing sync `XaiClient` with async-only.

## Behavior (stable)

- Prefer SDK when it already models the surface; REST/httpx when that is what shipped media uses and the SDK is thin.
- `file_id` is an opaque string from Files or Imagine `file_output`; do not parse it.
- Built-in agent tools stay opt-in knobs, never default-on for `chat`.
- Async, if added, mirrors sync method names on an async client — no split feature set. `AsyncXaiClient` is that twin: same public method names, all awaitable; REST via `httpx.AsyncClient`; WS via `connect_*_websocket_async`; live chat via `xai_sdk.AsyncClient`. Not `asyncio.to_thread` around sync I/O.

## Decisions

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-08-12 | Video first, then ranked remainder | User request |
| 2026-08-12 | After video: realtime voice; rest unordered | User confirm |
| 2026-08-12 | Target homes: tools/vision/schema → ClientChat; image edit/streaming STT → MediaRest; Files/embed/tokenizer/batch/collections → XaiClient | Final kit is one client, not N SDKs |
| 2026-08-13 | Streaming TTS (non-STS) → MediaRest | Same home as streaming STT: `/v1/tts` ≠ `/v1/realtime`. `open_tts_session` / `TtsSession`, not `RealtimeSession` |
| 2026-08-12 | Chat stays the paved text path; Responses/built-in tools are additive | Do not rewrite `chat` as an interim |
| 2026-08-12 | Files is not a gate for T2V / T2I | URL/data-URL first; `file_id` when Files exists |
| 2026-08-12 | Catalog intents per role, same cheapest/economy/best rules | Image/voice/video lineups stay thin; overlap already specified |
| 2026-08-12 | Split a map row at implement time, not for every inventory line | User: no empty spec/TODO pile; contract lives here |
| 2026-08-13 | Files: kit `purpose=` is the meter tag; `file_purpose=` (default `"assistants"`) is the REST multipart field | xAI Files also names a multipart field `purpose` (OpenAI compat). Do not collide with UsageMeter |
| 2026-08-13 | Embeddings: REST envelope `{object, model, data, usage}`; require `model=` | Official OpenAPI `POST /v1/embeddings` (https://api.x.ai/api-docs/openapi.json). Example model id is `v1`, not a grok-embedding-* default. Return the documented envelope so callers get vectors and usage. |
| 2026-08-13 | Embeddings: httpx REST, not gRPC; no catalog `role=embed` | `xai_sdk` ships embed protos but no Python module. Catalog roles are chat/image/video/voice only — pin `model=` |
| 2026-08-13 | Tokenizer: `{tokens, count, model}`; httpx REST; default model is client chat model | Official OpenAPI `POST /v1/tokenize-text`. Map `string_token` → `string` so callers never import protos. SDK also has `tokenize.tokenize_text`; REST matches embed/files mock-HTTP tests. |
| 2026-08-13 | Batch: JSON dicts on `XaiClient`; wrap `xai_sdk` batch via `call_batch_rpc`; `modality="batch"`; no USD | SDK already models create/add/get/list/cancel/list_results. Callers must not import `batch_pb2`. Public table has no batch rate — meter purpose/success only. |
| 2026-08-16 | Batch contracts 4.6/4.5 → `grok-4.3` via `need=batch` | Live Batch rejects flagship chat SKUs. Same extras map as video extend. Official examples use 4.3. Unknown pins stay. |
| 2026-08-16 | Embed `v1` is not a live pin | Tester: empty `GET /v1/embedding-models`; `v1` and `grok-embedding-small` 404. Wiring stays `model=` required. |
| 2026-08-13 | Collections: JSON dicts on `XaiClient`; wrap SDK via `call_collections_rpc`; `modality="collections"`; no USD; not a RAG product | SDK already models create/get/list/delete/upload_document/search. Callers must not import collections protobufs. Management key stays SDK `XAI_MANAGEMENT_KEY` env pass-through — no second kit auth. Public table has no collections rate. |
| 2026-08-13 | Responses: httpx REST `create_response` / `get_response`; `modality="responses"`; tools opt-in never default-on; do not replace `chat` | Official OpenAPI `POST /v1/responses` + `GET /v1/responses/{response_id}`. Built-in tools stay caller-supplied. Distinct modality so chat metering stays separate. Public table has no Responses/tools rate — no invented USD. `get_response` does not re-count stored generation tokens (same as `get_file` / `get_batch`). |
| 2026-08-13 | Service tier: pass-through `"default"` \| `"priority"` on chat + Responses; omit when None; never invent other values | Official docs https://docs.x.ai/developers/advanced-api-usage/priority-processing. SDK `chat.create(service_tier=)` already models the knob. |
| 2026-08-13 | Deferred chat: separate `create_deferred_chat` / `get_deferred_chat` REST helpers; 202 → `{status: "pending"}`; `modality="chat"`; no USD | SDK has no `deferred=` on create. REST matches files/responses. Do not overload `chat` → `CompletionResponse`. 202 is pollable, not an exception. |
| 2026-08-13 | `AsyncXaiClient` same-name twin of the full sync surface (chat + REST + WS + SDK RPC) | No split feature set. Kit httpx paths use `httpx.AsyncClient`; kit WS uses async connect helpers; live chat uses `xai_sdk.AsyncClient`. |

## Dependencies

| Piece | Relationship |
|-------|--------------|
| [VideoGeneration.md](VideoGeneration.md) | Implement first; may take `file_id` later |
| [RealtimeVoice.md](RealtimeVoice.md) | Implement after video |
| [ClientChat.md](ClientChat.md) | Tools, vision, structured outputs |
| [MediaRest.md](MediaRest.md) | Image edit, streaming STT, streaming TTS |
| [Catalog.md](Catalog.md) | Role-filtered resolve |
| [UsageObservability.md](UsageObservability.md) | Modalities for new surfaces |
| [ConnectAuth.md](ConnectAuth.md) | Credentials |

## Acceptance

- [x] Human ranking recorded (Human-TODO)
- [x] Winner split: [RealtimeVoice](RealtimeVoice.md)
- [x] Target homes + shared rules recorded (this spec)
- [x] Async twin `AsyncXaiClient` (same method names; no split feature set)
- [ ] Each **implemented** slice matches its home spec (or a new map row created the same turn)
- [ ] No silent “wrap the entire SDK” in one change

## Current status

- **In progress**: remainder unordered after video + realtime voice + ClientChat extras + Files + embeddings + tokenizer + batch + collections + Responses + service tier / deferred + async twin
- **Blocked by**: —
