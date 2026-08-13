# ClientChat

**Last Updated**: 2026-08-13 *(async client twin)*  
**Related TODO**: [ClientChat-TODO.md](ClientChat-TODO.md)

## Overview

Typed chat transport: `XaiClient.chat`, `chat_json`, and `chat_stream`, plus the async twin `AsyncXaiClient` with the same method names. Live path uses `SdkChatProvider` over `xai_sdk.Client` (sync) or `AsyncSdkChatProvider` over `xai_sdk.AsyncClient` (async); tests inject `MockChatProvider` (sync `complete`/`stream` plus `async_complete`/`async_stream`). Domain schemas stay in consuming apps.

The same methods accept tool defs, multimodal content parts, and native structured outputs on `chat_json`. Do not add a second chat client or replace `chat` with the Responses API.

## Architecture / Contract

- **Owns**: message list → completion/stream; knob forwarding; retry on open; optional usage/trace hooks; tool defs + tool-result turns; image/video message parts; schema structured outputs on `chat_json`; `service_tier`; deferred chat create/get helpers
- **Does not own**: product prompts, the app’s tool *loop* (kit never executes tools), UI, media REST (see [MediaRest](MediaRest.md)), Responses-as-default / built-in agent tools
- **Public API**: `XaiClient`, `AsyncXaiClient`, `ChatProvider`, `AsyncChatProvider`, `MockChatProvider`, `SdkChatProvider`, `AsyncSdkChatProvider`, `CompletionResponse`, `StreamChunk`

Knobs forwarded to the provider: `model`, `temperature`, `max_tokens`, `thought_level`, `system_prompt`, `tools` / `tool_choice` / `parallel_tool_calls`, multimodal `content` parts, `chat_json` `schema` / `response_format`, `service_tier` (`"default"` | `"priority"`; omit when `None`). `effort` is an alias for `thought_level`. `thought_level` maps to xAI `reasoning_effort` (`low` \| `high`; `med`/`medium`/`mid` → `low`).

Deferred chat is a separate REST pair (`create_deferred_chat` / `get_deferred_chat`) — not an overload of `chat` → `CompletionResponse`. Constant `XAI_DEFERRED_CHAT_URL`.

When a `UsageMeter` is attached, `purpose` is required. Without a meter, purpose is optional.

## Behavior (stable)

- `chat` records usage/trace on success and failure; wraps provider errors as `RuntimeError`.
- `chat_json` forces a JSON-only system prompt (overridable), default temperature `0.3`, parses object JSON (strips fences); non-object JSON fails. When `schema=` or `response_format=` is set, that knob is passed through to xAI `response_format`; fence-stripping remains the fallback if the model still returns fenced JSON.
- `chat_stream` retries only **opening** the iterator; mid-stream failures are not retried; usage recorded once when the stream completes (not on `GeneratorExit`).
- Client default `thought_level` applies unless the call passes `thought_level` or `effort`.
- Missing credentials without a mock provider raises (pass `api_key`, `CredentialStore`, or `provider=`).
- `chat` / `chat_stream` accept tool definitions (`name`, `description`, `parameters` JSON Schema) and optional `tool_choice` (`"auto"` \| `"none"` \| `"required"` \| `{"name": "..."}`) and `parallel_tool_calls`. Responses expose `tool_calls` as `[{id, name, arguments}]` with **parsed JSON arguments** (typically a dict; invalid JSON stays a string; missing/blank arguments stay `""` so incomplete stream deltas are not `{}`). The app runs tools and sends `role="tool"` results (`content`, `tool_call_id`) plus the assistant turn’s `tool_calls` on the next request.
- Stream: tool-call deltas are on `StreamChunk.tool_call_delta` when the SDK yields them; `tool_calls` on a chunk is the accumulation so far (last chunk has the full list).
- Message `content` may be `str` or a list of parts: `{"type": "text", "text": "..."}`, `{"type": "image_url", "url": "..."}` (also `image_url` key / data URI / OpenAI nested `{url, detail}`), `{"type": "file", "file_id": "..."}` (or `url` / inline `data`). Optional `video_url` parts map to SDK file content. `MockChatProvider` records parts as given.
- `MockChatProvider` records `tools`, `tool_choice`, `parallel_tool_calls`, `response_format`, `service_tier`, and message parts on `calls`. A scripted dict with a `tool_calls` key is a structured reply (not JSON content); any other dict is JSON-encoded as content.
- `service_tier` is `"default"` | `"priority"` (case-insensitive). Invalid values raise `ValueError` before the network. Omit from SDK/HTTP when `None`. Live chat forwards to `xai_sdk` `chat.create(service_tier=)`. `CompletionResponse.service_tier` echoes the provider value when present.
- `create_deferred_chat(messages, …)` POST `/v1/chat/completions` with `deferred: true` → `{request_id}`. `get_deferred_chat(request_id)` GET `/v1/chat/deferred-completion/{id}`: 200 → `{status: "complete", …}`; 202 → `{status: "pending"}`. Empty messages / empty id rejected before HTTP. Meter `modality="chat"`; 202 and create have no tokens; 200 may record `usage` tokens; no invented USD; 401 skips the meter.

