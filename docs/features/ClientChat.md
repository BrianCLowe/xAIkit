# ClientChat

**Last Updated**: 2026-08-12  
**Related TODO**: [ClientChat-TODO.md](ClientChat-TODO.md)

## Overview

Typed chat transport: `XaiClient.chat`, `chat_json`, and `chat_stream`. Live path uses `SdkChatProvider` over `xai_sdk.Client`; tests inject `MockChatProvider`. Domain schemas stay in consuming apps.

**Target (not all in tree):** the same methods grow tools, multimodal parts, and native structured outputs. Do not add a second chat client or replace `chat` with the Responses API.

## Architecture / Contract

- **Owns**: message list → completion/stream; knob forwarding; retry on open; optional usage/trace hooks. **Target:** tool defs + tool-result turns; image/video message parts; schema structured outputs on `chat_json`
- **Does not own**: product prompts, the app’s tool *loop*, UI, media REST (see [MediaRest](MediaRest.md)), Responses-as-default
- **Public API**: `XaiClient`, `ChatProvider`, `MockChatProvider`, `SdkChatProvider`, `CompletionResponse`, `StreamChunk`

Knobs forwarded to the provider: `model`, `temperature`, `max_tokens`, `thought_level`, `system_prompt`. **Target knobs:** `tools` / tool choice, multimodal `content` parts. `effort` is an alias for `thought_level`. `thought_level` maps to xAI `reasoning_effort` (`low` \| `high`; `med`/`medium`/`mid` → `low`).

When a `UsageMeter` is attached, `purpose` is required. Without a meter, purpose is optional.

## Behavior (stable)

- `chat` records usage/trace on success and failure; wraps provider errors as `RuntimeError`.
- `chat_json` forces a JSON-only system prompt (overridable), default temperature `0.3`, parses object JSON (strips fences); non-object JSON fails.
- `chat_stream` retries only **opening** the iterator; mid-stream failures are not retried; usage recorded once when the stream completes (not on `GeneratorExit`).
- Client default `thought_level` applies unless the call passes `thought_level` or `effort`.
- Missing credentials without a mock provider raises (pass `api_key`, `CredentialStore`, or `provider=`).
- **Target:** `chat` / stream accept tool definitions and return tool calls on the response; the app runs tools and sends results as follow-up messages.
- **Target:** message `content` may be parts (text + image/video `url` / `file_id` / data), not only `str`. `MockChatProvider` records parts.
- **Target:** `chat_json` uses upstream schema / `response_format` when wrapped; fence-stripping remains fallback until then.

## Decisions

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-08-12 | Library-only prove-out via mock + tests | Wiring, not UX; no playground UI |
| 2026-08-12 | `effort` aliases `thought_level` | Product wording vs xAI `reasoning_effort` |
| 2026-08-12 | Tools, vision, structured outputs stay on this client | Final kit — not a second chat stack ([ApiCoverage](ApiCoverage.md)) |

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
- [ ] Tools / function calling on `chat` / `chat_stream` (app owns the loop)
- [ ] Multimodal message parts
- [ ] Native structured outputs on `chat_json`

## Current status

- **In progress**: none on chat path
- **Last reconciled with code**: 2026-08-12
