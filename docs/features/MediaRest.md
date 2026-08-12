# MediaRest

**Last Updated**: 2026-08-12  
**Related TODO**: [MediaRest-TODO.md](MediaRest-TODO.md)

## Overview

REST modalities on `XaiClient` via `httpx` (not the chat provider): speech-to-text, text-to-speech, and Imagine image generation.

## Architecture / Contract

- **Owns**: request shape, auth header, empty-input guards, HTTP error mapping, usage modality tags
- **Does not own**: realtime WebSocket voice (see [RealtimeVoice](RealtimeVoice.md)), image **edit**, video (see [VideoGeneration](VideoGeneration.md))
- **Public API**:
  - `transcribe(file_bytes, filename, content_type, language, purpose, …)` → `str`
  - `synthesize_speech(text, voice_id, language, purpose, …)` → `(bytes, content_type)`
  - `generate_image(prompt, model, aspect_ratio, n, purpose, …)` → `{url, b64_json, model}`

Constants: `XAI_STT_URL`, `XAI_TTS_URL`, `XAI_IMAGES_URL`, `DEFAULT_TTS_VOICE_ID` (`eve`), `DEFAULT_IMAGE_MODEL` (`grok-imagine-image-quality`).

## Behavior (stable)

- STT: POST multipart `file` + `format=true` + `language`; Bearer token; 120s timeout
- TTS: JSON `{text, voice_id, language}`; Accept audio; strips surrounding whitespace on text
- Image: JSON `{model, prompt, n}` with `n` clamped 1–4; `aspect_ratio` omitted when unset; per-call `model` overrides `XaiClient.image_model`
- Purpose required when metered; success/failure usage with modalities `stt` / `tts` / `imagine`
- 401 and ≥400 mapped to `RuntimeError`; empty audio/prompt/file rejected before HTTP

## Decisions

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-08-12 | REST httpx for media (chat stays SDK provider) | Matches current extract; contract-tested via mocked `httpx.post` |

## Dependencies

| Piece | Relationship |
|-------|--------------|
| [UsageObservability.md](UsageObservability.md) | Optional meter |
| [ConnectAuth.md](ConnectAuth.md) | `api_key` on client |

## Acceptance *(library stem)*

- [x] STT/TTS/image URLs, auth, and bodies match client implementation
- [x] Empty input + purpose-when-metered guards
- [ ] Streaming STT / realtime voice ([RealtimeVoice](RealtimeVoice.md) / ApiCoverage)
- [ ] Image edit / image-to-image (ApiCoverage)

## Current status

- **Last reconciled with code**: 2026-08-12
