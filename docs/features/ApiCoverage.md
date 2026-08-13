# ApiCoverage

**Last Updated**: 2026-08-13  
**Related TODO**: [ApiCoverage-TODO.md](ApiCoverage-TODO.md)

## Overview

Target contract for **the rest of XaiKit** — every xAI surface this kit will wrap that is not already a Document Map row. Video and realtime voice have their own stems; this file is the **finished-kit spec** for everything else, not a parking lot of maybe-laters.

XaiKit’s product is one library: typed `XaiClient` (plus catalog / meter / credentials), mock-testable, purpose-tagged usage, no UI, no multi-provider SDK. Remaining surfaces attach to that client. They do **not** get a second architecture when someone picks them up.

Implement order after video: **realtime voice**, then **no order**. Split a surface into its own map row only when implementation starts if the stem would otherwise bloat — the contract below still applies.

## Target kit

| Surface | Home when built | In tree today |
|---------|-----------------|---------------|
| Chat complete / stream | [ClientChat](ClientChat.md) | Yes |
| Tools / function calling | [ClientChat](ClientChat.md) — same `chat` / `chat_stream` | No |
| Vision / multimodal parts | [ClientChat](ClientChat.md) — message parts, not a second API | No |
| Native structured outputs | [ClientChat](ClientChat.md) — `chat_json` grows to schema/SDK | Partial (`chat_json` fences) |
| Catalog resolve | [Catalog](Catalog.md) — `cheapest` / `economy` / `best` per **role** | Yes |
| Image generate | [MediaRest](MediaRest.md) | Yes |
| Image edit / i2i | [MediaRest](MediaRest.md) — `edit_image` beside generate | No |
| STT / TTS (REST) | [MediaRest](MediaRest.md) | Yes |
| Streaming STT (non-STS) | [MediaRest](MediaRest.md) | No |
| Video | [VideoGeneration](VideoGeneration.md) | No |
| Realtime voice / STS | [RealtimeVoice](RealtimeVoice.md) | Yes |
| Files upload / `file_id` | `XaiClient` files helpers (this spec until a map row) | No |
| Embeddings | `XaiClient` (this spec) | No |
| Tokenizer | `XaiClient` or `xaikit` helper (this spec) | No |
| Batch | `XaiClient` (this spec) | No |
| Collections / documents | `XaiClient` (this spec) | No |
| Responses / built-in agent tools | Additive wrap — **do not replace** `chat` | No |
| Async twin | Optional parallel API (`aio`) — **not** a rewrite of sync | No |
| Service tier / deferred | Pass-through knob when a method already exists | No |
| Auth subclient / User types | Out of kit — [ConnectAuth](ConnectAuth.md) stays stores + OAuth helpers | N/A |

## Architecture / Contract

- **Owns**: target shape for unsplit surfaces; inventory vs `xai_sdk` + xAI docs; ranking
- **Does not own**: shipped chat/media/catalog/connect behavior (those specs); video; realtime voice
- **Public API (target)**: methods on `XaiClient` or a thin submodule imported from `xaikit`. Same `api_key` / `CredentialStore` / `UsageMeter` / mock-or-httpx-contract tests

### Shared rules *(every new method)*

- Wrap upstream (`xai_sdk` or documented REST/WS). Do not invent a parallel protocol.
- Empty-input guards before the network.
- Purpose required when a meter is attached; success and failure usage; modality tag per surface.
- Failures → `RuntimeError` (or documented typed error); meter/trace must not swallow the user-facing error.
- Offline contract tests (mocked HTTP/SDK/WS). Optional live: `XAITKIT_LIVE=1` + `XAI_API_KEY`.
- No UI. No private app names in examples.

### Catalog roles

Same three intents, applied to a **role-filtered** pool (`chat` \| `image` \| `video` \| `voice`). One price band → all three pick flagship. Coding SKUs stay out of general **chat** unless the catalog is coding-only. Image/video/voice pools do not use the chat coding skip. See [Catalog](Catalog.md).

### Files *(target — unblocks `file_id`)*

