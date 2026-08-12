# RealtimeVoice — TODO

**Last Updated**: 2026-08-12  
**Related Spec**: [RealtimeVoice.md](RealtimeVoice.md)

---

## Current focus *(session handoff)*

**Active task:** Wait until [VideoGeneration](VideoGeneration-TODO.md) ships, then implement realtime voice on the kit.  
**Blocked by:** [VideoGeneration-TODO.md](VideoGeneration-TODO.md)  
**Last session:** 2026-08-12 — human ranked this next after video

*Next agent: do not start this stem while video High Priority is open. library-only · exercise path: pytest + optional env-gated smoke.*

---

## High Priority / Next Actions

- [ ] **Realtime session** — wrap xAI Voice / Realtime WebSocket (or `xai_sdk` equivalent): connect, auth, close
- [ ] **Audio stream** — inbound/outbound audio (and optional text) with documented knobs
- [ ] **Contract tests** — mocked WS/SDK: auth header, empty-session guards, purpose-when-metered, usage modality
- [ ] **Meter + prices** — `modality` for realtime voice; default price rows if public rates exist

## Medium Priority

- [ ] Ephemeral tokens for client-side connect (if we wrap that API)
- [ ] Streaming STT-only / TTS-only over WS if distinct from STS

## Low Priority / Future Ideas

- [ ] Custom voice `voice_id` on the realtime path
- [ ] Catalog: voice models in resolve helpers

## Cross-Feature Dependencies & Integration Notes

- **library-only** — mocked tests, not a recorder UI. Optional live: `XAITKIT_LIVE=1 uv run pytest tests/test_live_smoke.py -m live` once a live test exists.
- REST STT/TTS stay on [MediaRest-TODO.md](MediaRest-TODO.md).
- Do not implement while video is the Current focus on [VideoGeneration-TODO.md](VideoGeneration-TODO.md).

## Completed

- [x] Split from ApiCoverage after human rank (2026-08-12)
