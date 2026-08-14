# VideoGeneration

**Last Updated**: 2026-08-14  
**Related TODO**: [VideoGeneration-TODO.md](VideoGeneration-TODO.md)

## Overview

Library-only Imagine **video** on `XaiClient`, matching REST media (image / STT / TTS): typed methods, purpose-tagged metering, offline contract tests (mocked `httpx`). No playground UI. Chat stays on the SDK provider; video is REST.

Upstream: `POST /v1/videos/generations`, `POST /v1/videos/extensions`, `GET /v1/videos/{request_id}`. Default model `grok-imagine-video-1.5`. Video **edits** (`POST /v1/videos/edits`) are out of scope for this stem.

## Architecture / Contract

- **Owns**: text-to-video, image-to-video (URL / `file_id` passthrough), reference-to-video, extend; SDK-style poll-by-default plus a request-id path; usage `modality="video"`
- **Does not own**: video editor UI; Files upload helpers ([ApiCoverage](ApiCoverage.md)); video edits; catalog `role=video` resolve ([Catalog](Catalog.md))
- **Public API**:
  - `XaiClient.generate_video(...)` → `POST https://api.x.ai/v1/videos/generations`
  - `XaiClient.extend_video(...)` → `POST https://api.x.ai/v1/videos/extensions`
  - `XaiClient.poll_video(request_id)` → single `GET https://api.x.ai/v1/videos/{request_id}` (no loop)
  - `XaiClient.download_video(url)` → `GET` result URL → `bytes`
  - Constructor: optional `video_model=` (like `image_model=`)
  - `prefer_latest_video_model(catalog)` — newest `grok-imagine-video*` id from a list; fallback `DEFAULT_VIDEO_MODEL`. Does not change chat resolve.

Constants: `XAI_VIDEOS_URL`, `XAI_VIDEO_EXTENSIONS_URL`, `XAI_VIDEO_STATUS_URL` (`https://api.x.ai/v1/videos/{request_id}`), `DEFAULT_VIDEO_MODEL` (`grok-imagine-video-1.5`).

Knobs forwarded on generate (omit unset optionals): `prompt`, `model`, `duration` (1–15s), `aspect_ratio`, `resolution`, `image` (`url` / `file_id` via `image_url=` / `image_file_id=` or a dict), `reference_images`, `reference_audios` (`voice_id`, max 3). `purpose` / `parent_id` / `labels` like other media.

Return dict (same spirit as `generate_image`): `request_id`, `status`, `url`, `duration`, `model`, `respect_moderation`.

## Behavior (stable)

- Empty prompt rejected before HTTP for T2V and R2V; I2V may omit prompt
- Do not send `image` and `reference_images` together (client `ValueError`; upstream would 400)
- `file_id` is passthrough only — no Files upload in this stem
- Default `wait=True` polls until `done` (timeout ~10 minutes, interval 5s). `wait=False` returns the start payload including `request_id`
- Poll statuses: `pending` → keep going; `done` → return result; `failed` / `expired` → `RuntimeError`. `poll_video` is a single GET and returns the payload (including pending)
- Purpose required when a meter is attached
- Failures record failed usage with `modality="video"`; transport errors are `RuntimeError`
- Offline contract tests assert URL/auth/JSON body without a live key
- Optional live start-only smoke: `XAITKIT_LIVE=1` **and** `XAITKIT_LIVE_VIDEO=1` (slow/expensive; skipped by default live suite)

## Decisions

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-08-12 | Video is the next modality after current REST image/STT/TTS | User: get video handling in, then remaining API |
| 2026-08-12 | Same library-only verification as other knobs | Mocked wiring tests, not a UI |
| 2026-08-12 | REST `httpx` for video (not the chat SDK provider) | Matches image/STT/TTS; contract-tested via mocked `httpx.post` / `httpx.get` |
| 2026-08-12 | Frozen names: `generate_video`, `extend_video`, `poll_video`, `download_video`; `wait=True` by default | Aligns with xAI SDK poll-by-default plus an explicit request-id path |
| 2026-08-12 | `ModelPrice.per_second_usd` (+ optional resolution map); 480p default | Video is billed per second by resolution, not tokens. Public rates are estimates, not a billing authority |
| 2026-08-14 | Contract 1080p per model/mode (queued) | Docs: 1080p is 1.5 T2V/I2V only; R2V max 720p. Kit currently allowlists 1080p for every path. [VideoGeneration-TODO.md](VideoGeneration-TODO.md) |

## Dependencies

| Piece | Relationship |
|-------|--------------|
| [MediaRest.md](MediaRest.md) | Pattern for REST + meter |
| [UsageObservability.md](UsageObservability.md) | `modality="video"` + default price rows |
| [ApiCoverage.md](ApiCoverage.md) | Files helpers for `file_id`; URL I2V does not wait |
| [Catalog.md](Catalog.md) | `prefer_latest_video_model` only; full `role=video` resolve stays on Catalog-TODO |

## Acceptance *(library stem)*

- [x] `generate_video` (T2V) forwards model/prompt/duration/aspect/resolution
- [x] I2V / reference images/audio knobs reach the wire (`url` first; `file_id` passthrough)
- [x] Extend + poll (or SDK wait) documented and tested
- [x] Meter purpose + video modality
- [x] Offline contract tests; optional live smoke stays env-gated
- [ ] 1080p contracted: `grok-imagine-video-1.5` T2V/I2V only; R2V / older video → 720p

## Current status

- **Shipped** (library-only): generate / extend / poll / download + meter + default prices + `prefer_latest_video_model`
- **Queued**: 1080p per-model/mode contraction ([VideoGeneration-TODO.md](VideoGeneration-TODO.md))
- **Last reconciled with code**: 2026-08-14 (knob-gap TODO; 1080p still uncontracted)
