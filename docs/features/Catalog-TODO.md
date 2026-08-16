# Catalog — TODO

**Last Updated**: 2026-08-16  
**Related Spec**: [Catalog.md](Catalog.md)

---

## Current focus *(session handoff)*

**Active task:** — (Human verify extras closed via tester 2026-08-16). Model-watch Action is the inbox when public docs drift.  
**Blocked by:** —  
**Last session:** 2026-08-16 — Tester live: `persist_path` / `save_catalog_snapshot` + `role=video` / `need=video_extend`. Dual-write Human-TODO Done.

---

## High Priority / Next Actions

*(none blocking — role-filtered catalog landed.)*

## Medium Priority

*(none)*

## Low Priority / Future Ideas

*(none)*

## Human verify (orchestration 2026-08-13)

### Core — done (consumer proof)

- [x] **2026-08-13 — Live via Rivenquill** — `role=chat` + intent/pin (`best` / `economy` / `cheapest` / SKU) + `thought_level` (default / low / high) in the Quill chat picker. Imagine and conversation mode resolve admin `best` on `role=image` / `role=voice`. `BOOTSTRAP_MODEL` (`grok-4.6`) is the kit resolve fallback. Outcome: works. Dual-write: [Human-TODO.md](../Human-TODO.md) Done.

### Extras — done (consumer proof)

- [x] **2026-08-16 — Live via xAIkit tester** — `list_models(..., persist_path=)` / `save_catalog_snapshot`; `role=video` resolve + `need=video_extend`. Outcome: works. Dual-write: [Human-TODO.md](../Human-TODO.md) Done.

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
- [x] Feature map + `need=` — `feature_options(model=)` for settings knobs; resolve `best` filters to SKUs that have the job extras (quality over 1.5 for extend). `contract_model_for_need` remaps known SKUs that lack an extra. Dual-write: [Human-TODO.md](../Human-TODO.md) (2026-08-15)
