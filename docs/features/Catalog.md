# Catalog

**Last Updated**: 2026-08-12  
**Related TODO**: [Catalog-TODO.md](Catalog-TODO.md)

## Overview

Living model catalog and resolve helpers. Callers pass knobs or inject fixtures — no app settings import.

## Architecture / Contract

- **Owns**: fetch/cache/list `ModelInfo`; resolve `cheapest` / `economy` / `best` / pin / task hook / bootstrap
- **Does not own**: billing UI, per-app task names (apps inject `set_task_assignment`)
- **Public API**: `list_models`, `inject_catalog`, `resolve_model`, `resolve_model_selection`, `normalize_thought_level`, `normalize_intent`, `effort_options`, `intent_options`, `BOOTSTRAP_MODEL`, `ModelInfo`, `ModelSelection`

Resolve chain: **pin → intent (`cheapest`\|`economy`\|`best`) → task hook → prefer_latest → bootstrap** (`grok-4.5`).

`normalize_thought_level`: API `low`\|`high` only; empty/unknown → omit knob.

`intent_options()`: `cheapest`, `economy`, `best`. Overlap is allowed when the lineup is thin. `economy` is the cheaper-than-flagship rung, not a performance-per-dollar optimum.

## Behavior (stable)

- SDK fetch with fallback to empty/offline catalog when allowed
- In-process snapshot + TTL freshness
- Test inject: `inject_catalog`, `set_test_fetch`, `clear_catalog_cache`
- Capability tag `reasoning` comes from slugs that contain `reasoning` after stripping `non-reasoning` / `non_reasoning`
- General intents skip coding SKUs (`grok-build-*`, `grok-code-*`, `*code-fast*` **id**) unless the catalog is coding-only. Do not match aliases (`grok-4.5` currently aliases `grok-build-latest`).
- `cheapest`: lowest `input_per_million`; ties → oldest, then non-reasoning, then not multi-agent
- `best`: newest general-chat flagship (`prefer_latest`)
- `economy`: newest model in the price band **strictly below** flagship; overlaps `cheapest` or `best` when that band is empty or a single SKU

## Decisions

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-08-12 | Bootstrap model `grok-4.5` | Current default pin when catalog empty |
| 2026-08-12 | Strip `non-reasoning` before tagging `reasoning` | Live catalog slugs like `grok-4.20-0309-non-reasoning` contain the substring `reasoning` |
| 2026-08-12 | Three intents: cheapest / economy / best; overlap OK | Not 4+ named tiers. `economy` not `best_value` — that phrase reads as performance-per-dollar, which can be the flagship. Live 2026-08-12: 4.20-non-reasoning / 4.3 / 4.6 after skipping grok-build |

## Dependencies

| Piece | Relationship |
|-------|--------------|
| [ClientChat.md](ClientChat.md) | `XaiClient` uses resolve when `model` omitted |

## Acceptance *(library stem)*

- [x] Resolve chain documented in module docstring and implemented
- [x] Thought level normalized to API values
- [x] Catalog tests for inject / cheapest / best / unknown intent (gap)
- [x] `non-reasoning` slugs are not tagged `reasoning`
- [x] Three intents with overlap + coding-SKU skip

## Current status

- **In progress**: none
- **Last reconciled with code**: 2026-08-12
