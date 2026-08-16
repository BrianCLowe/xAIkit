# Catalog — TODO

**Last Updated**: 2026-08-15  
**Related Spec**: [Catalog.md](Catalog.md)

---

## Current focus *(session handoff)*

**Active task:** Stem shipped — Catalog High / Medium / Low drained. Human verify **extras** still open (`persist_path` / `role=video`). Model-watch Action is the inbox when public docs drift.  
**Blocked by:** —  
**Last session:** 2026-08-15 — feature-map identity locked (chat tools + video extras; `effort_options`-shaped discovery). No code until Human-TODO decide says implement.

---

## High Priority / Next Actions

*(none blocking — role-filtered catalog landed.)*

## Medium Priority

*(none)*

## Low Priority / Future Ideas

- [ ] **Capability map for resolve** — identity locked: per-SKU extras as settings knobs (chat tools + video/media), not role tags. First slice: discovery helper like `effort_options(model=)` using documented xAI tool types (`web_search`, `x_search`, `code_execution`, `collections_search`, `mcp`, …) plus media extras (`video_extend`, `video_edit`, `1080p`, …). Second slice: resolve `best` for the **job** (quality over 1.5 when the job is extend/edit). Wait for Human-TODO decide to say implement. Dual-write: [Human-TODO.md](../Human-TODO.md)

## Human verify (orchestration 2026-08-13)

### Core — done (consumer proof)

- [x] **2026-08-13 — Live via Rivenquill** — `role=chat` + intent/pin (`best` / `economy` / `cheapest` / SKU) + `thought_level` (default / low / high) in the Quill chat picker. Imagine and conversation mode resolve admin `best` on `role=image` / `role=voice`. `BOOTSTRAP_MODEL` (`grok-4.6`) is the kit resolve fallback. Outcome: works. Dual-write: [Human-TODO.md](../Human-TODO.md) Done.

### Extras — still open

Library look-list — reply in chat when done (do not mark this row yourself).

- **Surfaces:** `list_models(..., persist_path=)` / `save_catalog_snapshot`; `role=video` resolve (Rivenquill has no video job)
- **Placement:** `src/xaikit/catalog.py`; default prices in `pricing.py`
- **Copy:** README persist_path one-liner
- **Happy path:** `uv run pytest tests/test_catalog.py`
- **Rough edges:** persist is opt-in (no default path); mock HTTP tests may still pin dummy `grok-3-mini`

## Completed

- [x] Persist catalog snapshot to disk (today is in-process) (2026-08-13 — opt-in `persist_path=` / `save_catalog_snapshot`; no default cwd/home path)
- [x] Catalog module + resolve + thought_level mapping (2026-08-12 — in tree)
- [x] Resolve-chain contract tests + `non-reasoning` slug tag (2026-08-12 — live catalog)
- [x] Three intents + coding-SKU skip (2026-08-12)
- [x] Role-filtered resolve — `role=image|video|voice` using the same cheapest / economy / best rules (2026-08-13)
- [x] Surface image/video/voice models in fetch (not chat-only `list_language_models`) (2026-08-13)
- [x] Refresh bootstrap / fixture models when xAI retires slugs (2026-08-13 — `BOOTSTRAP_MODEL=grok-4.6`; offline cheap row `grok-4.3`; grok-3-mini out of fallback)
- [x] 4.6 thought levels + per-model contraction (`contract_thought_level`, `effort_options(model=)`) (2026-08-14)
- [x] Public-docs model watch — new slugs (Imagine 3.0) and resolution tokens (4k) open a `xai-models` GitHub issue (2026-08-14)
