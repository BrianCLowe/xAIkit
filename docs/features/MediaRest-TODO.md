# MediaRest — TODO

**Last Updated**: 2026-08-12  
**Related Spec**: [MediaRest.md](MediaRest.md)

---

## Current focus *(session handoff)*

**Active task:** Image edit / streaming STT are later; video then realtime voice are the next modalities.  
**Blocked by:** —  
**Last session:** 2026-08-12 — live TTS / STT round-trip / Imagine smokes

---

## High Priority / Next Actions

*(none blocking — shipped REST trio. Follow-ons live on [ApiCoverage-TODO.md](ApiCoverage-TODO.md).)*

## Medium Priority

- [ ] **Image edit / i2i** — wrap Imagine edit once we take that API slice
- [ ] **Streaming STT** — if we wrap the streaming speech-to-text endpoint

## Low Priority / Future Ideas

- [ ] Voice roster helper (list TTS `voice_id`s) instead of hard-coded default only

## Cross-Feature Dependencies

- **library-only** — mocked HTTP tests, not a recorder UI.

## Completed

- [x] `transcribe` / `synthesize_speech` / `generate_image` (2026-08-12 — in tree)
- [x] Media REST wiring tests (PR #2; 2026-08-12)
- [x] Env-gated live TTS / STT / Imagine smokes (2026-08-12)
