# RealtimeVoice

**Last Updated**: 2026-08-13  
**Related TODO**: [RealtimeVoice-TODO.md](RealtimeVoice-TODO.md)

## Overview

Library-only **realtime voice** (speech-to-speech) on `XaiClient`: documented xAI WebSocket, purpose-tagged metering, offline contract tests (mocked socket). No voice UI, mic, or recorder. REST unary STT/TTS and streaming STT/TTS stay on [MediaRest](MediaRest.md). Server-side mint of ephemeral client secrets for browser/mobile STS is included; product login is not.

Upstream: `wss://api.x.ai/v1/realtime?model=…`. Default model `grok-voice-latest` (alias for `grok-voice-think-fast-2.0`). `xai_sdk` has no voice/realtime module — the kit wraps the public WS protocol (same spirit as video wrapping REST via `httpx`). Ephemeral tokens: `POST https://api.x.ai/v1/realtime/client_secrets`.

## Architecture / Contract

- **Owns**: session open/close, inbound/outbound audio, optional text, usage `modality="realtime"`; server-side mint helper `create_realtime_client_secret` (wraps documented `POST /v1/realtime/client_secrets`)
- **Does not own**: REST `transcribe` / `synthesize_speech`; streaming STT-only WS (shipped on [MediaRest](MediaRest.md) as `open_stt_session`); streaming TTS-only WS (shipped on [MediaRest](MediaRest.md) as `open_tts_session`); custom voice **clone** (`POST /v1/custom-voices`) or the TTS voice roster (`GET /v1/tts/voices` — [MediaRest](MediaRest.md)); a recorder UI; ephemeral-token **product login** / User types (ConnectAuth stays stores + OAuth helpers); catalog `role=voice`
- **Public API** (frozen 2026-08-13; mint added 2026-08-13):
  - `XaiClient.open_realtime_session(...)` → `RealtimeSession` (context manager)
  - Constructor: optional `voice_model=` (like `video_model=` / `image_model=`)
  - `RealtimeSession.send_audio`, `send_text`, `commit_audio`, `clear_audio`, `create_response`, `cancel_response`, `update_session`, `send_event`, `recv`, `events`, `close`
  - `decode_realtime_audio(event)` — base64 PCM from `response.output_audio.delta` / `response.audio.delta`
  - `XaiClient.create_realtime_client_secret(*, expires_after=300, purpose=…, parent_id=…, labels=…)` → upstream JSON dict (typically `value`)
  - `realtime_client_secret_protocol(token)` → `xai-client-secret.{token}` for browser `sec-websocket-protocol`

Constants: `XAI_REALTIME_URL` (`wss://api.x.ai/v1/realtime`), `XAI_REALTIME_CLIENT_SECRETS_URL` (`https://api.x.ai/v1/realtime/client_secrets`), `DEFAULT_VOICE_MODEL` (`grok-voice-latest`). Session tests monkeypatch `connect_realtime_websocket` (no live socket). Mint tests mock `httpx.post`.

Knobs on open (forwarded on `session.update`; omit unset optionals): `voice` (default `eve`; built-in ids **or** an opaque custom `voice_id` — no kit allowlist; empty/whitespace keeps the default), `instructions`, `turn_detection` (default `{"type": "server_vad"}`; pass `None` for manual), `tools`, `audio` (input/output format + transport), `reasoning_effort` (`high` \| `none`), full `session=` overlay. `purpose` / `parent_id` / `labels` like other media. Clone/list custom-voices APIs are not on this stem.

Audio send: `input_audio_buffer.append` (bytes base64-encoded, or a base64 string). Text send: `conversation.item.create` + `response.create`. Receive: JSON events or binary frames; decode audio deltas with `decode_realtime_audio`.

Mint body is documented only: `{"expires_after": {"seconds": N}}`. Default `N=300`. Does **not** send `session` or `expires_after.anchor`. Return JSON as-is — do not invent a response schema. Token is used like an API key (`Authorization: Bearer <token>`) or in browsers via `sec-websocket-protocol` with prefix `xai-client-secret.`.

## Behavior (stable)

