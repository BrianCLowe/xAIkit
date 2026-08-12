# Catalog

**Last Updated**: 2026-08-12  
**Related TODO**: [Catalog-TODO.md](Catalog-TODO.md)

## Overview

Living model catalog and resolve helpers. Callers pass knobs or inject fixtures — no app settings import.

## Architecture / Contract

- **Owns**: fetch/cache/list `ModelInfo`; resolve `cheapest` / `best` / pin / task hook / bootstrap
- **Does not own**: billing UI, per-app task names (apps inject `set_task_assignment`)
- **Public API**: `list_models`, `inject_catalog`, `resolve_model`, `resolve_model_selection`, `normalize_thought_level`, `effort_options`, `BOOTSTRAP_MODEL`, `ModelInfo`, `ModelSelection`

Resolve chain: **pin → intent (`cheapest`\|`best`) → task hook → prefer_latest → bootstrap** (`grok-4.5`).

`normalize_thought_level`: API `low`\|`high` only; empty/unknown → omit knob.

## Behavior (stable)

- SDK fetch with fallback to empty/offline catalog when allowed
- In-process snapshot + TTL freshness
- Test inject: `inject_catalog`, `set_test_fetch`, `clear_catalog_cache`
- Capability tag `reasoning` comes from slugs that contain `reasoning` after stripping `non-reasoning` / `non_reasoning`

## Decisions

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-08-12 | Bootstrap model `grok-4.5` | Current default pin when catalog empty |
| 2026-08-12 | Strip `non-reasoning` before tagging `reasoning` | Live catalog slugs like `grok-4.20-0309-non-reasoning` contain the substring `reasoning` |

## Dependencies

| Piece | Relationship |
|-------|--------------|
| [ClientChat.md](ClientChat.md) | `XaiClient` uses resolve when `model` omitted |

## Acceptance *(library stem)*

- [x] Resolve chain documented in module docstring and implemented
- [x] Thought level normalized to API values
- [x] Catalog tests for inject / cheapest / best / unknown intent (gap)
- [x] `non-reasoning` slugs are not tagged `reasoning`

## Current status

- **In progress**: none
- **Last reconciled with code**: 2026-08-12
