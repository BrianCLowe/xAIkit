# Catalog

**Last Updated**: 2026-08-13  
**Related TODO**: [Catalog-TODO.md](Catalog-TODO.md)

## Overview

Living model catalog and resolve helpers. Callers pass knobs or inject fixtures — no app settings import.

The same `cheapest` / `economy` / `best` intents run on a **role-filtered** pool (`chat` \| `image` \| `video` \| `voice`). SDK fetch unions language models with image-generation models so those roles are not empty; video/voice rows are tagged by slug when they appear.

## Architecture / Contract

- **Owns**: fetch/cache/list `ModelInfo`; resolve `cheapest` / `economy` / `best` / pin / task hook / bootstrap. `role=` selects the pool
- **Does not own**: billing UI, per-app task names (apps inject `set_task_assignment`)
- **Public API**: `list_models`, `inject_catalog`, `resolve_model`, `resolve_model_selection` (`role=`), `normalize_thought_level`, `normalize_intent`, `effort_options`, `intent_options`, `BOOTSTRAP_MODEL`, `ModelInfo`, `ModelSelection`

Resolve chain: **pin → intent (`cheapest`\|`economy`\|`best`) → task hook → prefer_latest → bootstrap** (`grok-4.6` for chat; image/video/voice use that role’s default slug when the pool is empty). Offline with no key/fixture, `list_models` injects `grok-4.6` plus cheaper-band `grok-4.3`.

`normalize_thought_level`: API `low`\|`high` only; empty/unknown → omit knob.

`intent_options()`: `cheapest`, `economy`, `best`. Overlap is allowed when the lineup is thin. `economy` is the cheaper-than-flagship rung, not a performance-per-dollar optimum.

## Behavior (stable)

- SDK fetch with fallback to empty/offline catalog when allowed
- Fetch unions `list_language_models` + `list_image_generation_models` (best-effort: one list failing does not wipe the others). No video/voice list APIs — tag `grok-imagine-video*` / `grok-voice*` by slug; image-generation rows get capability `image` (or video/voice when the slug says so)
- In-process snapshot + TTL freshness
- Test inject: `inject_catalog`, `set_test_fetch`, `clear_catalog_cache`
- Capability tag `reasoning` comes from slugs that contain `reasoning` after stripping `non-reasoning` / `non_reasoning`
- General **chat** intents skip coding SKUs (`grok-build-*`, `grok-code-*`, `*code-fast*` **id**) unless the catalog is coding-only. Do not match aliases (`grok-4.5` currently aliases `grok-build-latest`). Coding-SKU skip does **not** apply to image/video/voice
- `cheapest`: lowest ranking price. **One price band** → same as `best` (newer is usually more efficient at the same list price). **Multiple bands** → oldest / non-reasoning in the cheapest band
- `best`: newest flagship in the role pool (`prefer_latest`)
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

## Current status

- **In progress**: none
- **Last reconciled with code**: 2026-08-13 (bootstrap `grok-4.6`; offline fallback + `grok-4.3`)
