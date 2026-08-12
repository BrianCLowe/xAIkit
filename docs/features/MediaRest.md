# MediaRest

**Last Updated**: 2026-08-12  
**Related TODO**: [MediaRest-TODO.md](MediaRest-TODO.md)

## Overview

REST modalities on `XaiClient` via `httpx` (not the chat provider): speech-to-text, text-to-speech, and Imagine image generation.

## Architecture / Contract

- **Owns**: request shape, auth header, empty-input guards, HTTP error mapping, usage modality tags. **Target:** image **edit** / i2i and streaming STT (non-STS) on this same REST client
- **Does not own**: realtime WebSocket voice (see [RealtimeVoice](RealtimeVoice.md)), video (see [VideoGeneration](VideoGeneration.md))
- **Public API**:
  - `transcribe(file_bytes, filename, content_type, language, purpose, …)` → `str`
  - `synthesize_speech(text, voice_id, language, purpose, …)` → `(bytes, content_type)`
  - `generate_image(prompt, model, aspect_ratio, n, purpose, …)` → `{url, b64_json, model}`
  - **Target:** `edit_image(prompt, image url|file_id, …)` → same shape (+ `file_id` when upstream returns it)

Constants: `XAI_STT_URL`, `XAI_TTS_URL`, `XAI_IMAGES_URL`, `DEFAULT_TTS_VOICE_ID` (`eve`), `DEFAULT_IMAGE_MODEL` (`grok-imagine-image-quality`).

## Behavior (stable)

- STT: POST multipart `file` + `format=true` + `language`; Bearer token; 120s timeout
- TTS: JSON `{text, voice_id, language}`; Accept audio; strips surrounding whitespace on text
- Image: JSON `{model, prompt, n}` with `n` clamped 1–4; `aspect_ratio` omitted when unset; per-call `model` overrides `XaiClient.image_model`
- Purpose required when metered; success/failure usage with modalities `stt` / `tts` / `imagine`
- 401 and ≥400 mapped to `RuntimeError`; empty audio/prompt/file rejected before HTTP
- **Target:** image edit posts to `/v1/images/edits` (or SDK equivalent) with model, prompt, source image; purpose-when-metered; modality `imagine`
- **Target:** generate/edit may surface Imagine `file_output.file_id` when present; `file_id` inputs need [ApiCoverage](ApiCoverage.md) Files

## Decisions

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-08-12 | REST httpx for media (chat stays SDK provider) | Matches current extract; contract-tested via mocked `httpx.post` |
| 2026-08-12 | Image edit and streaming STT stay on this REST client | Final kit — not a new media SDK ([ApiCoverage](ApiCoverage.md)) |

## Dependencies

| Piece | Relationship |
|-------|--------------|
| [UsageObservability.md](UsageObservability.md) | Optional meter |
| [ConnectAuth.md](ConnectAuth.md) | `api_key` on client |

## Acceptance *(library stem)*

- [x] STT/TTS/image URLs, auth, and bodies match client implementation
- [x] Empty input + purpose-when-metered guards
- [ ] Image edit / image-to-image (`edit_image`)
- [ ] Streaming STT if still unary-transcribe (STS is [RealtimeVoice](RealtimeVoice.md))

## Current status

- **Last reconciled with code**: 2026-08-12
