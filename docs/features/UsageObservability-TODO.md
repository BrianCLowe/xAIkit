# UsageObservability — TODO

**Last Updated**: 2026-08-13 *(OpenTelemetry export sink shipped)*  
**Related Spec**: [UsageObservability.md](UsageObservability.md)

---

## Current focus *(session handoff)*

**Active task:** Stem shipped — High/Medium/Low empty. Human verify look-list is open.  
**Blocked by:** —  
**Last session:** 2026-08-13 — `OpenTelemetryUsageSink` (optional `xaikit[otel]`; counters `xaikit.usage.calls` / `xaikit.usage.tokens`; tests mock OTel)

---

## High Priority / Next Actions

*(none)*

## Medium Priority

*(none)*

## Low Priority / Future Ideas

*(none)*

## Human verify (orchestration 2026-08-13)

Library-only look-list — reply in chat when done (do not mark this row yourself).

- **Surfaces:** `OpenTelemetryUsageSink`; modalities for files/embed/tokenize/batch/collections/responses/realtime mint/tts roster
- **Placement:** `src/xaikit/usage.py`; extra `xaikit[otel]`
- **Copy:** README optional OTel one-liner; counters `xaikit.usage.calls` / `xaikit.usage.tokens`
- **Happy path:** `uv run pytest tests/test_otel_usage_sink.py tests/test_meter_mock.py`
- **Rough edges:** `iter_events()` is export-only; pair with `InMemoryUsageSink`; no invented USD on new modalities

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
