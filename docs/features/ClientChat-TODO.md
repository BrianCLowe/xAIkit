# ClientChat — TODO

**Last Updated**: 2026-08-13 *(service tier + deferred covering)*  
**Related Spec**: [ClientChat.md](ClientChat.md)

---

## Current focus *(session handoff)*

**Active task:** Chat extras shipped (tools, vision parts, `chat_json` schema, `service_tier`, deferred helpers). Next library work is not on this stem — remainder lives on [ApiCoverage-TODO.md](ApiCoverage-TODO.md) (unordered) or Low (async twin).  
**Blocked by:** —  
**Last session:** 2026-08-13 — covering service tier + deferred chat helpers from [ApiCoverage-TODO.md](ApiCoverage-TODO.md)

---

## High Priority / Next Actions

*(none — text path + tools/vision/schema/service_tier/deferred shipped.)*

## Medium Priority

*(none)*

## Low Priority / Future Ideas

- [ ] Async `XaiClient` twin if callers need it (xai-sdk has `aio`)

## Cross-Feature Dependencies & Integration Notes

- **library-only** — exercise path is `uv run pytest` / mock provider, not a UI. Optional live: `XAITKIT_LIVE=1 uv run pytest tests/test_live_smoke.py -m live`.

## Completed

- [x] Typed `chat` / `chat_json` / `chat_stream` (2026-08-12 — in tree)
- [x] Mock provider + retry + purpose-when-metered (2026-08-12)
- [x] Knob pass-through contract tests (PR #2; 2026-08-12)
- [x] Env-gated live chat smokes (2026-08-12)
- [x] Tools / function calling — defs in, tool calls out; app owns the loop (2026-08-13)
- [x] Multimodal chat messages — image (and later video) parts, not only `list[dict[str, str]]` (2026-08-13)
- [x] Native structured outputs — `chat_json` uses xAI schema / `response_format` (fence-strip fallback) (2026-08-13)
- [x] Service tier / deferred chat helpers — covering [ApiCoverage-TODO.md](ApiCoverage-TODO.md) (`service_tier` on chat; `create_deferred_chat` / `get_deferred_chat`) (2026-08-13)
