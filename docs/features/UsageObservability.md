# UsageObservability

**Last Updated**: 2026-08-12  
**Related TODO**: [UsageObservability-TODO.md](UsageObservability-TODO.md)

## Overview

Optional, default-off companions: purpose-tagged `UsageMeter`, `CompletionTracer`, and `GapLog`. Pricing estimates via `PriceTable`.

## Architecture / Contract

- **Owns**: event records, sinks (null / memory / jsonl / composite), rollups, gap scrub
- **Does not own**: dashboards, billing accounts
- **Public API**: `UsageMeter`, sinks, `CompletionTracer`, `GapLog`, `build_gap_log`, `xaikit-gaps` CLI, `default_price_table`

Purpose is required when a meter is attached to `XaiClient`. Traces and gaps are opt-in.

## Behavior (stable)

- Usage events: purpose, model, tokens, estimated USD, success, thought_level, modality, labels, parent_id
- Modalities used today: `chat`, `stt`, `tts`, `imagine`
- Gap notes scrub secret-ish strings and cap length
- Meter/trace failures must not break the user-facing call (logged)

## Decisions

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-08-12 | Opt-in companions, default off | Library-first; apps attach sinks |

## Dependencies

| Piece | Relationship |
|-------|--------------|
| [ClientChat.md](ClientChat.md) / [MediaRest.md](MediaRest.md) | Callers record via client hooks |

## Acceptance *(library stem)*

- [x] Meter records by purpose; purpose required when attached
- [x] Stream meters once on completion
- [x] Gap scrub + jsonl CLI
- [ ] Video modality on meter when video ships

## Current status

- **Last reconciled with code**: 2026-08-12