- `upload_file(data, filename, *, purpose=…, content_type=…)` → `{id, filename, …}` via `POST /v1/files`.
- Optional get/delete if upstream has them.
- Video and image **accept** `url` **or** `file_id`. Text-to-video / text-to-image must not wait on Files. I2V/edit may take URL first, `file_id` when Files exists.
- Imagine `storage_options` / `file_output.file_id` on generate/edit is in-scope for MediaRest/Video when wrapping those response fields.

### Chat extras *(target — live on ClientChat)*

- **Tools**: pass tool defs into `chat` / `chat_stream`; return tool calls on `CompletionResponse`; accept tool-result messages on the next turn. App owns the tool loop.
- **Vision**: message content is not only `str` — image (and later video) parts (`url` / `file_id` / data). `MockChatProvider` records parts.
- **Structured outputs**: `chat_json` uses xAI schema / `response_format` when we wrap it; fence-stripping stays fallback until then.
- **Responses API / built-in tools** (web, X, code, collections, image-in-chat): additive. Do **not** migrate the paved path off `chat`.

### Media extras *(target — live on MediaRest)*

- **Image edit**: `POST /v1/images/edits` (or SDK `image.sample` with `image_file_id` / URL). Knobs: model, prompt, source image, `n`, aspect/response_format as upstream allows. Same return shape as `generate_image` plus `file_id` when present.
- **Streaming STT**: only if it is still “transcribe a stream,” not speech-to-speech (that is RealtimeVoice).

### Other `XaiClient` surfaces *(target — this spec)*

- **Embeddings**: `embed(texts, *, model=…, purpose=…)` → vectors; catalog role or explicit model pin.
- **Tokenizer**: count/encode helper if we wrap the tokenizer API; used by meter estimates, not a UI.
- **Batch**: submit + poll/results; same chat/media payloads where upstream allows; purpose-when-metered on the job.
- **Collections / documents**: upload/query if we wrap that API; not a RAG product.

### Out of kit

- Product login, User/Session, billing dashboards, multi-provider routing, playground UI.
- Replacing sync `XaiClient` with async-only.

## Behavior (stable)

- Prefer SDK when it already models the surface; REST/httpx when that is what shipped media uses and the SDK is thin.
- `file_id` is an opaque string from Files or Imagine `file_output`; do not parse it.
- Built-in agent tools stay opt-in knobs, never default-on for `chat`.
- Async, if added, mirrors sync method names on an async client — no split feature set.

## Decisions

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-08-12 | Video first, then ranked remainder | User request |
| 2026-08-12 | After video: realtime voice; rest unordered | User confirm |
| 2026-08-12 | Target homes: tools/vision/schema → ClientChat; image edit/streaming STT → MediaRest; Files/embed/tokenizer/batch/collections → XaiClient | Final kit is one client, not N SDKs |
| 2026-08-12 | Chat stays the paved text path; Responses/built-in tools are additive | Do not rewrite `chat` as an interim |
| 2026-08-12 | Files is not a gate for T2V / T2I | URL/data-URL first; `file_id` when Files exists |
| 2026-08-12 | Catalog intents per role, same cheapest/economy/best rules | Image/voice/video lineups stay thin; overlap already specified |
| 2026-08-12 | Split a map row at implement time, not for every inventory line | User: no empty spec/TODO pile; contract lives here |

## Dependencies

| Piece | Relationship |
|-------|--------------|
| [VideoGeneration.md](VideoGeneration.md) | Implement first; may take `file_id` later |
| [RealtimeVoice.md](RealtimeVoice.md) | Implement after video |
| [ClientChat.md](ClientChat.md) | Tools, vision, structured outputs |
| [MediaRest.md](MediaRest.md) | Image edit, streaming STT |
| [Catalog.md](Catalog.md) | Role-filtered resolve |
| [UsageObservability.md](UsageObservability.md) | Modalities for new surfaces |
| [ConnectAuth.md](ConnectAuth.md) | Credentials |

## Acceptance

- [x] Human ranking recorded (Human-TODO)
- [x] Winner split: [RealtimeVoice](RealtimeVoice.md)
- [x] Target homes + shared rules recorded (this spec)
- [ ] Each **implemented** slice matches its home spec (or a new map row created the same turn)
- [ ] No silent “wrap the entire SDK” in one change

## Current status

- **In progress**: target spec locked; code remainder unordered after video + realtime voice
- **Blocked by**: —
