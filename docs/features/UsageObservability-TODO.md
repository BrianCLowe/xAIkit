# UsageObservability — TODO

**Last Updated**: 2026-08-13 *(files modality on upload/get/delete)*  
**Related Spec**: [UsageObservability.md](UsageObservability.md)

---

## Current focus *(session handoff)*

**Active task:** Embed modality when embed ships.  
**Blocked by:** [ApiCoverage-TODO.md](ApiCoverage-TODO.md)  
**Last session:** 2026-08-13 — Files `modality="files"` landed with ApiCoverage Files helpers; embed still open

---

## High Priority / Next Actions

- [ ] Embed modality when embed ships (see [ApiCoverage.md](ApiCoverage.md))

## Medium Priority

- [ ] Tokenize helper if we wrap tokenizer API (see ApiCoverage)

## Low Priority / Future Ideas

- [ ] OpenTelemetry export sink

## Completed

- [x] UsageMeter + traces + gaps + mock meter tests (2026-08-12)
- [x] **`modality="video"`** on generate/extend/poll-wait — same purpose/labels rules as other media (2026-08-12)
- [x] Price rows for video in default table (`per_second_usd` + resolution map; 480p default) (2026-08-12)
- [x] **`modality="realtime"`** on open/close realtime session — same purpose/labels rules (2026-08-13)
- [x] Price rows for realtime voice in default table (`per_minute_usd`; public STS audio-minute rates) (2026-08-13)
- [x] **`modality="files"`** on upload/get/delete — same purpose/labels rules (2026-08-13)
