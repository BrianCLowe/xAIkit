# UsageObservability — TODO

**Last Updated**: 2026-08-12  
**Related Spec**: [UsageObservability.md](UsageObservability.md)

---

## Current focus *(session handoff)*

**Active task:** Extend meter modality when video lands.  
**Blocked by:** [VideoGeneration-TODO.md](VideoGeneration-TODO.md)  
**Last session:** 2026-08-12 — bootstrap

---

## High Priority / Next Actions

- [ ] **`modality="video"`** (or imagine-video) on generate/extend/poll — same purpose/labels rules as other media
- [ ] Realtime / files / embed modalities when those methods ship (see [ApiCoverage.md](ApiCoverage.md))

## Medium Priority

- [ ] Price rows for video / newer image models in default table
- [ ] Tokenize helper if we wrap tokenizer API (see ApiCoverage)

## Low Priority / Future Ideas

- [ ] OpenTelemetry export sink

## Completed

- [x] UsageMeter + traces + gaps + mock meter tests (2026-08-12)
