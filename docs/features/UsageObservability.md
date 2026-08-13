# UsageObservability

**Last Updated**: 2026-08-13 *(embeddings `embed` modality)*  
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
- Modalities used today: `chat`, `stt`, `tts`, `imagine`, `video`, `realtime`, `files`, `embed`
- Gap notes scrub secret-ish strings and cap length
- Meter/trace failures must not break the user-facing call (logged)

## Decisions

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-08-12 | Opt-in companions, default off | Library-first; apps attach sinks |
| 2026-08-12 | Video prices: `ModelPrice.per_second_usd` (+ optional resolution map); 480p default | Video is billed per second by resolution, not tokens. Public Imagine rates are estimates, not a billing authority |
| 2026-08-13 | Realtime voice: `modality="realtime"`; `ModelPrice.per_minute_usd` | STS is billed per audio minute on the public table ($0.05 / $0.08). Text-input `$0.004` unit is undocumented — not estimated. Estimates, not a billing authority |
| 2026-08-13 | Files: `modality="files"`; no default price row | Upload is metered for purpose/success; public table has no per-file rate to estimate |
| 2026-08-13 | Streaming STT: same `modality="stt"` as REST; default `stt` row `$0.20/hour` (`per_minute_usd`) | Public Voice table Streaming Speech to Text. REST `$0.10/hr` not estimated. Estimates, not billing. Cite: https://docs.x.ai/developers/pricing |
| 2026-08-13 | Embeddings: `modality="embed"`; no default price row | Public table https://docs.x.ai/developers/pricing has no embeddings rate. OpenAPI `prompt_text_token_price` examples conflict (10 vs 100 cents/M) — do not invent USD. Meter purpose/success/tokens; `apply_price_table=False` |

## Dependencies

| Piece | Relationship |
|-------|--------------|
| [ClientChat.md](ClientChat.md) / [MediaRest.md](MediaRest.md) / [VideoGeneration.md](VideoGeneration.md) / [RealtimeVoice.md](RealtimeVoice.md) / [ApiCoverage.md](ApiCoverage.md) Files | Callers record via client hooks |

## Acceptance *(library stem)*

- [x] Meter records by purpose; purpose required when attached
- [x] Stream meters once on completion
- [x] Gap scrub + jsonl CLI
- [x] Video modality on meter when video ships
- [x] Realtime-voice modality when realtime ships
- [x] Files modality when Files methods ship
- [x] Embed modality when embed ships

## Current status

- **Last reconciled with code**: 2026-08-13 (`modality="embed"`; no default embed price row)
