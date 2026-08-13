# MediaRest

**Last Updated**: 2026-08-13  
**Related TODO**: [MediaRest-TODO.md](MediaRest-TODO.md)

## Overview

REST modalities on `XaiClient` via `httpx` (not the chat provider): speech-to-text, text-to-speech, and Imagine image generation + edit. Streaming STT (unary-transcribe over WebSocket, **not** speech-to-speech) lives on this same stem.

## Architecture / Contract

- **Owns**: request shape, auth header, empty-input guards, HTTP/WS error mapping, usage modality tags; streaming STT (non-STS) on `wss://api.x.ai/v1/stt`
- **Does not own**: realtime speech-to-speech (see [RealtimeVoice](RealtimeVoice.md)), video (see [VideoGeneration](VideoGeneration.md)), Files upload (see [ApiCoverage](ApiCoverage.md)), streaming TTS-only WS
- **Public API**:
  - `transcribe(file_bytes, filename, content_type, language, purpose, …)` → `str`
  - `open_stt_session(...)` → `SttSession` (context manager)
  - `SttSession.send_audio(bytes)`, `finalize()`, `audio_done()`, `recv()`, `events()`, `close()`
  - `synthesize_speech(text, voice_id, language, purpose, …)` → `(bytes, content_type)`
  - `generate_image(prompt, model, aspect_ratio, n, purpose, …)` → `{url, b64_json, model, file_id}`
  - `edit_image(prompt, image url|file_id, …)` → same shape (`file_id` when upstream returns it)

Constants: `XAI_STT_URL` (`https://api.x.ai/v1/stt`), `XAI_STT_WS_URL` (`wss://api.x.ai/v1/stt`), `XAI_TTS_URL`, `XAI_IMAGES_URL`, `XAI_IMAGE_EDITS_URL`, `DEFAULT_TTS_VOICE_ID` (`eve`), `DEFAULT_IMAGE_MODEL` (`grok-imagine-image-quality`). Tests monkeypatch `connect_stt_websocket` (no live socket).

## Behavior (stable)

- STT: POST multipart `file` + `format=true` + `language`; Bearer token; 120s timeout
- Streaming STT: connect `wss://api.x.ai/v1/stt` with query knobs (no setup message); wait for `transcript.created` before sending; client audio is **raw binary** frames (not base64); client JSON `{"type": "finalize"}` and `{"type": "audio.done"}`; server events `transcript.created` / `transcript.partial` / `transcript.done` / `error` (error → `RuntimeError`); empty audio rejected before send
- Query knobs on open: `sample_rate` (default 16000), `encoding` (`pcm` \| `mulaw` \| `alaw`), `interim_results`, `endpointing`, `language`, `diarize`, `filler_words`, `multichannel`, `channels`, `keyterm` (repeatable), `smart_turn`, `smart_turn_timeout`, `vad_threshold`
- TTS: JSON `{text, voice_id, language}`; Accept audio; strips surrounding whitespace on text
- Image generate: JSON `{model, prompt, n}` with `n` clamped 1–4; `aspect_ratio` omitted when unset; per-call `model` overrides `XaiClient.image_model`
- Image edit: JSON `POST /v1/images/edits` (not OpenAI multipart) with model, prompt, source `image` (`url` + `type=image_url`, or `file_id` passthrough), `n` clamped 1–4; `aspect_ratio` / `response_format` omitted when unset
- Purpose required when metered; success/failure usage with modalities `stt` / `tts` / `imagine`. Streaming STT records once per session (close or first failure) with wall-clock `duration`, `modality="stt"`, `model="stt"`
- 401 and ≥400 mapped to `RuntimeError`; empty audio/prompt/file/image rejected before HTTP
- Generate/edit surface Imagine `file_output.file_id` (or top-level `file_id`) when present; `file_id` **inputs** need [ApiCoverage](ApiCoverage.md) Files (passthrough only here)

## Decisions

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-08-12 | REST httpx for media (chat stays SDK provider) | Matches current extract; contract-tested via mocked `httpx.post` |
| 2026-08-12 | Image edit and streaming STT stay on this REST client | Final kit — not a new media SDK ([ApiCoverage](ApiCoverage.md)) |
| 2026-08-13 | Image edit uses JSON `/v1/images/edits`, not multipart | xAI rejects OpenAI-style `multipart/form-data` on this endpoint |
| 2026-08-13 | Streaming STT is `SttSession` via `open_stt_session`, not `RealtimeSession` | Distinct upstream socket (`/v1/stt` vs `/v1/realtime`); wrap the documented query+binary protocol |
| 2026-08-13 | Default price row `stt` at `$0.20/hour` (`per_minute_usd = 0.20/60`) for streaming wall-clock estimates | Public Voice table: Speech to Text `$0.20 / hr` (Streaming). REST `$0.10 / hr` is not estimated (unary `transcribe` records no duration). Estimates, not billing. Cite: https://docs.x.ai/developers/pricing |

## Dependencies

| Piece | Relationship |
|-------|--------------|
| [UsageObservability.md](UsageObservability.md) | Optional meter; streaming STT uses `modality="stt"` |
| [ConnectAuth.md](ConnectAuth.md) | `api_key` on client |
| [RealtimeVoice.md](RealtimeVoice.md) | STS only; do not merge streaming STT into that session class |

## Acceptance *(library stem)*

- [x] STT/TTS/image URLs, auth, and bodies match client implementation
- [x] Empty input + purpose-when-metered guards
- [x] Image edit / image-to-image (`edit_image`)
- [x] Streaming STT if still unary-transcribe (STS is [RealtimeVoice](RealtimeVoice.md))

## Current status

- **Last reconciled with code**: 2026-08-13 (`open_stt_session` + `SttSession` + mocked WS tests)
