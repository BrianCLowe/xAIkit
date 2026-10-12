# UsageObservability

**Last Updated**: 2026-10-12 *(catalog fill uses the resolved row id; video inbox cancel records video_cancelled with requested duration and resolution; gap fetch only when the shipped table cannot price the call)* 
**Related Understanding**: —  

---

**Humans:** This is the contract. How to read it: [`help/SCAFFOLDS.md`](../templates/help/SCAFFOLDS.md) · [`help/USAGE.md`](../templates/help/USAGE.md).

**Agents:** Fill-in blanks — not a tutorial. If context is thin, re-open [`agent/workflow/understanding.md`](../templates/agent/workflow/understanding.md) §2. Catalog: [`agent/workflow/extensions.md`](../templates/agent/workflow/extensions.md) §7.1. Decisions: [`agent/workflow/decisions.md`](../templates/agent/workflow/decisions.md). Operable Acceptance: [`agent/workflow/todos.md`](../templates/agent/workflow/todos.md) §5.3. build-first (no Understanding): [`agent/workflow/profile-standing.md`](../templates/agent/workflow/profile-standing.md) §0.1.

---

## Overview

Optional, default-off companions: purpose-tagged `UsageMeter`, `CompletionTracer`, and `GapLog`. Pricing estimates via `PriceTable`.

## Architecture / Contract

- **Owns**: event records, sinks (null / memory / jsonl / composite / OpenTelemetry export), rollups, gap scrub
- **Does not own**: dashboards, billing accounts
- **Public API**: `UsageMeter`, sinks (`InMemoryUsageSink`, `JsonlUsageSink`, `CompositeUsageSink`, `OpenTelemetryUsageSink`), `CompletionTracer`, `GapLog`, `build_gap_log`, `xaikit-gaps` CLI, `PriceTable`, `default_price_table`, `load_price_table`, `save_price_table_template`, `PRICE_TABLE_SOURCE_URL`, `PRICE_TABLE_FETCHED`

Purpose is required when a meter is attached to `XaiClient`. Traces and gaps are opt-in.

## Behavior (stable)

- Usage events: purpose, model, tokens, estimated USD, success, thought_level, modality, labels, parent_id
- Modalities used today: `chat`, `stt`, `tts`, `imagine`, `video`, `realtime`, `files`, `embed`, `tokenize`, `batch`, `collections`, `responses`
- Minting a realtime client secret meters purpose/success with `modality="realtime"`; no duration and no USD (not an STS audio-minute; session duration stays on `open_realtime_session` close)
- Streaming TTS sessions use the same `tts` modality as REST `synthesize_speech`; wall-clock `duration` on close; no USD (`apply_price_table=False`)
- TTS voice roster listing (`list_tts_voices` / `get_tts_voice`) uses the same `tts` modality; no USD (`apply_price_table=False`) — listing is not billed audio
- Deferred chat get: 202 pending meters purpose/success **without** tokens (like `get_file`); 200 may record tokens from `usage`; still `modality="chat"`; no invented USD (`apply_price_table=False`). Create is purpose/success only. 401 skips the meter.
- Gap notes scrub secret-ish strings and cap length
- Meter price order: response `cost_in_usd_ticks`, then in-process catalog token and per-image rates, then the shipped table (exact id, or a prefix whose remainder is empty or starts with `-`). The public gap file is fetched only when both leave the price unset, at most once per process per 24 hours. Any exception from that fetch or from payload parsing is a failed refresh, so `UsageMeter.record` keeps the shipped price and does not raise. The shipped table bundles long and cached rates for every gap-file model that publishes them, so an empty catalog prices those tiers offline. A catalog row with input and output rates can still lack long or cached rates. The meter copies each missing field from the shipped table (`default_price_table().price_for`, exact id or a `-` prefix) only when the call needs that field. That lookup uses the resolved catalog row id, then the request model string when the row id is not on the shipped table. It does not fetch for this fill. A prompt of at least 200,000 tokens needs the long input and long output rates. A cached prompt count needs the cached input rate. Both together also need the long cached rate. A value already on the catalog row wins. The gap file is a refresh for an id or rate that neither the catalog nor the shipped table can price. When usage includes a cached prompt count (`cached_tokens`, `cached_prompt_tokens`, or `cached_prompt_text_tokens`) and the price row has a cached input rate, that slice is priced at the cached rate and the rest of `prompt_tokens` at the normal input rate. At 200,000 prompt tokens the long input, long output, and long cached rates apply when they are set. Unknown ids leave `estimated_usd` unset. No fetch on import. Overlay JSON via `load_price_table`; `save_price_table_template` writes the current defaults. Modalities without a public rate skip USD (`apply_price_table=False`). Do not invent a rate.
- Video start, video extend, image generation, and image edit record one failed event when a 2xx body cannot be used (video: not JSON, not an object, or missing `request_id`; image: not JSON), then raise. The event `error` field is the raised message text exactly. A 401 still skips the meter
- **XK-AC-METER-4.** Cancelling a video wait records exactly one video usage event, for both sync and async clients. `VideoInbox.cancel` records `error` `video_cancelled` and `modality` `video`. Usage is the requested duration and resolution (`_video_meter_usage` with no poll payload), the same fields `failed` and `expired` use when the poll body has no duration. `estimated_usd` is the price computed from those fields. xAI may still bill the clip. A second cancel, or a cancel after a terminal state, adds no event. `extend_video` shares this wait. `asyncio.CancelledError` does not record a cancel event, including a direct cancel of the inflight wait task
- Meter/trace failures must not break the user-facing call (logged). `UsageMeter.record` / sink `append` may raise; `XaiClient._record` catches and logs. A public price fetch error does not raise from `record`
- `OpenTelemetryUsageSink` is export-only (optional extra `xaikit-py[otel]` / `opentelemetry-api`; lazy import). Default meter: `opentelemetry.metrics.get_meter("xaikit")`. Counters: `xaikit.usage.calls` (+1) and `xaikit.usage.tokens` (+`total_tokens` when known) with attributes `purpose`, `model`, `modality`, `success` — never prompts/secrets (`error` omitted). `iter_events()` raises `NotImplementedError`; inspect via `CompositeUsageSink(InMemoryUsageSink(), OpenTelemetryUsageSink())` (memory first)

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
| 2026-08-13 | Price table records `source_url` + `fetched`; overlay JSON for operator refresh | Feedback: people will rely on estimates. Cite https://docs.x.ai/developers/pricing. Kit bump or `load_price_table`. Still estimates, not billing. |
| 2026-09-23 | Gap file before the shipped table; no `default` prefix for unknown ids | Ticks, then catalog list rates, then `scripts/data/xai_public_prices.json` (daily watch, fetched at most once a day on a gap), then exact/safe prefix. `grok-4.8` must not bill as `grok-4`. Failure leaves USD unset and does not fail the call. |
| 2026-10-10 | Unusable video start and image generation bodies record one failure | A 2xx body that cannot be used is a failed call. One event, `success` false. The event `error` field is the raised message exactly. 401 stays off the meter. |
| 2026-10-11 | Video inbox cancel records `video_cancelled` with requested duration and resolution | XK-AC-METER-4. Cancelling a video wait records exactly one video usage event, for both sync and async clients. Usage is the requested duration and resolution, and `estimated_usd` is priced from those fields. xAI may still bill the clip. |
| 2026-10-11 | Bundle long and cached rates on the shipped table; catalog fill reads that table | Ruling E. Every gap-file model with a long or cached rate has those fields on `default_price_table`. A partial catalog row copies each missing field the call needs from that table (`price_for`, exact or `-` prefix). The fill does not fetch. Ticks still win. A set catalog field still wins. The gap file stays a refresh source. |
| 2026-10-12 | Catalog fill looks up the resolved row id | An alias or a different case still resolves to the catalog row. The shipped long and cached rates are read with that row id first, then the request model string if the row id is absent. Per-field fill, catalog values, and ticks are unchanged. |
| 2026-10-12 | Fetch the gap file only when the catalog and the shipped table both leave USD unset | The shipped table is authoritative offline for long and cached rates. A price from ticks, the catalog, or the shipped table does not need the network. An id neither table can price still refreshes from the gap file. Any exception from the fetch or payload parse is caught at that call, and `record` does not raise. |

