# UsageObservability — TODO

**Last Updated**: 2026-08-16  
**Related Spec**: [UsageObservability.md](UsageObservability.md)

---

## Current focus *(session handoff)*

**Active task:** — (OTel + unused modalities closed except embed).  
**Blocked by:** —  
**Last session:** 2026-08-16 — Tester: `OpenTelemetryUsageSink` + files/tokenize/batch/collections/responses/realtime mint. Embed modality split (empty team roster).

---

## High Priority / Next Actions

*(none)*

## Medium Priority

*(none)*

## Low Priority / Future Ideas

*(none)*

## Human verify (orchestration 2026-08-13)

### Core — done (consumer proof)

- [x] **2026-08-15 — Live via Reelwright** — `UsageMeter` + `InMemoryUsageSink`; purpose tags (`roster.expand` / `image` / `voice`, `pipeline.plot` / `board` / `image` / `storyboard` / `video` / `extend`); `parent_id` = short id; `events(parent_id=)` rollup by purpose with estimated USD on the job desk. Modalities hit: chat, imagine, video, tts roster listing. Outcome: works. Dual-write: [Human-TODO.md](../Human-TODO.md) Done.

### Extras — done except embed modality

- [x] **2026-08-16 — Live via xAIkit tester** — `OpenTelemetryUsageSink` paired with `InMemoryUsageSink`; modalities files / tokenize / batch / collections / responses / realtime mint. Outcome: works. Dual-write: [Human-TODO.md](../Human-TODO.md) Done (embed split).

### Embed modality — still open

Library look-list — reply in chat when done (do not mark this row yourself). Same inbox row as ApiCoverage embed. Dual-write: [Human-TODO.md](../Human-TODO.md) Open.

- **Surfaces:** `modality="embed"` on a live `embed` call
- **Placement:** `src/xaikit/usage.py` (already records; blocked on team SKU)
- **Copy:** no invented USD
- **Happy path:** after embed live works, confirm the meter event
- **Rough edges:** 2026-08-16 roster empty

## Cross-Feature Dependencies & Integration Notes

- Tokenizer helper shipped with [ApiCoverage-TODO.md](ApiCoverage-TODO.md) (`XaiClient.tokenize`).
- Batch methods shipped with [ApiCoverage-TODO.md](ApiCoverage-TODO.md) (`XaiClient.create_batch` / `add_batch_requests` / `get_batch` / `list_batch_results`).
- Collections methods shipped with [ApiCoverage-TODO.md](ApiCoverage-TODO.md) (`XaiClient.create_collection` / `upload_document` / `search_collections`).
- Responses methods shipped with [ApiCoverage-TODO.md](ApiCoverage-TODO.md) (`XaiClient.create_response` / `get_response`).

## Completed

- [x] UsageMeter + traces + gaps + mock meter tests (2026-08-12)
- [x] **`modality="video"`** on generate/extend/poll-wait — same purpose/labels rules as other media (2026-08-12)
- [x] Price rows for video in default table (`per_second_usd` + resolution map; 480p default) (2026-08-12)
- [x] **`modality="realtime"`** on open/close realtime session — same purpose/labels rules (2026-08-13)
- [x] Price rows for realtime voice in default table (`per_minute_usd`; public STS audio-minute rates) (2026-08-13)
- [x] **`modality="files"`** on upload/get/delete — same purpose/labels rules (2026-08-13)
- [x] Default `stt` price row `$0.20/hour` (`per_minute_usd`) for streaming wall-clock estimates (2026-08-13)
- [x] **`modality="embed"`** on `embed` — same purpose/labels/success rules; no invented USD (2026-08-13)
- [x] Tokenize helper if we wrap tokenizer API — `modality="tokenize"` on `tokenize`; no invented USD (2026-08-13)
- [x] **`modality="batch"`** on create/add/get/list/cancel/list_results — same purpose/labels/success rules; no invented USD (2026-08-13)
- [x] **`modality="collections"`** on create/get/list/delete/upload_document/search — same purpose/labels/success rules; no invented USD (2026-08-13)
- [x] **`modality="responses"`** on create_response/get_response — same purpose/labels/success rules; no invented USD (2026-08-13)
- [x] Realtime client-secret mint — purpose/success, `modality="realtime"`, no duration/USD (`apply_price_table=False`) (2026-08-13)
- [x] OpenTelemetry export sink (2026-08-13)
- [x] Price table provenance (`source_url` / `fetched`) + overlay template (2026-08-13)
- [x] **2026-08-15 — Live via Reelwright** — purpose + `parent_id` meter; `InMemoryUsageSink`; USD rollup by purpose. Dual-write: [Human-TODO.md](../Human-TODO.md) Done.
