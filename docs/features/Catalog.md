# Catalog

**Last Updated**: 2026-08-15  
**Related TODO**: [Catalog-TODO.md](Catalog-TODO.md)

## Overview

Living model catalog and resolve helpers. Callers pass knobs or inject fixtures — no app settings import.

The same `cheapest` / `economy` / `best` intents run on a **role-filtered** pool (`chat` \| `image` \| `video` \| `voice`). SDK fetch unions language models with image-generation models so those roles are not empty; video/voice rows are tagged by slug when they appear.

## Architecture / Contract

- **Owns**: fetch/cache/list `ModelInfo`; resolve `cheapest` / `economy` / `best` / pin / task hook / bootstrap. `role=` selects the pool
- **Does not own**: billing UI, per-app task names (apps inject `set_task_assignment`)
- **Public API**: `list_models` (`persist_path=`), `save_catalog_snapshot`, `inject_catalog`, `resolve_model` / `resolve_model_selection` (`role=`, `need=`), `normalize_thought_level`, `contract_thought_level`, `contract_model_for_need`, `normalize_intent`, `effort_options` (`model=`), `feature_options` (`model=`), `intent_options`, `BOOTSTRAP_MODEL`, `ModelInfo`, `ModelSelection`

Resolve chain: **pin → need-filter → intent (`cheapest`\|`economy`\|`best`) → task hook → prefer_latest → bootstrap** (`grok-4.6` for chat; image/video/voice use that role’s default slug when the pool is empty). Offline with no key/fixture, `list_models` injects `grok-4.6` plus cheaper-band `grok-4.3`.

`normalize_thought_level`: canonical `low`\|`medium`\|`high`\|`xhigh` (4.6 set). `med`/`mid` → `medium`; `x-high`/`extra`/`max` → `xhigh`; empty/unknown → omit knob. `contract_thought_level(level, model)` clamps to what that family accepts (4.6+/multi-agent pass through; 4.5 `xhigh`→`high`; older reasoners also `medium`→`low`; `*-non-reasoning*` omits). `effort_options(model=)` returns that family's list (empty when none). `grok-4.20` is older than `grok-4.5` — do not treat numeric 20 as “4.6 and later”.

`feature_options(model=)`: extra capabilities (tools + media), not role tags. No model / `grok-4.6`+ chat → `web_search`, `x_search`, `code_execution`, `file_attachments`, `collections_search`, `image_understanding`, `x_video_understanding`, `mcp`. `grok-imagine-video` (quality) → `video_extend`, `video_edit`, `r2v`. `grok-imagine-video-1.5` → `1080p`, `r2v`. Unknown / older → `[]`. `resolve_model(..., need=)` / `need=["video_extend", …]` keeps only SKUs that have every requested extra, then runs cheapest / economy / best on that pool. Pin still wins. Empty need-filtered pool bootstraps a kit-known slug that has the extras (quality for extend, not 1.5).

`intent_options()`: `cheapest`, `economy`, `best`. Overlap is allowed when the lineup is thin. `economy` is the cheaper-than-flagship rung, not a performance-per-dollar optimum.

## Behavior (stable)

- SDK fetch with fallback to empty/offline catalog when allowed
- Fetch unions `list_language_models` + `list_image_generation_models` (best-effort: one list failing does not wipe the others). No video/voice list APIs — tag `grok-imagine-video*` / `grok-voice*` by slug; image-generation rows get capability `image` (or video/voice when the slug says so)
- In-process snapshot + TTL freshness
- Opt-in disk persist: `list_models(..., persist_path=)` writes `{models: [...]}` after a successful SDK fetch (same shape `save_catalog_snapshot` writes). Writes go to a sibling temp file then `os.replace` so a failed write cannot truncate the last good snapshot. No default cwd/home path. Read order when no inject/test-fetch: fresh memory → SDK if key → persist file if present → `fixture_path` → bootstrap. Disk write errors are logged; the live list is still returned. `clear_catalog_cache` is memory-only (does not delete the file)
- Test inject: `inject_catalog`, `set_test_fetch`, `clear_catalog_cache`
- Capability tag `reasoning` comes from slugs that contain `reasoning` after stripping `non-reasoning` / `non_reasoning`
- General **chat** intents skip coding SKUs (`grok-build-*`, `grok-code-*`, `*code-fast*` **id**) unless the catalog is coding-only. Do not match aliases (`grok-4.5` currently aliases `grok-build-latest`). Coding-SKU skip does **not** apply to image/video/voice
- `cheapest`: lowest ranking price. **One price band** → same as `best` (newer is usually more efficient at the same list price). **Multiple bands** → oldest / non-reasoning in the cheapest band
- `best`: newest flagship in the role pool (`prefer_latest`), or newest that satisfies `need=`
- **Feature map:** `feature_options(model=)` for settings knobs; `need=` on resolve so `best` is best **for the job**. 1.5 is newest video but cannot extend/edit — `need="video_extend"` picks quality. Chat extras (4.6): web/X search, code execution, file attachments, collections search, image understanding, X video understanding, remote MCP. Newer SKUs may add tools; older may have fewer. Do not overload `ModelInfo.capabilities` (role tags).
- `economy`: newest model in the price band **strictly below** flagship; overlaps `cheapest` when a cheaper band exists, overlaps `best` when there is only one band
- `resolve_model` / `resolve_model_selection(..., role="image"|"video"|"voice")` use the same rules on that pool (default `role="chat"`)
- Image/video/voice use list price (or public rates from `pricing.py`) when the SDK omits `input_per_million`. Image proto `image_price` is mapped when present

