# ClientChat — TODO

**Last Updated**: 2026-08-12  
**Related Spec**: [ClientChat.md](ClientChat.md)

---

## Current focus *(session handoff)*

**Active task:** Chat path is shipped; next library work is video. Tools / vision / structured outputs are **target on this spec** — implement when that slice is picked (no order after voice).  
**Blocked by:** —  
**Last session:** 2026-08-12 — live xAI smokes (chat / JSON / stream / unpinned / thought_level)

*Next agent: only pick up this file if chat/tools/vision work is in scope.*

---

## High Priority / Next Actions

*(none — shipped text path. Tools / vision / schema are Medium, home on this spec.)*

## Medium Priority

- [ ] **Native structured outputs** — `chat_json` uses xAI schema / `response_format` (fence-strip fallback until then)
- [ ] **Multimodal chat messages** — image (and later video) parts, not only `list[dict[str, str]]`
- [ ] **Tools / function calling** — defs in, tool calls out; app owns the loop

## Low Priority / Future Ideas

- [ ] Async `XaiClient` twin if callers need it (xai-sdk has `aio`)

## Cross-Feature Dependencies & Integration Notes

- **library-only** — exercise path is `uv run pytest` / mock provider, not a UI. Optional live: `XAITKIT_LIVE=1 uv run pytest tests/test_live_smoke.py -m live`.

## Completed

- [x] Typed `chat` / `chat_json` / `chat_stream` (2026-08-12 — in tree)
- [x] Mock provider + retry + purpose-when-metered (2026-08-12)
- [x] Knob pass-through contract tests (PR #2; 2026-08-12)
- [x] Env-gated live chat smokes (2026-08-12)
