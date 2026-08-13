# MediaRest — TODO

**Last Updated**: 2026-08-13 *(image edit + Imagine `file_id` on generate/edit)*  
**Related Spec**: [MediaRest.md](MediaRest.md)

---

## Current focus *(session handoff)*

**Active task:** Streaming STT — only if still unary-transcribe; STS is [RealtimeVoice-TODO.md](RealtimeVoice-TODO.md)  
**Blocked by:** —  
**Last session:** 2026-08-13 — `edit_image` JSON `/v1/images/edits`; surface `file_output.file_id` on generate/edit

---

## High Priority / Next Actions

*(none blocking — REST generate/edit shipped. Streaming STT: Medium, home on this spec.)*

## Medium Priority

- [ ] **Streaming STT** — only if still unary-transcribe; STS is [RealtimeVoice-TODO.md](RealtimeVoice-TODO.md)

## Low Priority / Future Ideas

- [ ] Voice roster helper (list TTS `voice_id`s) instead of hard-coded default only

## Cross-Feature Dependencies

- **library-only** — mocked HTTP tests, not a recorder UI.
- Files upload / `file_id` minting stays on [ApiCoverage-TODO.md](ApiCoverage-TODO.md); this stem forwards `file_id` on the wire and surfaces Imagine `file_output.file_id`.

## Completed

- [x] `transcribe` / `synthesize_speech` / `generate_image` (2026-08-12 — in tree)
- [x] Media REST wiring tests (PR #2; 2026-08-12)
- [x] Env-gated live TTS / STT / Imagine smokes (2026-08-12)
- [x] **Image edit / i2i** — `edit_image` per [MediaRest.md](MediaRest.md) (`POST /v1/images/edits` JSON, not multipart) (2026-08-13)
- [x] Surface Imagine `file_output.file_id` on generate/edit when upstream returns it (2026-08-13)
