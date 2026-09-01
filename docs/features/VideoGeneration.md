# VideoGeneration

**Last Updated**: 2026-08-31  
**Related TODO**: [VideoGeneration-TODO.md](VideoGeneration-TODO.md)

## Overview

Library-only Imagine **video** on `XaiClient`, matching REST media (image / STT / TTS): typed methods, purpose-tagged metering, offline contract tests (mocked `httpx`). No playground UI. Chat stays on the SDK provider; video is REST.

Upstream: `POST /v1/videos/generations`, `POST /v1/videos/extensions`, `GET /v1/videos/{request_id}`. Default model `grok-imagine-video-1.5`. Video **edits** (`POST /v1/videos/edits`) are out of scope for this stem.

## Architecture / Contract

- **Owns**: text-to-video, image-to-video (URL / `file_id` passthrough), reference-to-video, extend; SDK-style poll-by-default plus a request-id path; required durable receive path (`into=`); usage `modality="video"`
- **Does not own**: video editor UI; Files upload helpers ([ApiCoverage](ApiCoverage.md)); video edits; catalog `role=video` resolve ([Catalog](Catalog.md)); app job runners
- **Public API**:
  - `XaiClient.generate_video(..., into=)` → `POST https://api.x.ai/v1/videos/generations`
  - `XaiClient.extend_video(..., into=)` → `POST https://api.x.ai/v1/videos/extensions`
  - `XaiClient.poll_video(request_id)` → single `GET https://api.x.ai/v1/videos/{request_id}` (no loop)
  - `XaiClient.download_video(url)` → `GET` result URL → `bytes`
  - `VideoInbox` / `VideoReceipt` — app-owned receive path (also accepts a list or callback)
  - Constructor: optional `video_model=` (like `image_model=`)
  - `prefer_latest_video_model(catalog)` — newest `grok-imagine-video*` id from a list; fallback `DEFAULT_VIDEO_MODEL`. Does not change chat resolve.

Constants: `XAI_VIDEOS_URL`, `XAI_VIDEO_EXTENSIONS_URL`, `XAI_VIDEO_STATUS_URL` (`https://api.x.ai/v1/videos/{request_id}`), `DEFAULT_VIDEO_MODEL` (`grok-imagine-video-1.5`).

Knobs forwarded on generate (omit unset optionals): `prompt`, `model`, `duration` (1–15s), `aspect_ratio`, `resolution` (`480p` / `720p` / `1080p`; `1080p` contracted to `720p` unless `grok-imagine-video-1.5` T2V/I2V), `image` (`url` / `file_id` via `image_url=` / `image_file_id=` or a dict), `reference_images`, `reference_audios` (`voice_id`, max 3). `purpose` / `parent_id` / `labels` like other media. Extend never sends `aspect_ratio` / `resolution`.

`extend_video` remaps a known SKU that lacks `video_extend` (omitted model / constructor 1.5 / explicit 1.5) via `contract_model_for_need` → resolve `best` with `need="video_extend"` (quality). Generate stays on 1.5. Unknown pins are left alone. Same extras map as Catalog `feature_options` / `need=`. Video **edits** stay out of this stem.

Return dict (same spirit as `generate_image`): `request_id`, `status`, `url`, `duration`, `model`, `respect_moderation`, `error`. `poll_video` and the wait path share `_normalize_video_payload` so a failed hop keeps the Imagine message (`error.message`, string `error`, or top-level `message`) — not status-only.

## Behavior (stable)

- Empty prompt rejected before HTTP for T2V and R2V; I2V may omit prompt
- Do not send `image` and `reference_images` together (client `ValueError`; upstream would 400)
- `file_id` is passthrough only — no Files upload in this stem
- `into=` is required (`VideoInbox`, list, or callback the app keeps). Omitting it is a `TypeError` so a coding agent must write a receive path. The kit delivers `request_id` as soon as the POST is accepted, then the terminal result (`done` / `failed` / `expired`). A sibling `gather` / `TaskGroup` cancel stops the await, not delivery — async wait is shielded. `VideoInbox.cancel(request_id)` is the only abandon (stop listening; does not abort xAI-side generation). Process death without a persisted id is still unrecoverable.
- Default `wait=True` polls until `done` (timeout ~10 minutes, interval 5s). `wait=False` returns the start payload including `request_id` (already delivered to `into`)
- Wait loop: `pending` → keep going; `done` → return result; `failed` / `expired` → deliver receipt with `error` then `RuntimeError`. `poll_video` is a single GET and returns the same normalized dict (including pending and failed). Failed polls set `error` from the Imagine payload; they do not raise.
- Purpose required when a meter is attached
- Failures record failed usage with `modality="video"`; transport errors are `RuntimeError`
- Offline contract tests assert URL/auth/JSON body without a live key
- `1080p` is sent only for `grok-imagine-video-1.5` T2V/I2V; R2V and older `grok-imagine-video` contract `1080p` → `720p` (do not 400). Unknown resolution still rejected. Extend never sends `aspect_ratio` / `resolution`
- `extend_video` contracts known SKUs missing `video_extend` (1.5 / omitted) to the job’s `best` (`grok-imagine-video`). Generate default stays 1.5. Unknown pins stay.
- Optional live smoke: `XAITKIT_LIVE=1` **and** `XAITKIT_LIVE_VIDEO=1` (start + poll + speaking `reference_audios`; slow/expensive; skipped by default live suite). Extend also needs `XAITKIT_LIVE_VIDEO_FILE_ID`.

