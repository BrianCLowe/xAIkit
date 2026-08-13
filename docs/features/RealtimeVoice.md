# RealtimeVoice

**Last Updated**: 2026-08-13  
**Related TODO**: [RealtimeVoice-TODO.md](RealtimeVoice-TODO.md)

## Overview

Library-only **realtime voice** (speech-to-speech) on `XaiClient`: documented xAI WebSocket, purpose-tagged metering, offline contract tests (mocked socket). No voice UI, mic, or recorder. REST unary STT/TTS stay on [MediaRest](MediaRest.md).

Upstream: `wss://api.x.ai/v1/realtime?model=…`. Default model `grok-voice-latest` (alias for `grok-voice-think-fast-2.0`). `xai_sdk` has no voice/realtime module — the kit wraps the public WS protocol (same spirit as video wrapping REST via `httpx`).

## Architecture / Contract

- **Owns**: session open/close, inbound/outbound audio, optional text, usage `modality="realtime"`
- **Does not own**: REST `transcribe` / `synthesize_speech`; streaming STT-only WS (shipped on [MediaRest](MediaRest.md) as `open_stt_session`); custom voice clone; a recorder UI; ephemeral-token product login; streaming TTS-only WS; catalog `role=voice`
- **Public API** (frozen 2026-08-13):
  - `XaiClient.open_realtime_session(...)` → `RealtimeSession` (context manager)
  - Constructor: optional `voice_model=` (like `video_model=` / `image_model=`)
  - `RealtimeSession.send_audio`, `send_text`, `commit_audio`, `clear_audio`, `create_response`, `cancel_response`, `update_session`, `send_event`, `recv`, `events`, `close`
  - `decode_realtime_audio(event)` — base64 PCM from `response.output_audio.delta` / `response.audio.delta`

Constants: `XAI_REALTIME_URL` (`wss://api.x.ai/v1/realtime`), `DEFAULT_VOICE_MODEL` (`grok-voice-latest`). Tests monkeypatch `connect_realtime_websocket` (no live socket).

Knobs on open (forwarded on `session.update`; omit unset optionals): `voice` (default `eve`), `instructions`, `turn_detection` (default `{"type": "server_vad"}`; pass `None` for manual), `tools`, `audio` (input/output format + transport), `reasoning_effort` (`high` \| `none`), full `session=` overlay. `purpose` / `parent_id` / `labels` like other media.

Audio send: `input_audio_buffer.append` (bytes base64-encoded, or a base64 string). Text send: `conversation.item.create` + `response.create`. Receive: JSON events or binary frames; decode audio deltas with `decode_realtime_audio`.

## Behavior (stable)

- Missing/empty credentials fail before connect
- Empty audio / empty text rejected before send
- Purpose required when a meter is attached
- Failures record failed usage with `modality="realtime"`; transport errors are `RuntimeError`; meter/trace must not swallow the user-facing error
- Usage is recorded once per session (close or first failure), with wall-clock `duration` seconds for price estimates
- Contract tests mock the WebSocket — no live mic in CI
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

## Dependencies

| Piece | Relationship |
|-------|--------------|
| [MediaRest.md](MediaRest.md) | REST STT/TTS already shipped; do not duplicate |
| [ConnectAuth.md](ConnectAuth.md) | API key / store |
| [UsageObservability.md](UsageObservability.md) | `modality="realtime"` + default per-minute price rows |
| [VideoGeneration.md](VideoGeneration.md) | Pattern for mocked transport + meter |
| [ApiCoverage.md](ApiCoverage.md) | Remainder inventory + target homes |

## Acceptance *(library stem)*

- [x] Open/close a realtime session with auth
- [x] Stream audio (and optional text) with documented knobs
- [x] Meter purpose + realtime-voice modality
- [x] Offline contract tests; optional live smoke env-gated

## Current status

- **Shipped** (library-only): `open_realtime_session` + `RealtimeSession` + meter + default per-minute prices + mocked WS tests
- **Last reconciled with code**: 2026-08-13