## Decisions

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-08-12 | Bootstrap model `grok-4.5` | Current default pin when catalog empty |
| 2026-08-12 | Strip `non-reasoning` before tagging `reasoning` | Live catalog slugs like `grok-4.20-0309-non-reasoning` contain the substring `reasoning` |
| 2026-08-12 | Three intents: cheapest / economy / best; overlap OK | Not 4+ named tiers. `economy` not `best_value` — that phrase reads as performance-per-dollar, which can be the flagship. Live 2026-08-12: 4.20-non-reasoning / 4.3 / 4.6 after skipping grok-build |
| 2026-08-12 | Single price band → all intents pick flagship | Same list price: older SKU is not cheaper, and newer models are usually more token-efficient. Multi-band cheapest still uses the low band (4.20 vs 4.3 at $12.5 while 4.6 is $20) |
| 2026-08-12 | Catalog intents per role, same three names | Thin image/voice/video lineups; overlap already specified ([ApiCoverage](ApiCoverage.md)) |
| 2026-08-13 | `role=` on resolve; fetch via `list_image_generation_models` | Same three intents on a filtered pool. SDK has no video/voice list APIs — slug-tag those; image proto prices map when present, else public rates |
| 2026-08-13 | Bootstrap `grok-4.6`; offline fallback `grok-4.6` + `grok-4.3` | Public models page (fetched 2026-08-13): chat/code default is Grok 4.6. `grok-3-mini` is off that table — cheap offline row is `grok-4.3` ($1.25 in / $2.50 out under 200k). Cite: https://docs.x.ai/docs/models and https://docs.x.ai/developers/pricing |
| 2026-08-13 | Opt-in `persist_path` only; log-and-continue on write failure | Callers pass a path — kit never writes cwd/home by default. A full disk must not block metering/chat. Cache clear does not delete the snapshot file |
| 2026-08-13 | Persist writes via temp file + `os.replace` | In-place `write_text` would truncate the last good snapshot on a mid-write failure |
| 2026-08-14 | Thought levels are the 4.6 set; contract per model | 4.6 has `low`/`medium`/`high`/`xhigh`. 4.5 has no `xhigh` (API treats it as `high`). Older/unknown reasoners only `low`/`high`. Non-reasoning SKUs omit the knob. `medium` is a real value now (no longer collapsed to `low` on 4.6) |
| 2026-08-15 | Feature map feeds `best`: extras list + `need=` filter | 1.5 looked like best video (newest) but cannot extend/edit. `need=` keeps only SKUs that have the job extras, then cheapest/economy/best. Pin still wins. Settings UIs use `feature_options`. |

## Dependencies

| Piece | Relationship |
|-------|--------------|
| [ClientChat.md](ClientChat.md) | `XaiClient` uses resolve when `model` omitted (chat role) |

## Acceptance *(library stem)*

- [x] Resolve chain documented in module docstring and implemented
- [x] Thought level normalized to API values
- [x] Catalog tests for inject / cheapest / best / unknown intent (gap)
- [x] `non-reasoning` slugs are not tagged `reasoning`
- [x] Three intents with overlap + coding-SKU skip
- [x] Role-filtered catalog (image / video / voice) using the same intents
- [x] Opt-in `persist_path`: SDK write + offline reload of the same JSON; memory cache still wins when fresh; write failure does not fail `list_models`
- [x] `feature_options(model=)` + `resolve_model(need=)` so `best` is best for the job (quality over 1.5 for extend)

## Current status

- **In progress**: none — High / Medium / Low drained. Feature map + `need=` shipped
- **Last reconciled with code**: 2026-08-15 (`feature_options` + resolve `need=`)