## Decisions

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-08-12 | Video is the next modality after current REST image/STT/TTS | User: get video handling in, then remaining API |
| 2026-08-12 | Same library-only verification as other knobs | Mocked wiring tests, not a UI |
| 2026-08-12 | REST `httpx` for video (not the chat SDK provider) | Matches image/STT/TTS; contract-tested via mocked `httpx.post` / `httpx.get` |
| 2026-08-12 | Frozen names: `generate_video`, `extend_video`, `poll_video`, `download_video`; `wait=True` by default | Aligns with xAI SDK poll-by-default plus an explicit request-id path |
| 2026-08-12 | `ModelPrice.per_second_usd` (+ optional resolution map); 480p default | Video is billed per second by resolution, not tokens. Public rates are estimates, not a billing authority |
| 2026-08-14 | Contract 1080p → 720p on unsupported model/mode | Docs: 1080p is 1.5 T2V/I2V only; R2V max 720p; older `grok-imagine-video` has no 1080p. Clamp to 720p (not omit) so the caller still gets HD. Helper: `_contract_video_resolution` next to `_optional_resolution`. |
| 2026-08-15 | Contract extend model via feature map (`need=video_extend`) | 1.5 looked like best video (newest) but cannot extend. Same extras list as Catalog settings knobs; `best` is best for the job. |
| 2026-08-15 | Required `into=` receive path; deliver `request_id` before wait; sibling cancel ≠ abandon | Coding agents will `gather` long waits and lose billed clips unless the signature forces a keep-alive sink. `VideoInbox.cancel` is the only stop-listening. |
| 2026-08-15 | `into=` stays video-only | Video is the expensive wait-after-accept. Do not require a sink on chat / image / unary TTS/STT / embed / files. Deferred chat, batch, and Responses already return an id; only add `into=` if those grow a kit-owned wait loop. |
| 2026-08-15 | `poll_video` keeps `error` | Wait already raised `_video_error_message` and set `VideoReceipt.error`. `wait=False` + poll dropped it in `_normalize_video_payload`, so a failed hop looked like status-only. Same helper now puts `error` on the dict. |

## Dependencies

| Piece | Relationship |
|-------|--------------|
| [MediaRest.md](MediaRest.md) | Pattern for REST + meter |
| [UsageObservability.md](UsageObservability.md) | `modality="video"` + default price rows |
| [ApiCoverage.md](ApiCoverage.md) | Files helpers for `file_id`; URL I2V does not wait |
| [Catalog.md](Catalog.md) | `feature_options` / `need=` / `contract_model_for_need`; `prefer_latest_video_model` is newest-in-role only |

## Acceptance *(library stem)*

- [x] `generate_video` (T2V) forwards model/prompt/duration/aspect/resolution
- [x] I2V / reference images/audio knobs reach the wire (`url` first; `file_id` passthrough)
- [x] Extend + poll (or SDK wait) documented and tested
- [x] Meter purpose + video modality
- [x] Offline contract tests; optional live smoke stays env-gated
- [x] 1080p contracted: `grok-imagine-video-1.5` T2V/I2V only; R2V / older video → 720p
- [x] `extend_video` contracts 1.5 / omitted model to `grok-imagine-video` (generate stays on 1.5)
- [x] Durable start: required `into=`; `request_id` delivered before wait; wait-cancel ≠ abandon unless `inbox.cancel`
- [x] `poll_video` / normalize keep Imagine `error` (wait and poll share the same text)

## Current status

- **Shipped** (library-only): generate / extend / poll / download + meter + default prices + `prefer_latest_video_model` + 1080p per-model/mode contraction + required `into=` / `VideoInbox` + extend-model contraction via `need=video_extend`
- **Queued**: none on this stem (edits / Files stay elsewhere)
- **Last reconciled with code**: 2026-08-15 (`poll_video` keeps Imagine `error`)
