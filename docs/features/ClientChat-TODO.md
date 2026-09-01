# ClientChat — TODO

**Last Updated**: 2026-08-31  
**Related Spec**: [ClientChat.md](ClientChat.md)

---

## Current focus *(session handoff)*

**Active task:** — (Human verify extras closed via tester 2026-08-16)  
**Blocked by:** —  
**Last session:** 2026-08-16 — Tester live: tools, vision parts (≥8×8), `service_tier`, `AsyncXaiClient`. Dual-write Human-TODO Done.

---

## High Priority / Next Actions

*(none — text path + tools/vision/schema/service_tier/deferred + async twin shipped.)*

## Medium Priority

*(none)*

## Low Priority / Future Ideas

*(none)*

## Human verify (orchestration 2026-08-13)

### Core — done (consumer proof)

- [x] **2026-08-13 — Live via Rivenquill** — Quill chat + structured `chat_json`/`schema=` (propose-edits and related) against PyPI `xaikit-py`. Outcome: works. Dual-write: [Human-TODO.md](../Human-TODO.md) Done.

### Extras — done (consumer proof)

- [x] **2026-08-16 — Live via xAIkit tester** — tools / function calling; vision parts (live xAI rejects images under 8×8); `service_tier`; `AsyncXaiClient`. Outcome: works. Dual-write: [Human-TODO.md](../Human-TODO.md) Done.

## Cross-Feature Dependencies & Integration Notes

- **library-only** — exercise path is `uv run pytest` / mock provider, not a UI. Optional live: `XAITKIT_LIVE=1 uv run pytest tests/test_live_smoke.py -m live` (includes tools, vision ≥8×8, `service_tier`, `AsyncXaiClient`).
- Vision `detail` (`auto`/`low`/`high`) is already on chat parts — no new knob TODO. Imagine generate/edit knobs live on [MediaRest-TODO.md](MediaRest-TODO.md).

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
- [x] 4.6 `reasoning_effort` set (`low`/`medium`/`high`/`xhigh`) with per-model contraction (2026-08-14)
