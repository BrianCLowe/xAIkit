# ClientChat — TODO

**Last Updated**: 2026-08-13 *(async client twin)*  
**Related Spec**: [ClientChat.md](ClientChat.md)

---

## Current focus *(session handoff)*

**Active task:** Chat extras + async twin shipped. Next library work is not on this stem — remainder lives on [ApiCoverage-TODO.md](ApiCoverage-TODO.md) (unordered).  
**Blocked by:** —  
**Last session:** 2026-08-13 — `AsyncXaiClient` same-name twin (covering [ApiCoverage-TODO.md](ApiCoverage-TODO.md) async client)

---

## High Priority / Next Actions

*(none — text path + tools/vision/schema/service_tier/deferred + async twin shipped.)*

## Medium Priority

*(none)*

## Low Priority / Future Ideas

*(none)*

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
- [x] Async `XaiClient` twin if callers need it (xai-sdk has `aio`) — `AsyncXaiClient`; covering [ApiCoverage-TODO.md](ApiCoverage-TODO.md) (2026-08-13)
