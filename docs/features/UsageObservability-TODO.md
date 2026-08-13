# UsageObservability — TODO

**Last Updated**: 2026-08-13 *(responses modality)*  
**Related Spec**: [UsageObservability.md](UsageObservability.md)

---

## Current focus *(session handoff)*

**Active task:** OpenTelemetry export sink (Low).  
**Blocked by:** —  
**Last session:** 2026-08-13 — `modality="responses"` on `XaiClient.create_response` / `get_response`; no default USD row (public table has no Responses/tools rate)

---

## High Priority / Next Actions

*(none)*

## Medium Priority

*(none)*

## Low Priority / Future Ideas

- [ ] OpenTelemetry export sink

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