- Missing/empty credentials fail before connect / before mint HTTP
- Empty audio / empty text rejected before send
- Non-positive / empty `expires_after` rejected before mint HTTP
- Purpose required when a meter is attached
- Failures record failed usage with `modality="realtime"`; transport errors are `RuntimeError`; meter/trace must not swallow the user-facing error
- Session usage is recorded once per session (close or first failure), with wall-clock `duration` seconds for price estimates
- Minting a client secret records purpose/success only (`modality="realtime"`, no duration, no tokens, no USD — not an STS audio-minute)
- Contract tests mock the WebSocket and mint HTTP — no live mic in CI
- Optional live smoke: `XAITKIT_LIVE=1` **and** `XAITKIT_LIVE_VOICE=1` (metered; skipped by default live suite)

## Decisions

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-08-12 | Realtime voice is the next slice after video | User rank; remaining API unordered |
| 2026-08-12 | Split off ApiCoverage into this map row | Workflow: winner gets its own spec + TODO before implement |
| 2026-08-12 | Library-only prove-out | Standing: mock + tests, no playground UI |
| 2026-08-13 | Frozen names: `open_realtime_session` → `RealtimeSession`; `XAI_REALTIME_URL`; `DEFAULT_VOICE_MODEL`; ctor `voice_model=` | Same kit shape as video on `XaiClient` |
| 2026-08-13 | Wrap documented WS protocol (`websockets` sync client), not `xai_sdk` | Installed SDK has no voice/realtime modules; xAI samples use `websockets` |
| 2026-08-13 | Meter modality is `realtime` (not `voice`) | Distinguishes STS from REST TTS; files/embed stay unclaimed |
| 2026-08-13 | `ModelPrice.per_minute_usd` for STS audio-minute list rates | Public table: $0.05/min (think-fast-1.0), $0.08/min (think-fast-2.0 / `grok-voice-latest`). Text-input `$0.004` has no documented unit — not estimated. Estimates, not a billing authority |
| 2026-08-13 | Wrap documented ephemeral-token mint; do not add product login | xAI `POST /v1/realtime/client_secrets`; long-lived key stays server-side. No FastAPI session server, no User types. Body is `expires_after.seconds` only (no `session` / `anchor`). Mint meters purpose/success with `modality="realtime"` and `apply_price_table=False` so estimates stay None |
| 2026-08-13 | `voice=` forwards built-in ids or opaque custom `voice_id`; no clone wrap | Same `session.update` `voice` field as `eve` / `ara`. Empty/whitespace does not overwrite the default. This stem does not own `POST /v1/custom-voices` or `GET /v1/tts/voices` |

## Dependencies

| Piece | Relationship |
|-------|--------------|
| [MediaRest.md](MediaRest.md) | REST STT/TTS and streaming STT/TTS already shipped; do not duplicate |
| [ConnectAuth.md](ConnectAuth.md) | API key / store — mint uses the same server-side key; ConnectAuth does not own this API |
| [UsageObservability.md](UsageObservability.md) | `modality="realtime"` + default per-minute price rows (session close). Mint records purpose/success only |
| [VideoGeneration.md](VideoGeneration.md) | Pattern for mocked transport + meter |
| [ApiCoverage.md](ApiCoverage.md) | Remainder inventory + target homes |

## Acceptance *(library stem)*

- [x] Open/close a realtime session with auth
- [x] Stream audio (and optional text) with documented knobs
- [x] Meter purpose + realtime-voice modality
- [x] Offline contract tests; optional live smoke env-gated
- [x] Server-side ephemeral client-secret mint (`create_realtime_client_secret`); mocked HTTP; no product login
- [x] Custom `voice_id` on `voice=` forwarded unchanged on `session.update` (no allowlist; clone/roster not this stem)

## Current status

- **Shipped** (library-only): `open_realtime_session` + `RealtimeSession` + meter + default per-minute prices + mocked WS tests; `create_realtime_client_secret` + `realtime_client_secret_protocol` + mocked mint tests; `voice=` accepts built-in ids or custom `voice_id` (no clone wrap)
- **Last reconciled with code**: 2026-08-13
