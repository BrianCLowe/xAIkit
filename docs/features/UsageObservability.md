# UsageObservability

**Last Updated**: 2026-08-13 *(OpenTelemetryUsageSink optional extra)*  
**Related TODO**: [UsageObservability-TODO.md](UsageObservability-TODO.md)

## Overview

Optional, default-off companions: purpose-tagged `UsageMeter`, `CompletionTracer`, and `GapLog`. Pricing estimates via `PriceTable`.

## Architecture / Contract

- **Owns**: event records, sinks (null / memory / jsonl / composite / OpenTelemetry export), rollups, gap scrub
- **Does not own**: dashboards, billing accounts
- **Public API**: `UsageMeter`, sinks (`InMemoryUsageSink`, `JsonlUsageSink`, `CompositeUsageSink`, `OpenTelemetryUsageSink`), `CompletionTracer`, `GapLog`, `build_gap_log`, `xaikit-gaps` CLI, `default_price_table`

Purpose is required when a meter is attached to `XaiClient`. Traces and gaps are opt-in.

## Behavior (stable)

- Usage events: purpose, model, tokens, estimated USD, success, thought_level, modality, labels, parent_id
- Modalities used today: `chat`, `stt`, `tts`, `imagine`, `video`, `realtime`, `files`, `embed`, `tokenize`, `batch`, `collections`, `responses`
- Minting a realtime client secret meters purpose/success with `modality="realtime"`; no duration and no USD (not an STS audio-minute; session duration stays on `open_realtime_session` close)
- Streaming TTS sessions use the same `tts` modality as REST `synthesize_speech`; wall-clock `duration` on close; no USD (`apply_price_table=False`)
- TTS voice roster listing (`list_tts_voices` / `get_tts_voice`) uses the same `tts` modality; no USD (`apply_price_table=False`) — listing is not billed audio
- Deferred chat get: 202 pending meters purpose/success **without** tokens (like `get_file`); 200 may record tokens from `usage`; still `modality="chat"`; no invented USD (`apply_price_table=False`). Create is purpose/success only. 401 skips the meter.
- Gap notes scrub secret-ish strings and cap length
- Meter/trace failures must not break the user-facing call (logged). `UsageMeter.record` / sink `append` may raise; `XaiClient._record` catches and logs
- `OpenTelemetryUsageSink` is export-only (optional extra `xaikit[otel]` / `opentelemetry-api`; lazy import). Default meter: `opentelemetry.metrics.get_meter("xaikit")`. Counters: `xaikit.usage.calls` (+1) and `xaikit.usage.tokens` (+`total_tokens` when known) with attributes `purpose`, `model`, `modality`, `success` — never prompts/secrets (`error` omitted). `iter_events()` raises `NotImplementedError`; inspect via `CompositeUsageSink(InMemoryUsageSink(), OpenTelemetryUsageSink())` (memory first)

## Decisions

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-08-12 | Opt-in companions, default off | Library-first; apps attach sinks |
| 2026-08-12 | Video prices: `ModelPrice.per_second_usd` (+ optional resolution map); 480p default | Video is billed per second by resolution, not tokens. Public Imagine rates are estimates, not a billing authority |
| 2026-08-13 | Realtime voice: `modality="realtime"`; `ModelPrice.per_minute_usd` | STS is billed per audio minute on the public table ($0.05 / $0.08). Text-input `$0.004` unit is undocumented — not estimated. Estimates, not a billing authority |
| 2026-08-13 | Files: `modality="files"`; no default price row | Upload is metered for purpose/success; public table has no per-file rate to estimate |
| 2026-08-13 | Streaming STT: same `modality="stt"` as REST; default `stt` row `$0.20/hour` (`per_minute_usd`) | Public Voice table Streaming Speech to Text. REST `$0.10/hr` not estimated. Estimates, not billing. Cite: https://docs.x.ai/developers/pricing |
| 2026-08-13 | Embeddings: `modality="embed"`; no default price row | Public table https://docs.x.ai/developers/pricing has no embeddings rate. OpenAPI `prompt_text_token_price` examples conflict (10 vs 100 cents/M) — do not invent USD. Meter purpose/success/tokens; `apply_price_table=False` |
| 2026-08-13 | Tokenizer: `modality="tokenize"`; no default price row | Public table has no tokenizer rate. Meter purpose/success and token count from the token list; `apply_price_table=False` |
| 2026-08-13 | Batch: `modality="batch"`; no default price row | Public table has no batch rate. Meter purpose/success on batch RPCs; `apply_price_table=False` |
| 2026-08-13 | Collections: `modality="collections"`; no default price row | Public table has no collections rate. Meter purpose/success on collection RPCs; `apply_price_table=False` |
| 2026-08-13 | Responses: `modality="responses"`; no default price row | Distinct from `chat`. Public table has no Responses/tools rate. Meter purpose/success/tokens from `input_tokens`/`output_tokens`; `apply_price_table=False` — no invented USD |
| 2026-08-13 | Realtime client-secret mint: purpose/success only | Same `modality="realtime"` as STS. No duration/tokens; `apply_price_table=False` so estimates stay None — minting is not an audio-minute |
| 2026-08-13 | Streaming TTS: same `modality="tts"` as REST; no default price row | Public table has no TTS rate. Session records purpose/success + wall-clock duration; `apply_price_table=False` — no invented USD |
| 2026-08-13 | Deferred chat get 202: purpose/success, no tokens; 200 may record usage tokens; no USD | Same `modality="chat"` as live chat. Pending poll is not a completion. Public priority premium is not estimated. |
| 2026-08-13 | OTel sink is optional extra, export-only counters | Keep wheel on httpx/pydantic/websockets/xai-sdk. Mapping: meter `xaikit`, counters `xaikit.usage.calls` / `xaikit.usage.tokens`, attrs purpose/model/modality/success. Tests mock `opentelemetry.metrics`. `iter_events` not supported — compose with `InMemoryUsageSink`. Sink may raise; client `_record` still protects user calls. |

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
- [x] Tokenize modality when tokenizer ships
- [x] Batch modality when batch ships
- [x] Collections modality when collections ships
- [x] Responses modality when Responses ships
- [x] OpenTelemetry export sink (optional extra; mocked tests; export-only)

## Current status

- **Last reconciled with code**: 2026-08-13 (`OpenTelemetryUsageSink`; optional `otel` extra; mocked meter tests)
