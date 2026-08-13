# RealtimeVoice — TODO

**Last Updated**: 2026-08-13  
**Related Spec**: [RealtimeVoice.md](RealtimeVoice.md)

---

## Current focus *(session handoff)*

**Active task:** Medium — ephemeral tokens for client-side connect (if we wrap that API).  
**Blocked by:** —  
**Last session:** 2026-08-13 — High Priority realtime session + audio + mocked WS tests + meter/prices shipped

*Next agent: High is drained. library-only · exercise path: pytest + optional `XAITKIT_LIVE=1` + `XAITKIT_LIVE_VOICE=1` smoke. Do not add a recorder UI.*

---

## High Priority / Next Actions

*(drained — 2026-08-13)*

## Medium Priority

- [ ] Ephemeral tokens for client-side connect (if we wrap that API)
- [ ] Streaming STT-only / TTS-only over WS if distinct from STS

## Low Priority / Future Ideas

- [ ] Custom voice `voice_id` on the realtime path
- [ ] Catalog: voice models in resolve helpers

## Cross-Feature Dependencies & Integration Notes

- **library-only** — mocked tests, not a recorder UI. Optional live: `XAITKIT_LIVE=1 XAITKIT_LIVE_VOICE=1 uv run pytest tests/test_live_smoke.py -m live`
- REST STT/TTS stay on [MediaRest-TODO.md](MediaRest-TODO.md).
- Video generation shipped 2026-08-12 ([VideoGeneration-TODO.md](VideoGeneration-TODO.md)).

## Completed

- [x] Split from ApiCoverage after human rank (2026-08-12)
- [x] **Realtime session** — wrap xAI Voice / Realtime WebSocket: connect, auth, close (2026-08-13)
- [x] **Audio stream** — inbound/outbound audio (and optional text) with documented knobs (2026-08-13)
- [x] **Contract tests** — mocked WS: auth header, empty-session guards, purpose-when-metered, usage modality (2026-08-13)
- [x] **Meter + prices** — `modality="realtime"`; default `per_minute_usd` rows from public STS rates (2026-08-13)