## Dependencies

| Piece | Relationship |
|-------|--------------|
| [ClientChat.md](ClientChat.md) / [MediaRest.md](MediaRest.md) / [VideoGeneration.md](VideoGeneration.md) / [RealtimeVoice.md](RealtimeVoice.md) / [ApiCoverage.md](ApiCoverage.md) Files | Callers record via client hooks |

## Acceptance *(library stem)*

- [x] Meter records by purpose; purpose required when attached
- [x] Stream meters once on completion
- [x] Gap scrub + jsonl CLI
- [x] Video modality on meter when video ships
- [x] XK-AC-METER-4. Cancelling a video wait records exactly one video usage event, for both sync and async clients. Usage is requested duration and resolution, and `estimated_usd` is priced from those fields.
- [x] Realtime-voice modality when realtime ships
- [x] Files modality when Files methods ship
- [x] Embed modality when embed ships
- [x] Tokenize modality when tokenizer ships
- [x] Batch modality when batch ships
- [x] Collections modality when collections ships
- [x] Responses modality when Responses ships
- [x] OpenTelemetry export sink (optional extra; mocked tests; export-only)
- [x] Price table provenance (`source_url` / `fetched`) + overlay refresh path documented
- [x] XK-AC-PRICE-1: after `list_models()`, `UsageMeter.record` for grok-4.7 at 200000 prompt tokens gives 0.8, the same as with an empty catalog after `clear_catalog_cache()`, not 0.4
- [x] XK-AC-PRICE-2: 1M prompt tokens with 400k cached gives the same cost loaded or not loaded, and the exact figure equals the gap-file computation: 2.80, not 2.00
- [x] XK-AC-PRICE-3: UsageMeter.record never raises because the public price fetch failed: on a fetch error it uses the bundled table and the recorded cost equals the bundled-table cost
- [x] XK-AC-PRICE-4: a prompt that needs no long-context or cached fill does not attempt the network fetch at all; fetch calls counted with a fake

## Visual references

*(none — library stem)*

## Current status

- **Last reconciled with code**: 2026-10-12 (catalog fill looks up the resolved row id, then the request model string; XK-AC-METER-4: video inbox cancel records `video_cancelled` with requested duration and resolution; gap fetch only when the catalog and the shipped table both leave USD unset; a fetch error does not raise from record)
