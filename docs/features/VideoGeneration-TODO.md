# VideoGeneration — TODO

**Last Updated**: 2026-08-12  
**Related Spec**: [VideoGeneration.md](VideoGeneration.md)

---

## Current focus *(session handoff)*

**Active task:** Implement video generate (+ poll/extend) on `XaiClient` with mocked contract tests.  
**Blocked by:** —  
**Last session:** 2026-08-12 — human confirmed live xAI key procured (env set up)

*Next agent: read the spec, then High Priority. library-only · exercise path: pytest + optional env-gated smoke (key available).*

---

## High Priority / Next Actions

- [ ] **`generate_video` T2V** — wrap `POST /v1/videos/generations` or `xai_sdk` `client.video.generate`; knobs: model, prompt, duration, aspect_ratio, resolution
- [ ] **Poll / wait** — SDK auto-poll by default; expose request-id path if REST-native
- [ ] **Contract tests** — mocked HTTP or SDK: URL/auth/body, empty prompt, purpose-when-metered, usage modality
- [ ] **Meter + prices** — record video events; add default price rows if we have public rates

## Medium Priority

- [ ] **Image-to-video** — image `url` / `file_id`
- [ ] **Reference-to-video** — `reference_images`, `reference_audios` (`voice_id`)
- [ ] **`extend_video`** — `POST /v1/videos/extensions`

## Low Priority / Future Ideas

- [ ] Download helper for result URL → bytes
- [ ] Catalog: prefer latest imagine-video model

## Cross-Feature Dependencies & Integration Notes

- **library foundation first · exercise path:** `uv run pytest` (mocked). Optional env-gated live smoke unblocked (Human-TODO procure done 2026-08-12) — do not add a UI.
- Files `file_id` may wait on [ApiCoverage-TODO.md](ApiCoverage-TODO.md) Files helpers; ship URL/data-URL I2V first. T2V does not wait on Files.
- After this stem: [RealtimeVoice-TODO.md](RealtimeVoice-TODO.md) (human rank 2026-08-12).

## Completed

*(none — not in tree)*