## Decisions

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-08-12 | Library-only prove-out via mock + tests | Wiring, not UX; no playground UI |
| 2026-08-12 | `effort` aliases `thought_level` | Product wording vs xAI `reasoning_effort` |
| 2026-08-12 | Tools, vision, structured outputs stay on this client | Final kit — not a second chat stack ([ApiCoverage](ApiCoverage.md)) |
| 2026-08-13 | Tool `arguments` are parsed JSON (dict when the model returns an object); invalid JSON stays a string; blank/missing stay `""` | JSON-dict public API; callers should not import `xai_sdk.chat` protos; stream deltas must not look like a finished `{}` call |
| 2026-08-13 | `chat_json(schema=)` aliases `response_format=`; `schema=` wins if both are set | Convenience for JSON Schema / pydantic; still one provider knob |
| 2026-08-13 | Mock dict replies with a `tool_calls` key are structured (not `json.dumps`’d) | Lets tests script tool calls without breaking existing `chat_json` dict replies |
| 2026-08-13 | Deferred chat is `create_deferred_chat` + `get_deferred_chat`, not a `chat(..., deferred=True)` return-type fork | `CompletionResponse` would lie for `{request_id}`; matches files/responses helpers. SDK has no `deferred=` on create. |
| 2026-08-13 | `AsyncXaiClient` is a same-name async twin (not chat-only; REST/WS included) | ApiCoverage: no split feature set. Real `httpx.AsyncClient` / async websockets / `xai_sdk.AsyncClient` — not `asyncio.to_thread` around sync I/O. |

## Dependencies

| Piece | Relationship |
|-------|--------------|
| [Catalog.md](Catalog.md) | Model pin / resolve when `model=` omitted |
| [UsageObservability.md](UsageObservability.md) | Optional meter + tracer |
| [ConnectAuth.md](ConnectAuth.md) | Credential store / API key |

## Acceptance *(library stem)*

- [x] `chat` / `chat_json` / `chat_stream` exist and return typed results
- [x] Knobs reach `MockChatProvider.calls` (temperature, max_tokens, system, thought_level/effort)
- [x] Purpose required iff meter attached
- [x] SDK kwargs map `thought_level` → `reasoning_effort`
- [x] Tools / function calling on `chat` / `chat_stream` (app owns the loop)
- [x] Multimodal message parts
- [x] Native structured outputs on `chat_json`
- [x] `service_tier` on `chat` / `chat_stream` / `chat_json` (`default` \| `priority`)
- [x] Deferred chat helpers (`create_deferred_chat` / `get_deferred_chat`)
- [x] Async twin `AsyncXaiClient` with the same chat method names (`chat` / `chat_json` / `chat_stream`)

## Current status

- **In progress**: none on chat path (async twin shipped)
- **Last reconciled with code**: 2026-08-13
