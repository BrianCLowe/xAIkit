# RealtimeVoice

**Last Updated**: 2026-08-12  
**Related TODO**: [RealtimeVoice-TODO.md](RealtimeVoice-TODO.md)

## Overview

**Not shipped.** Next API slice **after video**: wrap xAI **realtime voice** (speech-to-speech over WebSocket) the same way the kit wraps chat — typed client surface, purpose-tagged metering, offline contract tests, no voice UI.

REST unary STT/TTS stay on [MediaRest](MediaRest.md). This stem is the live duplex / agent voice path (`wss://api.x.ai/v1/realtime` or the Voice STS WebSocket in current xAI docs).

## Architecture / Contract

- **Owns** (planned): session open/close, audio in/out streaming, optional text, usage `modality` for realtime voice
- **Does not own**: REST `transcribe` / `synthesize_speech`; custom voice clone; a recorder UI; ephemeral-token product login
- **Public API** (planned, names not frozen): e.g. `XaiClient` realtime session helper or a small `xaikit.voice` module — same `api_key` / `CredentialStore` / purpose-when-metered rules

Prefer wrapping `xai_sdk` (or documented WS protocol) rather than inventing a second stack.

## Behavior (stable)

*Target — not implemented:*

- Missing credentials fail before connect
- Purpose required when metered
- Failures record failed usage; callers get a typed `RuntimeError` (or documented WS error)
- Contract tests mock the socket/SDK — no live mic in CI
- Optional live smoke stays env-gated (`XAITKIT_LIVE=1` + `XAI_API_KEY`)

## Decisions

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-08-12 | Realtime voice is the next slice after video | User rank; remaining API unordered |
| 2026-08-12 | Split off ApiCoverage into this map row | Workflow: winner gets its own spec + TODO before implement |
| 2026-08-12 | Library-only prove-out | Standing: mock + tests, no playground UI |

## Dependencies

| Piece | Relationship |
|-------|--------------|
| [MediaRest.md](MediaRest.md) | REST STT/TTS already shipped; do not duplicate |
| [ConnectAuth.md](ConnectAuth.md) | API key / store |
| [UsageObservability.md](UsageObservability.md) | New modality + prices |
| [VideoGeneration.md](VideoGeneration.md) | **Implement after video** |
| [ApiCoverage.md](ApiCoverage.md) | Remainder inventory (no order) |

## Acceptance *(library stem — open until shipped)*

- [ ] Open/close a realtime session with auth
- [ ] Stream audio (and optional text) with documented knobs
- [ ] Meter purpose + realtime-voice modality
- [ ] Offline contract tests; optional live smoke env-gated

## Current status

- **In progress**: spec + TODO only — wait for video
- **Last reconciled with code**: 2026-08-12 (no realtime voice in `XaiClient`)
