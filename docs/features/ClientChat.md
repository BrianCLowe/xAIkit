# ClientChat

**Last Updated**: 2026-08-13  
**Related TODO**: [ClientChat-TODO.md](ClientChat-TODO.md)

## Overview

Typed chat transport: `XaiClient.chat`, `chat_json`, and `chat_stream`. Live path uses `SdkChatProvider` over `xai_sdk.Client`; tests inject `MockChatProvider`. Domain schemas stay in consuming apps.

The same methods accept tool defs, multimodal content parts, and native structured outputs on `chat_json`. Do not add a second chat client or replace `chat` with the Responses API.

## Architecture / Contract

- **Owns**: message list → completion/stream; knob forwarding; retry on open; optional usage/trace hooks; tool defs + tool-result turns; image/video message parts; schema structured outputs on `chat_json`
- **Does not own**: product prompts, the app’s tool *loop* (kit never executes tools), UI, media REST (see [MediaRest](MediaRest.md)), Responses-as-default / built-in agent tools
- **Public API**: `XaiClient`, `ChatProvider`, `MockChatProvider`, `SdkChatProvider`, `CompletionResponse`, `StreamChunk`

Knobs forwarded to the provider: `model`, `temperature`, `max_tokens`, `thought_level`, `system_prompt`, `tools` / `tool_choice` / `parallel_tool_calls`, multimodal `content` parts, `chat_json` `schema` / `response_format`. `effort` is an alias for `thought_level`. `thought_level` maps to xAI `reasoning_effort` (`low` \| `high`; `med`/`medium`/`mid` → `low`).

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
- `MockChatProvider` records `tools`, `tool_choice`, `parallel_tool_calls`, `response_format`, and message parts on `calls`. A scripted dict with a `tool_calls` key is a structured reply (not JSON content); any other dict is JSON-encoded as content.

## Decisions

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-08-12 | Library-only prove-out via mock + tests | Wiring, not UX; no playground UI |
| 2026-08-12 | `effort` aliases `thought_level` | Product wording vs xAI `reasoning_effort` |
| 2026-08-12 | Tools, vision, structured outputs stay on this client | Final kit — not a second chat stack ([ApiCoverage](ApiCoverage.md)) |
| 2026-08-13 | Tool `arguments` are parsed JSON (dict when the model returns an object); invalid JSON stays a string; blank/missing stay `""` | JSON-dict public API; callers should not import `xai_sdk.chat` protos; stream deltas must not look like a finished `{}` call |
| 2026-08-13 | `chat_json(schema=)` aliases `response_format=`; `schema=` wins if both are set | Convenience for JSON Schema / pydantic; still one provider knob |
| 2026-08-13 | Mock dict replies with a `tool_calls` key are structured (not `json.dumps`’d) | Lets tests script tool calls without breaking existing `chat_json` dict replies |

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

## Current status

- **In progress**: none on chat path
- **Last reconciled with code**: 2026-08-13
