# ClientChat — TODO

**Last Updated**: 2026-08-12  
**Related Spec**: [ClientChat.md](ClientChat.md)

---

## Current focus *(session handoff)*

**Active task:** Chat path is shipped; next library work is video (see [VideoGeneration-TODO.md](VideoGeneration-TODO.md)).  
**Blocked by:** —  
**Last session:** 2026-08-12 — bootstrap from existing code

*Next agent: only pick up this file if chat/tools/vision work is in scope.*

---

## High Priority / Next Actions

*(none — shipped. Tool calling / vision inputs are tracked on [ApiCoverage-TODO.md](ApiCoverage-TODO.md).)*

## Medium Priority

- [ ] **Native structured outputs** — replace fence-stripping `chat_json` with xAI structured-output / schema path when wrapping that API
- [ ] **Multimodal chat messages** — image (and later video) parts on `chat` / stream, not only `list[dict[str, str]]`

## Low Priority / Future Ideas

- [ ] Async `XaiClient` twin if callers need it (xai-sdk has `aio`)

## Cross-Feature Dependencies & Integration Notes

- **library-only** — exercise path is `uv run pytest` / mock provider, not a UI.

## Completed

- [x] Typed `chat` / `chat_json` / `chat_stream` (2026-08-12 — in tree)
- [x] Mock provider + retry + purpose-when-metered (2026-08-12)
- [x] Knob pass-through contract tests (PR #2; 2026-08-12)
