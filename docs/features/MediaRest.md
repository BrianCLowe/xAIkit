# MediaRest

**Last Updated**: 2026-08-13  
**Related TODO**: [MediaRest-TODO.md](MediaRest-TODO.md)

## Overview

REST modalities on `XaiClient` via `httpx` (not the chat provider): speech-to-text, text-to-speech, and Imagine image generation + edit. Streaming STT (unary-transcribe over WebSocket) and streaming TTS-only (bidirectional TTS over WebSocket) live on this same stem — **not** speech-to-speech.

## Architecture / Contract

- **Owns**: request shape, auth header, empty-input guards, HTTP/WS error mapping, usage modality tags; streaming STT (non-STS) on `wss://api.x.ai/v1/stt`; streaming TTS (non-STS) on `wss://api.x.ai/v1/tts`
- **Does not own**: realtime speech-to-speech (see [RealtimeVoice](RealtimeVoice.md)), video (see [VideoGeneration](VideoGeneration.md)), Files upload (see [ApiCoverage](ApiCoverage.md))
- **Public API**:
  - `transcribe(file_bytes, filename, content_type, language, purpose, …)` → `str`
  - `open_stt_session(...)` → `SttSession` (context manager)
  - `SttSession.send_audio(bytes)`, `finalize()`, `audio_done()`, `recv()`, `events()`, `close()`
  - `synthesize_speech(text, voice_id, language, purpose, …)` → `(bytes, content_type)`
  - `open_tts_session(...)` → `TtsSession` (context manager)
  - `TtsSession.send_text(delta)`, `text_done()`, `text_clear()`, `update_session(replace)`, `recv()`, `events()`, `close()`
  - `decode_tts_audio(event)` — base64 from `audio.delta`
  - `generate_image(prompt, model, aspect_ratio, n, purpose, …)` → `{url, b64_json, model, file_id}`
  - `edit_image(prompt, image url|file_id, …)` → same shape (`file_id` when upstream returns it)

Constants: `XAI_STT_URL` (`https://api.x.ai/v1/stt`), `XAI_STT_WS_URL` (`wss://api.x.ai/v1/stt`), `XAI_TTS_URL` (`https://api.x.ai/v1/tts`), `XAI_TTS_WS_URL` (`wss://api.x.ai/v1/tts`), `XAI_IMAGES_URL`, `XAI_IMAGE_EDITS_URL`, `DEFAULT_TTS_VOICE_ID` (`eve`), `DEFAULT_IMAGE_MODEL` (`grok-imagine-image-quality`). Tests monkeypatch `connect_stt_websocket` / `connect_tts_websocket` (no live socket).

## Behavior (stable)

- STT: POST multipart `file` + `format=true` + `language`; Bearer token; 120s timeout
- Streaming STT: connect `wss://api.x.ai/v1/stt` with query knobs (no setup message); wait for `transcript.created` before sending; client audio is **raw binary** frames (not base64); client JSON `{"type": "finalize"}` and `{"type": "audio.done"}`; server events `transcript.created` / `transcript.partial` / `transcript.done` / `error` (error → `RuntimeError`); empty audio rejected before send
- Query knobs on STT open: `sample_rate` (default 16000), `encoding` (`pcm` \| `mulaw` \| `alaw`), `interim_results`, `endpointing`, `language`, `diarize`, `filler_words`, `multichannel`, `channels`, `keyterm` (repeatable), `smart_turn`, `smart_turn_timeout`, `vad_threshold`
- TTS REST: JSON `{text, voice_id, language}`; Accept audio; strips surrounding whitespace on text
- Streaming TTS: connect `wss://api.x.ai/v1/tts` with query knobs (no setup message); client JSON `{"type": "text.delta", "delta": …}`, `{"type": "text.done"}`, `{"type": "text.clear"}`, optional `{"type": "session.update", "replace": {…}}`; server events `audio.delta` (base64) / `audio.done` / `audio.clear` / `error` (error → `RuntimeError`). Empty text and `text.delta` over 15,000 characters rejected before send. Invalid `codec` / `sample_rate` rejected before connect
- Query knobs on TTS open: `voice` (query `voice=`, default `eve`), `language` (required upstream; kit default `"en"`), `codec` (default `mp3`; `mp3` \| `wav` \| `pcm` \| `mulaw`/`ulaw` \| `alaw`), `sample_rate` (omit unless set; 8000, 16000, 22050, 24000, 44100, 48000), `bit_rate` (omit unless set; MP3), `speed` (omit unless set), `optimize_streaming_latency` (omit unless set), `text_normalization` / `with_timestamps` (omit unless set)
- Image generate: JSON `{model, prompt, n}` with `n` clamped 1–4; `aspect_ratio` omitted when unset; per-call `model` overrides `XaiClient.image_model`
- Image edit: JSON `POST /v1/images/edits` (not OpenAI multipart) with model, prompt, source `image` (`url` + `type=image_url`, or `file_id` passthrough), `n` clamped 1–4; `aspect_ratio` / `response_format` omitted when unset
- Purpose required when metered; success/failure usage with modalities `stt` / `tts` / `imagine`. Streaming STT records once per session (close or first failure) with wall-clock `duration`, `modality="stt"`, `model="stt"`. Streaming TTS records once per session the same way with `modality="tts"`, `model="tts"`, `apply_price_table=False` (no invented USD; REST TTS has no price row). 401 skips the meter then raises
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
| 2026-08-13 | Streaming TTS is `TtsSession` via `open_tts_session` on this stem, not `RealtimeSession` | Distinct upstream socket (`wss://api.x.ai/v1/tts` vs `/v1/realtime`); same home pattern as streaming STT. REST `synthesize_speech` stays. Query `voice=` (not JSON `voice_id`). No default `tts` price row — `apply_price_table=False`. Cite: https://docs.x.ai/developers/model-capabilities/audio/text-to-speech#streaming-tts-websocket |

## Dependencies

| Piece | Relationship |
|-------|--------------|
| [UsageObservability.md](UsageObservability.md) | Optional meter; streaming STT uses `modality="stt"`; streaming TTS uses `modality="tts"` (no USD) |
| [ConnectAuth.md](ConnectAuth.md) | `api_key` on client |
| [RealtimeVoice.md](RealtimeVoice.md) | STS only; do not merge streaming STT or streaming TTS into that session class |

## Acceptance *(library stem)*

- [x] STT/TTS/image URLs, auth, and bodies match client implementation
- [x] Empty input + purpose-when-metered guards
- [x] Image edit / image-to-image (`edit_image`)
- [x] Streaming STT if still unary-transcribe (STS is [RealtimeVoice](RealtimeVoice.md))
- [x] Streaming TTS-only WS (`open_tts_session` / `TtsSession` on `wss://api.x.ai/v1/tts`; not STS)

## Current status

- **Last reconciled with code**: 2026-08-13 (`open_tts_session` + `TtsSession` + mocked WS tests)
