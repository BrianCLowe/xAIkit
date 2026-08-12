# VideoGeneration — TODO

**Last Updated**: 2026-08-12  
**Related Spec**: [VideoGeneration.md](VideoGeneration.md)

---

## Current focus *(session handoff)*

**Active task:** Stem shipped (library-only). Next product work is [RealtimeVoice](RealtimeVoice-TODO.md).  
**Blocked by:** —  
**Last session:** 2026-08-12 — shipped T2V / I2V / R2V / extend / poll-wait / download / meter+prices / prefer_latest_video_model with mocked contract tests

*library-only · exercise path: `uv run pytest` + optional `XAITKIT_LIVE=1` + `XAITKIT_LIVE_VIDEO=1` start-only smoke. Do not add a UI. Files upload stays on ApiCoverage. Video edits (`POST /v1/videos/edits`) not in this stem.*

---

## High Priority / Next Actions

*(none — High drained)*

## Medium Priority

*(none — Medium drained)*

## Low Priority / Future Ideas

*(none — Low drained; video edits / Files upload / catalog `role=video` live on other stems)*

## Human verify (orchestration 2026-08-12)

Library-only look-list — reply in chat when done (do not mark this row yourself).

- **Surfaces:** `XaiClient.generate_video` / `extend_video` / `poll_video` / `download_video`; README **Video generation** section
- **Placement:** `src/xaikit/client.py`; constants exported from `xaikit` (`DEFAULT_VIDEO_MODEL`, `XAI_VIDEOS_URL`, …)
- **Copy:** README example uses `wait=False` + `poll_video`; default live path is `wait=True`
- **Happy path:** `uv run pytest tests/test_video_wiring.py` (offline). Optional live start-only: `XAITKIT_LIVE=1 XAITKIT_LIVE_VIDEO=1 uv run pytest tests/test_live_smoke.py -m live -k video -v` (needs `XAI_API_KEY`; slow/expensive)
- **Rough edges:** live wait can take minutes; `file_id` is passthrough only (Files upload is ApiCoverage); video **edits** and catalog `role=video` are not in this stem

## Cross-Feature Dependencies & Integration Notes

- **library foundation first · exercise path:** `uv run pytest` (mocked). Optional env-gated live video start: `XAITKIT_LIVE=1 XAITKIT_LIVE_VIDEO=1` (not part of default live smokes).
- Files `file_id` upload stays on [ApiCoverage-TODO.md](ApiCoverage-TODO.md); this stem forwards `file_id` on the wire only.
- Next: [RealtimeVoice-TODO.md](RealtimeVoice-TODO.md) (human rank 2026-08-12).

## Completed

- [x] **`generate_video` T2V** — wrap `POST /v1/videos/generations`; knobs: model, prompt, duration, aspect_ratio, resolution (2026-08-12)
- [x] **Poll / wait** — wait-by-default + `poll_video(request_id)` REST path (2026-08-12)
- [x] **Contract tests** — `tests/test_video_wiring.py`: URL/auth/body, empty prompt, purpose-when-metered, usage modality (2026-08-12)
- [x] **Meter + prices** — `modality="video"`; default per-second price rows (2026-08-12)
- [x] **Image-to-video** — image `url` / `file_id` passthrough (2026-08-12)
- [x] **Reference-to-video** — `reference_images`, `reference_audios` (`voice_id`) (2026-08-12)
- [x] **`extend_video`** — `POST /v1/videos/extensions` (2026-08-12)
- [x] Download helper for result URL → bytes (2026-08-12)
- [x] Catalog: prefer latest imagine-video model (`prefer_latest_video_model`; not full `role=video` resolve) (2026-08-12)
