# MediaRest — TODO

**Last Updated**: 2026-08-13  
**Related Spec**: [MediaRest.md](MediaRest.md)

---

## Current focus *(session handoff)*

**Active task:** Low — Voice roster helper (list TTS `voice_id`s) instead of hard-coded default only  
**Blocked by:** —  
**Last session:** 2026-08-13 — Streaming STT (`open_stt_session` / `SttSession`) over `wss://api.x.ai/v1/stt` (not STS)

---

## High Priority / Next Actions

*(none blocking)*

## Medium Priority

*(none)*

## Low Priority / Future Ideas

- [ ] Voice roster helper (list TTS `voice_id`s) instead of hard-coded default only

## Cross-Feature Dependencies

- **library-only** — mocked HTTP/WS tests, not a recorder UI.
- Files upload / `file_id` minting stays on [ApiCoverage-TODO.md](ApiCoverage-TODO.md); this stem forwards `file_id` on the wire and surfaces Imagine `file_output.file_id`.
- STS (`wss://api.x.ai/v1/realtime`) stays on [RealtimeVoice-TODO.md](RealtimeVoice-TODO.md). Streaming TTS-only WS, if distinct, stays there.

## Completed

- [x] `transcribe` / `synthesize_speech` / `generate_image` (2026-08-12 — in tree)
- [x] Media REST wiring tests (PR #2; 2026-08-12)
- [x] Env-gated live TTS / STT / Imagine smokes (2026-08-12)
- [x] **Image edit / i2i** — `edit_image` per [MediaRest.md](MediaRest.md) (`POST /v1/images/edits` JSON, not multipart) (2026-08-13)
- [x] Surface Imagine `file_output.file_id` on generate/edit when upstream returns it (2026-08-13)
- [x] **Streaming STT** — `XaiClient.open_stt_session` / `SttSession` wrapping `wss://api.x.ai/v1/stt` (unary-transcribe; not STS) (2026-08-13)
