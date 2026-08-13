# RealtimeVoice — TODO

**Last Updated**: 2026-08-13  
**Related Spec**: [RealtimeVoice.md](RealtimeVoice.md)

---

## Current focus *(session handoff)*

**Active task:** Medium — Streaming TTS-only over WS if distinct from STS  
**Blocked by:** —  
**Last session:** 2026-08-13 — ephemeral client-secret mint (`create_realtime_client_secret`) + mocked HTTP tests

*Next agent: library-only · exercise path: pytest + optional `XAITKIT_LIVE=1` + `XAITKIT_LIVE_VOICE=1` smoke. Do not add a recorder UI.*

---

## High Priority / Next Actions

*(drained — 2026-08-13)*

## Medium Priority

- [ ] Streaming TTS-only over WS if distinct from STS

## Low Priority / Future Ideas

- [ ] Custom voice `voice_id` on the realtime path

## Cross-Feature Dependencies & Integration Notes

- **library-only** — mocked tests, not a recorder UI. Optional live: `XAITKIT_LIVE=1 XAITKIT_LIVE_VOICE=1 uv run pytest tests/test_live_smoke.py -m live`
- REST STT/TTS and streaming STT (`open_stt_session`) stay on [MediaRest-TODO.md](MediaRest-TODO.md).
- Video generation shipped 2026-08-12 ([VideoGeneration-TODO.md](VideoGeneration-TODO.md)).

## Completed

- [x] Split from ApiCoverage after human rank (2026-08-12)
- [x] **Realtime session** — wrap xAI Voice / Realtime WebSocket: connect, auth, close (2026-08-13)
- [x] **Audio stream** — inbound/outbound audio (and optional text) with documented knobs (2026-08-13)
- [x] **Contract tests** — mocked WS: auth header, empty-session guards, purpose-when-metered, usage modality (2026-08-13)
- [x] **Meter + prices** — `modality="realtime"`; default `per_minute_usd` rows from public STS rates (2026-08-13)
- [x] Streaming STT-only over WS — home: [MediaRest-TODO.md](MediaRest-TODO.md) (`open_stt_session`; not STS) (2026-08-13)
- [x] **Ephemeral tokens for client-side connect** — `create_realtime_client_secret` wraps `POST /v1/realtime/client_secrets`; `realtime_client_secret_protocol`; mocked HTTP; no product login (2026-08-13)
- [x] Catalog: voice models in resolve helpers — shipped on [Catalog-TODO.md](Catalog-TODO.md) (`role=voice`; 2026-08-13); closed here as a stale pointer (not this slice)
