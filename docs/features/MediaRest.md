# MediaRest

**Last Updated**: 2026-08-13  
**Related TODO**: [MediaRest-TODO.md](MediaRest-TODO.md)

## Overview

REST modalities on `XaiClient` via `httpx` (not the chat provider): speech-to-text, text-to-speech, and Imagine image generation + edit.

## Architecture / Contract

- **Owns**: request shape, auth header, empty-input guards, HTTP error mapping, usage modality tags. **Target:** streaming STT (non-STS) on this same REST client
- **Does not own**: realtime WebSocket voice (see [RealtimeVoice](RealtimeVoice.md)), video (see [VideoGeneration](VideoGeneration.md)), Files upload (see [ApiCoverage](ApiCoverage.md))
- **Public API**:
  - `transcribe(file_bytes, filename, content_type, language, purpose, …)` → `str`
  - `synthesize_speech(text, voice_id, language, purpose, …)` → `(bytes, content_type)`
  - `generate_image(prompt, model, aspect_ratio, n, purpose, …)` → `{url, b64_json, model, file_id}`
  - `edit_image(prompt, image url|file_id, …)` → same shape (`file_id` when upstream returns it)

Constants: `XAI_STT_URL`, `XAI_TTS_URL`, `XAI_IMAGES_URL`, `XAI_IMAGE_EDITS_URL`, `DEFAULT_TTS_VOICE_ID` (`eve`), `DEFAULT_IMAGE_MODEL` (`grok-imagine-image-quality`).

## Behavior (stable)

- STT: POST multipart `file` + `format=true` + `language`; Bearer token; 120s timeout
- TTS: JSON `{text, voice_id, language}`; Accept audio; strips surrounding whitespace on text
- Image generate: JSON `{model, prompt, n}` with `n` clamped 1–4; `aspect_ratio` omitted when unset; per-call `model` overrides `XaiClient.image_model`
- Image edit: JSON `POST /v1/images/edits` (not OpenAI multipart) with model, prompt, source `image` (`url` + `type=image_url`, or `file_id` passthrough), `n` clamped 1–4; `aspect_ratio` / `response_format` omitted when unset
- Purpose required when metered; success/failure usage with modalities `stt` / `tts` / `imagine`
- 401 and ≥400 mapped to `RuntimeError`; empty audio/prompt/file/image rejected before HTTP
- Generate/edit surface Imagine `file_output.file_id` (or top-level `file_id`) when present; `file_id` **inputs** need [ApiCoverage](ApiCoverage.md) Files (passthrough only here)
- **Target:** streaming STT if still unary-transcribe (STS is [RealtimeVoice](RealtimeVoice.md))

## Decisions

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-08-12 | REST httpx for media (chat stays SDK provider) | Matches current extract; contract-tested via mocked `httpx.post` |
| 2026-08-12 | Image edit and streaming STT stay on this REST client | Final kit — not a new media SDK ([ApiCoverage](ApiCoverage.md)) |
| 2026-08-13 | Image edit uses JSON `/v1/images/edits`, not multipart | xAI rejects OpenAI-style `multipart/form-data` on this endpoint |

## Dependencies

| Piece | Relationship |
|-------|--------------|
| [UsageObservability.md](UsageObservability.md) | Optional meter |
| [ConnectAuth.md](ConnectAuth.md) | `api_key` on client |

## Acceptance *(library stem)*

- [x] STT/TTS/image URLs, auth, and bodies match client implementation
- [x] Empty input + purpose-when-metered guards
- [x] Image edit / image-to-image (`edit_image`)
- [ ] Streaming STT if still unary-transcribe (STS is [RealtimeVoice](RealtimeVoice.md))

## Current status

- **Last reconciled with code**: 2026-08-13
