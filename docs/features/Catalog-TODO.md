# Catalog — TODO

**Last Updated**: 2026-09-23 
**Related Spec**: [Catalog.md](Catalog.md)
**Related Understanding**: —

---

**Humans:** [`help/SCAFFOLDS.md`](../templates/help/SCAFFOLDS.md). Inbox: [`Human-TODO.md`](../Human-TODO.md).

**Agents:** Fill-in blanks. If context is thin, re-open [`agent/workflow/todos.md`](../templates/agent/workflow/todos.md) (Current focus §5.1 · operable §5.3 · kit coverage §5.4). Human dual-write: [`agent/workflow/human-todo.md`](../templates/agent/workflow/human-todo.md). Shared foundation: [`agent/workflow/shared-components.md`](../templates/agent/workflow/shared-components.md).

---

## Current focus *(session handoff)*

**Active task:** — (Human verify extras closed via tester 2026-08-16). Model-watch Action is the inbox when public docs drift.  
**Blocked by:** —  
**Last session:** 2026-09-23 — Model watch opens a new `xai-models` issue only for slugs/resolutions not already listed on an open one (New slugs / New resolutions lines, title, or comment). An open transcribe issue no longer hides a later flagship.

---

## High Priority / Next Actions

*(none blocking — role-filtered catalog landed.)*

## Medium Priority

*(none)*

## Low Priority / Future Ideas

*(none)*

## Cross-Feature Dependencies & Integration Notes

*(none)*

## Human verify (orchestration 2026-08-13)

### Core — done (consumer proof)

- [x] **2026-08-13 — Live via Rivenquill** — `role=chat` + intent/pin (`best` / `economy` / `cheapest` / SKU) + `thought_level` (default / low / high) in the Quill chat picker. Imagine and conversation mode resolve admin `best` on `role=image` / `role=voice`. `BOOTSTRAP_MODEL` (`grok-4.6`) is the kit resolve fallback. Outcome: works. Dual-write: [Human-TODO.md](../Human-TODO.md) Done.

### Extras — done (consumer proof)

- [x] **2026-08-16 — Live via xAIkit tester** — `list_models(..., persist_path=)` / `save_catalog_snapshot`; `role=video` resolve + `need=video_extend`. Outcome: works. Dual-write: [Human-TODO.md](../Human-TODO.md) Done. Kit live smoke: `XAITKIT_LIVE=1` `test_live_list_models_persist_and_role_video`.

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
- [x] Review [#49](https://github.com/BrianCLowe/xAIkit/issues/49) (`grok-46`) — UTM false positive; no kit catalog/price change; watcher drops collapsed dotted tokens (2026-08-23)
- [x] Grok 4.7 flagship — `BOOTSTRAP_MODEL=grok-4.7`; price row $2 in / $6 out under 200k (exact key, not the `grok-4` prefix); 4.6+ thought levels and chat extras; no `batch` (model page). Watch baseline: `grok-4.7`, docs-path `grok-4-7`, `grok-voice-transcribe-1.0` / `2.0` (no new STT price key). Cite: https://docs.x.ai/developers/models and https://docs.x.ai/developers/models/grok-4.7 (2026-09-23)
- [x] Model watch files a new issue for unlisted slugs/resolutions while another `xai-models` issue is open. Checklist examples (`4k`) are not listings. `grok-4` does not cover `grok-4.7` (2026-09-23)
- [x] Feature map + `need=` — `feature_options(model=)` for settings knobs; resolve `best` filters to SKUs that have the job extras (quality over 1.5 for extend). `contract_model_for_need` remaps known SKUs that lack an extra. Dual-write: [Human-TODO.md](../Human-TODO.md) (2026-08-15)
