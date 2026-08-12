# VideoGeneration

**Last Updated**: 2026-08-12  
**Related TODO**: [VideoGeneration-TODO.md](VideoGeneration-TODO.md)

## Overview

**Not shipped.** First planned modality expansion: wrap xAI Imagine **video** the same way the kit wraps chat + image — typed client methods, purpose-tagged metering, offline contract tests (mocked HTTP or SDK), no playground UI.

Upstream (xAI): `POST /v1/videos/generations`, `POST /v1/videos/extensions`, `GET /v1/videos/{request_id}`. SDK: `client.video.generate` / `extend` with polling. Models such as `grok-imagine-video` / `grok-imagine-video-1.5`.

## Architecture / Contract

- **Owns** (planned): text-to-video, image-to-video, reference-to-video, extend; poll or SDK-managed wait; usage `modality` for video
- **Does not own**: video editor UI; Files API as a product (upload lives on [ApiCoverage](ApiCoverage.md) / `XaiClient` files helpers). Video **accepts** `url` or `file_id`; T2V does not wait on Files
- **Public API** (planned, names not frozen): e.g. `XaiClient.generate_video(...)`, `extend_video(...)`, optional `poll_video(request_id)` if we expose REST without hiding poll

Knobs to forward (from current xAI docs): `prompt`, `model`, `duration`, `aspect_ratio`, `resolution`, optional image (`url` / `file_id`), `reference_images`, `reference_audios` (`voice_id`).

Async: generation is long-running; prefer SDK poll-by-default with timeout/interval knobs, plus a manual request-id path for callers who need it.

## Behavior (stable)

*Target — not implemented:*

- Empty prompt rejected for T2V; I2V may omit prompt per upstream
- Purpose required when metered
- Failures record failed usage; do not leave callers without a typed error
- Contract tests assert URL/auth/JSON body (or SDK kwargs) without a live key

## Decisions

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-08-12 | Video is the next modality after current REST image/STT/TTS | User: get video handling in, then remaining API |
| 2026-08-12 | Same library-only verification as other knobs | Mocked wiring tests, not a UI |

## Dependencies

| Piece | Relationship |
|-------|--------------|
| [MediaRest.md](MediaRest.md) | Pattern for REST + meter; image refs may share helpers |
| [UsageObservability.md](UsageObservability.md) | New modality + prices |
| [ApiCoverage.md](ApiCoverage.md) | Files helpers for `file_id`; URL I2V does not wait |

## Acceptance *(library stem — open until shipped)*

- [ ] `generate_video` (T2V) forwards model/prompt/duration/aspect/resolution
- [ ] I2V / reference images/audio knobs reach the wire (`url` first; `file_id` when Files exists)
- [ ] Extend + poll (or SDK wait) documented and tested
- [ ] Meter purpose + video modality
- [ ] Offline contract tests; optional live smoke stays env-gated

## Current status

- **In progress**: spec + TODO only
- **Last reconciled with code**: 2026-08-12 (no video methods in `XaiClient`)
