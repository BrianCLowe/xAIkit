# UsageObservability — TODO

**Last Updated**: 2026-08-12  
**Related Spec**: [UsageObservability.md](UsageObservability.md)

---

## Current focus *(session handoff)*

**Active task:** Realtime / files / embed modalities when those methods ship.  
**Blocked by:** [RealtimeVoice-TODO.md](RealtimeVoice-TODO.md) / [ApiCoverage-TODO.md](ApiCoverage-TODO.md)  
**Last session:** 2026-08-12 — video modality + per-second price rows landed with VideoGeneration

---

## High Priority / Next Actions

- [ ] Realtime / files / embed modalities when those methods ship (see [ApiCoverage.md](ApiCoverage.md) / [RealtimeVoice.md](RealtimeVoice.md))

## Medium Priority

- [ ] Tokenize helper if we wrap tokenizer API (see ApiCoverage)

## Low Priority / Future Ideas

- [ ] OpenTelemetry export sink

## Completed

- [x] UsageMeter + traces + gaps + mock meter tests (2026-08-12)
- [x] **`modality="video"`** on generate/extend/poll-wait — same purpose/labels rules as other media (2026-08-12)
- [x] Price rows for video in default table (`per_second_usd` + resolution map; 480p default) (2026-08-12)
