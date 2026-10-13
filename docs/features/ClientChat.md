# ClientChat

**Last Updated**: 2026-10-13 *(custom base_url)*
**Related Understanding**: —  

---

**Humans:** This is the contract. How to read it: [`help/SCAFFOLDS.md`](../templates/help/SCAFFOLDS.md) · [`help/USAGE.md`](../templates/help/USAGE.md).

**Agents:** Fill-in blanks — not a tutorial. If context is thin, re-open [`agent/workflow/understanding.md`](../templates/agent/workflow/understanding.md) §2. Catalog: [`agent/workflow/extensions.md`](../templates/agent/workflow/extensions.md) §7.1. Decisions: [`agent/workflow/decisions.md`](../templates/agent/workflow/decisions.md). Operable Acceptance: [`agent/workflow/todos.md`](../templates/agent/workflow/todos.md) §5.3. build-first (no Understanding): [`agent/workflow/profile-standing.md`](../templates/agent/workflow/profile-standing.md) §0.1.

---

## Overview

Typed chat transport: `XaiClient.chat`, `chat_json`, and `chat_stream`, plus the async twin `AsyncXaiClient` with the same method names. Live path uses `SdkChatProvider` over `xai_sdk.Client` (sync) or `AsyncSdkChatProvider` over `xai_sdk.AsyncClient` (async); tests inject `MockChatProvider` (sync `complete`/`stream` plus `async_complete`/`async_stream`). Domain schemas stay in consuming apps.

The same methods accept tool defs, multimodal content parts, and native structured outputs on `chat_json`. Do not add a second chat client or replace `chat` with the Responses API.

## Architecture / Contract

- **Owns**: message list → completion/stream; knob forwarding; retry on open; optional usage/trace hooks; tool defs + tool-result turns; image/video message parts; schema structured outputs on `chat_json`; `service_tier`; deferred chat create/get helpers
- **Does not own**: product prompts, the app’s tool *loop* (kit never executes tools), UI, media REST (see [MediaRest](MediaRest.md)), Responses-as-default / built-in agent tools
- **Public API**: `XaiClient`, `AsyncXaiClient`, `ChatProvider`, `AsyncChatProvider`, `MockChatProvider`, `SdkChatProvider`, `AsyncSdkChatProvider`, `CompletionResponse`, `StreamChunk`

Knobs forwarded to the provider: `model`, `temperature`, `max_tokens`, `thought_level`, `system_prompt`, `tools` / `tool_choice` / `parallel_tool_calls`, multimodal `content` parts, `chat_json` `schema` / `response_format`, `service_tier` (`"default"` | `"priority"`; omit when `None`). `effort` is an alias for `thought_level`. `thought_level` maps to xAI `reasoning_effort` (`low` \| `medium` \| `high` \| `xhigh` on 4.6+). Send path contracts via `contract_thought_level` for thinner families (4.5 `xhigh`→`high`; older `medium`→`low` and `xhigh`→`high`; non-reasoning omits). Meter records the contracted (on-the-wire) value.

Deferred chat is a separate REST pair (`create_deferred_chat` / `get_deferred_chat`) — not an overload of `chat` → `CompletionResponse`. Constant `XAI_DEFERRED_CHAT_URL`.

`XaiClient` and `AsyncXaiClient` take `base_url`. A blank argument is unset. The fallback is the `XAI_BASE_URL` environment variable, and a blank value there is unset too. Otherwise the base is `https://api.x.ai/v1`. Precedence is constructor argument, then `XAI_BASE_URL`, then the default. The value is stored on `base_url` when the client is constructed. Changing the environment later does not move an existing client.

Every REST call this client makes, and the speech-to-text, text-to-speech, and realtime websockets, use that base. `https` maps to `wss` and `http` maps to `ws`, with the same host, port, and path. One trailing slash is removed. The path is used as given, with no automatic `/v1`. Any host is accepted. A scheme other than http or https, a missing host, a query, a fragment, or userinfo raises `ValueError` and the message does not include the credentials.

Chat on a base whose path is empty or `/v1` stays on the SDK gRPC channel. The gRPC `api_host` is `host:port` from the base, and `http` uses an insecure channel. The default base does not pass those arguments, so it stays on the SDK default host. Chat and `chat_stream` on any other path use REST `POST <base>/chat/completions`. `chat_stream` sets `stream` to true and reads server-sent events. That REST body uses the same kit-to-wire adapters as the SDK path (function tools, named `tool_choice`, `chat_json` schemas, assistant `tool_calls`, and content parts). Text, `image_url`, `file` (`file_id`, url, or inline bytes), and `video_url` are sent with the same fields the SDK content helpers send. Inline file bytes are base64 in the JSON body. An injected `provider`, including `MockChatProvider`, is the chat transport even on a path-prefixed base, and that call does not hit the network. A non-default base loads models with REST `GET <base>/models`. Best and economy on that host, and `RoleUnavailableOnHost` when an unpinned role is missing, are specified in [Catalog.md](Catalog.md) (XK-AC-REGION-1, XK-AC-REGION-2). The usage meter does not apply the 10% US endpoint token premium. The default base keeps the gRPC model list. Collections and batch stay on the SDK default hosts: a custom chat `api_host` is a separate client and does not move them. OAuth connect and the usage meter price fetch do not follow `base_url`.

Public `XAI_*_URL` constants stay exported with their current default values. They are derived from one default constant.

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
| 2026-08-14 | 4.6 thought levels + per-model contraction | Flagship can pass `xhigh`/`medium`. Older models get the documented clamp instead of a 400 or a silent API remap the meter would miss. |
| 2026-10-13 | `base_url`, then `XAI_BASE_URL`, then `https://api.x.ai/v1`. Path-prefix chat and non-default models use REST. A bare host or `/v1` keeps gRPC `host:port`. Collections, batch, OAuth, and meter prices do not follow `base_url`. | CUT-2026-10-13-xk-custom-base-url (XK-AC-URL-1, XK-AC-URL-2). QA defaults Q1 through Q12 accepted. |
| 2026-10-13 | Path-prefix `chat` and `chat_stream` use REST with the SDK kit-to-wire adapters. An injected provider wins over that REST route. Batch and collections use an SDK client left on the default hosts, separate from a custom gRPC chat host. | Bugbot on the same cut. Q9 keeps collections and batch off `base_url`. |
| 2026-10-13 | Non-default host model choice follows [Catalog.md](Catalog.md) XK-AC-REGION-1 and XK-AC-REGION-2. The usage meter does not apply the 10% US endpoint token premium. | Host list is a catalog rule. Client chat, image, video, TTS, STT, and realtime call it before the request. |
| 2026-10-13 | REST content parts are built from the kit part fields, not by reading SDK protos back. Inline file bytes and `video_url` stay on the wire. | Proto round-trip dropped file `data` and rewrote `video_url` as `file`. |

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
- [x] XK-AC-URL-1: `base_url` on `XaiClient` and `AsyncXaiClient`, then `XAI_BASE_URL`, then `https://api.x.ai/v1`. Every REST call and the stt, tts, and realtime websockets derive from it.
- [x] XK-AC-URL-2: Any host is accepted. With no `base_url` and no env, URLs, methods, headers, and bodies stay as they are today. Auth stays `Authorization: Bearer`.

## Visual references

*(none — library stem)*

## Current status

- **In progress**: none on chat path (async twin shipped)
- **Last reconciled with code**: 2026-10-13
