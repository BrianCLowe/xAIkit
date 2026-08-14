# RealtimeVoice — TODO

**Last Updated**: 2026-08-13  
**Related Spec**: [RealtimeVoice.md](RealtimeVoice.md)

---

## Current focus *(session handoff)*

**Active task:** *(stem shipped — High/Medium/Low drained; human verify Done)*  
**Blocked by:** —  
**Last session:** 2026-08-13 — Human verify closed via Rivenquill live STS conversation mode (mint + browser WS + server VAD).

---

## High Priority / Next Actions

*(drained — 2026-08-13)*

## Medium Priority

*(none)*

## Low Priority / Future Ideas

*(drained — 2026-08-13)*

## Human verify (orchestration 2026-08-13)

- [x] **2026-08-13 — Live via Rivenquill** — Ephemeral mint + browser STS + server VAD confirmed (consumer proof of kit mint/protocol/realtime path). Dual-write: [Human-TODO.md](../Human-TODO.md) Done. Chat-UI transcript jank is Rivenquill product, not kit.

## Cross-Feature Dependencies & Integration Notes

- **library-only** — mocked tests, not a recorder UI. Optional live: `XAITKIT_LIVE=1 XAITKIT_LIVE_VOICE=1 uv run pytest tests/test_live_smoke.py -m live`
- REST STT/TTS, streaming STT (`open_stt_session`), and streaming TTS (`open_tts_session`) stay on [MediaRest-TODO.md](MediaRest-TODO.md).
- Video generation shipped 2026-08-12 ([VideoGeneration-TODO.md](VideoGeneration-TODO.md)).

## Completed

- [x] Split from ApiCoverage after human rank (2026-08-12)
- [x] **Realtime session** — wrap xAI Voice / Realtime WebSocket: connect, auth, close (2026-08-13)
- [x] **Audio stream** — inbound/outbound audio (and optional text) with documented knobs (2026-08-13)
- [x] **Contract tests** — mocked WS: auth header, empty-session guards, purpose-when-metered, usage modality (2026-08-13)
- [x] **Meter + prices** — `modality="realtime"`; default `per_minute_usd` rows from public STS rates (2026-08-13)
- [x] Streaming STT-only over WS — home: [MediaRest-TODO.md](MediaRest-TODO.md) (`open_stt_session`; not STS) (2026-08-13)
- [x] Streaming TTS-only over WS if distinct from STS — home: [MediaRest-TODO.md](MediaRest-TODO.md) (`open_tts_session` / `TtsSession` on `wss://api.x.ai/v1/tts`; not STS) (2026-08-13)
- [x] **Ephemeral tokens for client-side connect** — `create_realtime_client_secret` wraps `POST /v1/realtime/client_secrets`; `realtime_client_secret_protocol`; mocked HTTP; no product login (2026-08-13)
- [x] Catalog: voice models in resolve helpers — shipped on [Catalog-TODO.md](Catalog-TODO.md) (`role=voice`; 2026-08-13); closed here as a stale pointer (not this slice)
- [x] Custom voice `voice_id` on the realtime path — `voice=` forwards opaque ids unchanged on `session.update`; empty/whitespace keeps default; no allowlist; clone/roster not this stem (2026-08-13)
- [x] README end-to-end-ish recv loop (app owns mic/speaker) (2026-08-13)
- [x] Human verify look-list (orchestration 2026-08-13) — Rivenquill live STS consumer proof (2026-08-13)
