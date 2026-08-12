# ClientChat

**Last Updated**: 2026-08-12  
**Related TODO**: [ClientChat-TODO.md](ClientChat-TODO.md)

## Overview

Typed chat transport: `XaiClient.chat`, `chat_json`, and `chat_stream`. Live path uses `SdkChatProvider` over `xai_sdk.Client`; tests inject `MockChatProvider`. Domain schemas stay in consuming apps.

## Architecture / Contract

- **Owns**: message list → completion/stream; knob forwarding; retry on open; optional usage/trace hooks
- **Does not own**: product prompts, tool loops, UI, media REST (see [MediaRest](MediaRest.md))
- **Public API**: `XaiClient`, `ChatProvider`, `MockChatProvider`, `SdkChatProvider`, `CompletionResponse`, `StreamChunk`

Knobs forwarded to the provider: `model`, `temperature`, `max_tokens`, `thought_level`, `system_prompt`. `effort` is an alias for `thought_level`. `thought_level` maps to xAI `reasoning_effort` (`low` \| `high`; `med`/`medium`/`mid` → `low`).

When a `UsageMeter` is attached, `purpose` is required. Without a meter, purpose is optional.

## Behavior (stable)

- `chat` records usage/trace on success and failure; wraps provider errors as `RuntimeError`.
- `chat_json` forces a JSON-only system prompt (overridable), default temperature `0.3`, parses object JSON (strips fences); non-object JSON fails.
- `chat_stream` retries only **opening** the iterator; mid-stream failures are not retried; usage recorded once when the stream completes (not on `GeneratorExit`).
- Client default `thought_level` applies unless the call passes `thought_level` or `effort`.
- Missing credentials without a mock provider raises (pass `api_key`, `CredentialStore`, or `provider=`).

## Decisions

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-08-12 | Library-only prove-out via mock + tests | Wiring, not UX; no playground UI |
| 2026-08-12 | `effort` aliases `thought_level` | Product wording vs xAI `reasoning_effort` |

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

## Current status

- **In progress**: none on chat path
- **Last reconciled with code**: 2026-08-12
