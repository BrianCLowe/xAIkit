# VideoGeneration — TODO

**Last Updated**: 2026-08-15  
**Related Spec**: [VideoGeneration.md](VideoGeneration.md)

---

## Current focus *(session handoff)*

**Active task:** Stem High drained. Human verify **extras** still open (`extend_video` live look, `reference_audios`, 1080p contraction look).  
**Blocked by:** —  
**Last session:** 2026-08-15 — `poll_video` / `_normalize_video_payload` keep Imagine `error` so `wait=False` + poll matches the wait path.

*library-only · exercise path: `uv run pytest` + optional `XAITKIT_LIVE=1` + `XAITKIT_LIVE_VIDEO=1` start-only smoke. Do not add a UI. Files upload stays on ApiCoverage. Video edits (`POST /v1/videos/edits`) not in this stem.*

---

## High Priority / Next Actions

*(none blocking)*

## Medium Priority

*(none)*

## Low Priority / Future Ideas

*(none — video edits / Files upload / catalog `role=video` live on other stems)*

## Human verify (orchestration 2026-08-12)

### Core — done (consumer proof)

- [x] **2026-08-15 — Live via Reelwright** — `generate_video` (`wait=True` poll) + `download_video`; duration + `aspect_ratio`; R2V `reference_images`. First short had no dialogue, so `reference_audios` was not sent. Outcome: works. Dual-write: [Human-TODO.md](../Human-TODO.md) Done.

### Extras — still open

Library-only look-list — reply in chat when done (do not mark this row yourself).

- **Surfaces still open:** `extend_video`; live `reference_audios` (`voice_id` on a speaking shot); 1080p contraction look (1.5 T2V/I2V keep 1080p; R2V and older `grok-imagine-video` → 720p); README **Video generation** `wait=False` + `poll_video` example
- **Placement:** `src/xaikit/client.py`; constants exported from `xaikit` (`DEFAULT_VIDEO_MODEL`, `XAI_VIDEOS_URL`, …)
- **Copy:** README example uses `VideoInbox` + `into=` + `wait=False` + `poll_video`; default live path is `wait=True`; 1080p is contracted per model/mode
- **Happy path:** `uv run pytest tests/test_video_wiring.py` (offline). Optional live start-only: `XAITKIT_LIVE=1 XAITKIT_LIVE_VIDEO=1 uv run pytest tests/test_live_smoke.py -m live -k video -v` (needs `XAI_API_KEY`; slow/expensive)
- **Rough edges:** live wait can take minutes; `file_id` is passthrough only (Files upload is ApiCoverage); video **edits** are not in this stem; `1080p` stays only on `grok-imagine-video-1.5` T2V/I2V — R2V and older `grok-imagine-video` clamp to `720p`; `extend_video` remaps 1.5 via `need=video_extend` (offline covered; live look still open)

## Cross-Feature Dependencies & Integration Notes

- **library foundation first · exercise path:** `uv run pytest` (mocked). Optional env-gated live video start: `XAITKIT_LIVE=1 XAITKIT_LIVE_VIDEO=1` (not part of default live smokes).
- Files `file_id` upload stays on [ApiCoverage-TODO.md](ApiCoverage-TODO.md); this stem forwards `file_id` on the wire only.
- Capability-aware resolve lives on Catalog (`feature_options` / `need=`). This stem uses it on `extend_video`.
- Next: [RealtimeVoice-TODO.md](RealtimeVoice-TODO.md) (human rank 2026-08-12).

## Completed

- [x] **Durable video start / no silent abandon** — Required `into=` (`VideoInbox` / list / callback). Kit delivers `request_id` as soon as POST is accepted, then the terminal result. Async wait is shielded so sibling `gather` cancel does not void the receipt. `VideoInbox.cancel(request_id)` is the only stop-listening. Offline tests in `tests/test_video_wiring.py`. Cite: 2026-08-15 consumer parallel-job loss (2026-08-15)
- [x] **Resolution contraction** — kit allowlist is `480p`/`720p`/`1080p`. Docs: `1080p` only on `grok-imagine-video-1.5` **T2V / I2V**; **R2V capped at 720p**; older `grok-imagine-video` (no `-1.5`) does not send 1080p. Contract `1080p` → `720p` on those paths. Extend still omits `aspect_ratio` / `resolution`. Offline tests in `tests/test_video_wiring.py`. Cite: https://docs.x.ai/developers/model-capabilities/video/generation (2026-08-14)
- [x] **`generate_video` T2V** — wrap `POST /v1/videos/generations`; knobs: model, prompt, duration, aspect_ratio, resolution (2026-08-12)
- [x] **Poll / wait** — wait-by-default + `poll_video(request_id)` REST path (2026-08-12)
- [x] **Contract tests** — `tests/test_video_wiring.py`: URL/auth/body, empty prompt, purpose-when-metered, usage modality (2026-08-12)
- [x] **Meter + prices** — `modality="video"`; default per-second price rows (2026-08-12)
- [x] **Image-to-video** — image `url` / `file_id` passthrough (2026-08-12)
- [x] **Reference-to-video** — `reference_images`, `reference_audios` (`voice_id`) (2026-08-12)
- [x] **`extend_video`** — `POST /v1/videos/extensions` (2026-08-12)
- [x] Download helper for result URL → bytes (2026-08-12)
- [x] Catalog: prefer latest imagine-video model (`prefer_latest_video_model`; not full `role=video` resolve) (2026-08-12)
- [x] **Contract extend model** — omitted / 1.5 remaps via `contract_model_for_need(..., need="video_extend")` to quality; generate stays 1.5; unknown pins stay. Offline tests in `tests/test_video_wiring.py` + `tests/test_catalog.py`. Cite: 2026-08-15 Reelwright 400 (2026-08-15)
- [x] **`poll_video` keeps `error`** — `_normalize_video_payload` includes `_video_error_message` (nested `error.message`, string `error`, top-level `message`) so `wait=False` + poll matches wait/`VideoReceipt.error`. Offline tests in `tests/test_video_wiring.py`. Cite: 2026-08-15 consumer poll path (2026-08-15)
