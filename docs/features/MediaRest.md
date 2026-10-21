# MediaRest

**Last Updated**: 2026-10-21  
**Related Understanding**: —  

---

**Humans:** This is the contract. How to read it: [`help/SCAFFOLDS.md`](../templates/help/SCAFFOLDS.md) · [`help/USAGE.md`](../templates/help/USAGE.md).

**Agents:** Fill-in blanks — not a tutorial. If context is thin, re-open [`agent/workflow/understanding.md`](../templates/agent/workflow/understanding.md) §2. Catalog: [`agent/workflow/extensions.md`](../templates/agent/workflow/extensions.md) §7.1. Decisions: [`agent/workflow/decisions.md`](../templates/agent/workflow/decisions.md). Operable Acceptance: [`agent/workflow/todos.md`](../templates/agent/workflow/todos.md) §5.3. build-first (no Understanding): [`agent/workflow/profile-standing.md`](../templates/agent/workflow/profile-standing.md) §0.1.

---

## Overview

REST modalities on `XaiClient` via `httpx` (not the chat provider): speech-to-text, text-to-speech, Imagine image generation + edit, and a built-in TTS voice roster. Streaming STT (unary-transcribe over WebSocket) and streaming TTS-only (bidirectional TTS over WebSocket) live on this same stem — **not** speech-to-speech.

Custom `base_url` and `XAI_BASE_URL` for these REST and websocket URLs are specified on [ClientChat](ClientChat.md) (XK-AC-URL-1, XK-AC-URL-2).

## Architecture / Contract

- **Owns**: request shape, auth header, empty-input guards, HTTP/WS error mapping, usage modality tags; streaming STT (non-STS) on `wss://api.x.ai/v1/stt`; streaming TTS (non-STS) on `wss://api.x.ai/v1/tts`; built-in TTS voice roster (`GET /v1/tts/voices`); team custom voices (`/v1/custom-voices`)
- **Does not own**: realtime speech-to-speech (see [RealtimeVoice](RealtimeVoice.md)), video (see [VideoGeneration](VideoGeneration.md)), Files upload (see [ApiCoverage](ApiCoverage.md))
- **Public API**:
  - `transcribe(file_bytes, filename, content_type, language, purpose, …)` → `str`
  - `open_stt_session(...)` → `SttSession` (context manager)
  - `SttSession.send_audio(bytes)`, `finalize()`, `audio_done()`, `recv()`, `events()`, `close()`
  - `synthesize_speech(text, voice_id, language, codec, sample_rate, bit_rate, output_format, speed, optimize_streaming_latency, text_normalization, with_timestamps, replace, purpose, …)` → `(bytes, content_type)`
  - `list_tts_voices(*, purpose, parent_id, labels)` → list of dicts (upstream `voices` array)
  - `get_tts_voice(voice_id, *, purpose, …)` → one voice dict
  - `create_custom_voice(file, *, name, description, gender, accent, age, language, use_case, tone, filename, content_type, purpose, …)` → `CustomVoice`
  - `list_custom_voices(*, limit, pagination_token, purpose, …)` → `CustomVoicePage`
  - `iter_custom_voices(*, limit, pagination_token, purpose, …)` → iterator of `CustomVoice`
  - `get_custom_voice(voice_id, *, purpose, …)` → `CustomVoice`
  - `update_custom_voice(voice_id, *, name, description, gender, accent, age, language, use_case, tone, purpose, …)` → `CustomVoice`
  - `delete_custom_voice(voice_id, *, purpose, …)` → `True`
  - `download_custom_voice_audio(voice_id, *, purpose, …)` → `(bytes, content_type)`
  - `open_tts_session(...)` → `TtsSession` (context manager)
  - `TtsSession.send_text(delta)`, `text_done()`, `text_clear()`, `update_session(replace)`, `recv()`, `events()`, `close()`
  - `decode_tts_audio(event)` — base64 from `audio.delta`
  - `generate_image(prompt, model, aspect_ratio, n, resolution, quality, response_format, purpose, ...)` → `{url, b64_json, model, file_id, images}` (first item on the top-level fields; `images` is every `data` item, in order)
  - `edit_image(prompt, image url|file_id | images sequence, ...)` → same shape (`file_id` when upstream returns it)

Constants: `XAI_STT_URL` (`https://api.x.ai/v1/stt`), `XAI_STT_WS_URL` (`wss://api.x.ai/v1/stt`), `XAI_TTS_URL` (`https://api.x.ai/v1/tts`), `XAI_TTS_VOICES_URL` (`https://api.x.ai/v1/tts/voices`), `XAI_TTS_WS_URL` (`wss://api.x.ai/v1/tts`), `XAI_CUSTOM_VOICES_URL` (`https://api.x.ai/v1/custom-voices`), `XAI_IMAGES_URL`, `XAI_IMAGE_EDITS_URL`, `DEFAULT_TTS_VOICE_ID` (`eve`), `DEFAULT_IMAGE_MODEL` (`grok-imagine-image-quality`). Tests monkeypatch `connect_stt_websocket` / `connect_tts_websocket` (no live socket). Roster tests mock `httpx.get`. Custom voice tests mock `httpx` transports (no live clone).

## Behavior (stable)

- STT: POST multipart `file` + `format=true` + `language`; Bearer token; 120s timeout
- Streaming STT: connect `wss://api.x.ai/v1/stt` with query knobs (no setup message); wait for `transcript.created` before sending; client audio is **raw binary** frames (not base64); client JSON `{"type": "finalize"}` and `{"type": "audio.done"}`; server events `transcript.created` / `transcript.partial` / `transcript.done` / `error` (error → `RuntimeError`); empty audio rejected before send
- Query knobs on STT open: `sample_rate` (default 16000), `encoding` (`pcm` \| `mulaw` \| `alaw`), `interim_results`, `endpointing`, `language`, `diarize`, `filler_words`, `multichannel`, `channels`, `keyterm` (repeatable), `smart_turn`, `smart_turn_timeout`, `vad_threshold`
- TTS REST: JSON `{text, voice_id, language}` plus optional `output_format` `{codec, sample_rate, bit_rate}`, `speed` (0.7–1.5), `optimize_streaming_latency` (`0` / `1` / `2`), `text_normalization`, `with_timestamps`, `replace`. Flat `codec=` / `sample_rate=` / `bit_rate=` match streaming names and nest as `output_format` on the wire (`output_format=` also accepted; flat wins). Unset optional knobs omitted (do not send MP3 24 kHz / 128 kbps defaults). Accept audio; `with_timestamps=True` Accept includes `application/json` and returns the JSON envelope as bytes. Strips surrounding whitespace; empty and **>15,000** chars rejected before HTTP. Invalid `codec` / `sample_rate` / `bit_rate` / `speed` / latency rejected before HTTP (same `TTS_CODECS` / `TTS_SAMPLE_RATES` as streaming; `ulaw` stays the `mulaw` alias). Cite: https://docs.x.ai/developers/model-capabilities/audio/text-to-speech
- TTS voice roster: `GET /v1/tts/voices` with Bearer `api_key`; returns the `voices` array as JSON dicts (`voice_id` / `name` / `language`) as-is. Omitting `voices`, a non-list, an empty list, or any entry that is not an object with a non-blank string `voice_id` (for example `{"voices": [1, 2]}`) raises `RuntimeError` with text `TTS voices response missing voices list`. Optional `GET /v1/tts/voices/{voice_id}` returns one object; empty/blank `voice_id` is rejected before HTTP. Missing key fails before HTTP. Team custom voices are the methods below. A custom `voice_id` still passes through unchanged on TTS `voice_id`, the TTS websocket `voice=` query, and realtime `session.voice`
- Custom voices (XK-CV-AC-1, XK-CV-AC-2, XK-CV-AC-3, XK-CV-AC-4, XK-CV-AC-5, XK-CV-AC-6, XK-CV-AC-7, XK-CV-AC-8, XK-CV-AC-9): sync and async `create_custom_voice`, `list_custom_voices`, `iter_custom_voices`, `get_custom_voice`, `update_custom_voice`, `delete_custom_voice`, `download_custom_voice_audio`. Create is multipart `POST /v1/custom-voices` (file required and non-empty; path, bytes, or binary file object; filename defaults to the path name or `reference.wav`; content type guessed from the filename, with `.wav` as `audio/wav` and `.mp3` as `audio/mpeg`, else `application/octet-stream`). Unset create fields are omitted. List omits `limit` when the caller omits it; `limit` must be an int from 1 to 1000; an empty `voices` list is a valid page. `iter_custom_voices` follows `pagination_token` until it is null. `voice_id` must match `^[a-z0-9]{8}$` before HTTP. PATCH omits fields the caller did not pass, sends JSON null when the caller passes `None`, and rejects an empty string or a call with no fields before HTTP. Delete returns `True` on any 2xx. Download returns `(bytes, content_type)`; a missing `Content-Type` is `application/octet-stream`. Client checks raise `ValueError` before any HTTP call. HTTP status >= 400 raises `CustomVoiceError` (`XaiKitError` and `RuntimeError`) with `status_code` and a server detail truncated to 500 characters and with the API key removed. 403 is passed through with no region or Enterprise rewrite. The client `RetryPolicy` retries GET, PATCH, and DELETE on 500 and transport errors. 4xx is not retried. POST create is never retried. Timeout is 30 seconds, and 120 seconds for create and download. No regional role check. Usage is modality `tts`, `apply_price_table=False`, and `model` set to `custom_voices.create`, `custom_voices.list`, `custom_voices.get`, `custom_voices.update`, `custom_voices.delete`, or `custom_voices.download`. `purpose`, `parent_id`, and `labels` are forwarded. One record per request, including failures. `iter_custom_voices` records one `custom_voices.list` event per page. Cite: https://docs.x.ai/developers/model-capabilities/audio/custom-voices
- Streaming TTS: connect `wss://api.x.ai/v1/tts` with query knobs (no setup message); client JSON `{"type": "text.delta", "delta": …}`, `{"type": "text.done"}`, `{"type": "text.clear"}`, optional `{"type": "session.update", "replace": {…}}`; server events `audio.delta` (base64) / `audio.done` / `audio.clear` / `error` (error → `RuntimeError`). Empty text and `text.delta` over 15,000 characters rejected before send. Invalid `codec` / `sample_rate` rejected before connect
- Query knobs on TTS open: `voice` (query `voice=`, default `eve`), `language` (required upstream; kit default `"en"`), `codec` (default `mp3`; `mp3` \| `wav` \| `pcm` \| `mulaw`/`ulaw` \| `alaw`), `sample_rate` (omit unless set; 8000, 16000, 22050, 24000, 44100, 48000), `bit_rate` (omit unless set; MP3), `speed` (omit unless set), `optimize_streaming_latency` (omit unless set), `text_normalization` / `with_timestamps` (omit unless set)
- Image generate: JSON `{model, prompt, n}` with `n` clamped 1–4; per-call `model` overrides `XaiClient.image_model`. Optional knobs: `aspect_ratio` (Imagine list incl. `auto` / `19.5:9` / `20:9`), `resolution` (`1k` \| `2k`), `response_format` (`b64_json`), `quality` (`low` \| `medium`, **`grok-imagine-image-2.0` only**). Unknown `aspect_ratio` / `resolution` / `quality` are omitted (do not 400). `quality` is omitted on `grok-imagine-image` / `grok-imagine-image-quality` (default pin) even if the caller passed it. Cite: https://docs.x.ai/developers/model-capabilities/images/generation
- Image edit: JSON `POST /v1/images/edits` (not OpenAI multipart) with model, prompt, `n` clamped 1–4; `aspect_ratio` / `response_format` omitted when unset. Unknown `aspect_ratio` omitted (same Imagine list as generate). One source (`image=` / `image_url=` / `image_file_id=`, or a 1-item `images=`) wires `image` (`url` + `type=image_url`, or `file_id`). Two or three sources via `images=` (URL / data URI / `{url|file_id}`, mixable) wire `images` (mutually exclusive with `image`). `>3` or single+`images=` rejected before HTTP. Prompt may refer to `<IMAGE_0>` / `<IMAGE_1>` / `<IMAGE_2>` (not rewritten). Default output aspect follows the first input; `aspect_ratio` overrides. Cite: https://docs.x.ai/developers/model-capabilities/images/multi-image-editing
- Image results (generate and edit, sync and async): every `data` item is returned in order on `images` (`url`, `b64_json`, `file_id`). Top-level `url`, `b64_json`, and `file_id` stay the first item, so a one-image call keeps the previous shape. Meter cost is the per-image rate times the number of images returned, not the `n` requested.
- Purpose required when metered; success/failure usage with modalities `stt` / `tts` / `imagine`. Streaming STT records once per session (close or first failure) with wall-clock `duration`, `modality="stt"`, `model="stt"`. Streaming TTS records once per session the same way with `modality="tts"`, `model="tts"`, `apply_price_table=False` (no invented USD; REST TTS has no price row). Voice roster listing uses the same `tts` modality with `apply_price_table=False` (listing is not billed audio). 401 skips the meter then raises
- Image generation and edit (sync and async) share this path: a 2xx body that is not JSON records one failed event with `modality="imagine"`, then raises `Imagine returned non-JSON response`. The event `error` field is that same text. A 401 records nothing
- STT (`transcribe`), REST TTS (`synthesize_speech`), `list_tts_voices`, and `get_tts_voice` (sync and async): a malformed HTTP 200 records exactly one failed usage event, then raises the existing error text. The event `error` field is that same text. `purpose`, `parent_id`, and `labels` are the values passed in. STT non-JSON raises `STT returned non-JSON response`. STT JSON that is not an object, or an object whose `text` is missing, raises `STT response missing text field`. REST TTS with an empty body raises `TTS returned empty audio`. Roster non-JSON raises `TTS voices returned non-JSON response`. A roster body with no usable `voices` list raises `TTS voices response missing voices list`. `get_tts_voice` non-JSON raises `TTS voice returned non-JSON response`. A non-object voice payload raises `TTS voice returned unexpected payload`. Modality and model are `stt` and `stt` for STT, and `tts` and `tts` for TTS, the roster, and `get_tts_voice`. Roster and `get_tts_voice` pass `apply_price_table=False`. `estimated_usd` stays unset. There is no second success event. A 401 records nothing and raises the existing unauthorized text. HTTP 413 on STT still raises with no record. HTTP 500 still records `HTTP500` once. Transport errors stay on the existing failure record
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
| 2026-08-13 | TTS voice roster is `list_tts_voices` (`GET /v1/tts/voices`); thin `get_tts_voice`; no custom-voices clone | Built-in roster so callers are not stuck on hard-coded `eve`. Custom ids already pass through on TTS/realtime `voice=` / `voice_id=`. Team-scoped clone stays out of kit. Listing meters `modality="tts"` with `apply_price_table=False` |
| 2026-08-14 | Queue Imagine generate + REST TTS knobs; contract per SKU | Audit vs docs: generate missing `resolution`/`quality`/`response_format`; unary TTS missing the streaming set. Same contraction idea as chat `thought_level`. Work on [MediaRest-TODO.md](MediaRest-TODO.md) |
| 2026-08-14 | Imagine generate knobs omit unknown; `quality` only on 2.0 | Official generate set is `resolution`/`quality`/`response_format` plus the Imagine aspect list. Do not 400 on unknown aspect/resolution; contract `quality` off non-2.0 SKUs (`grok-imagine-image`, `grok-imagine-image-quality`). Helpers: `imagine_generate_knobs` in catalog (same idea as `contract_thought_level`) |
| 2026-08-14 | REST unary TTS knobs use streaming names; nest format on the wire | Official unary body uses `output_format`. Callers use the same `codec` / `sample_rate` / `bit_rate` / `speed` / … kwargs as `open_tts_session`. Reject invalid + >15k before HTTP. `with_timestamps=True` returns JSON bytes. Helper: `tts_rest_body` in `tts_stream` (same allowlists as streaming). |
| 2026-08-14 | Multi-image edit: one source wires `image`; 2–3 wire `images` | Official `/v1/images/edits` is JSON `image` **or** `images` (max 3, mixable URL / data URI / `file_id`). Keep single-image kwargs backward compatible. Helper: `_imagine_edit_source_fields` reuses `_imagine_edit_image_ref`. Cite: https://docs.x.ai/developers/model-capabilities/images/multi-image-editing |
| 2026-10-10 | Unusable image generation body records one failed event, then raises | A 2xx non-JSON body on generate or edit is a failed imagine call. The event `error` field is `Imagine returned non-JSON response`, the same text that is raised. 401 still skips the meter. |
| 2026-10-12 | Image calls return every `data` item; cost follows images returned | XK-AC-IMGN-1 / XK-AC-IMGN-2. First-item fields stay so a one-image call keeps the old shape. Count is images returned, not requested `n`. |
| 2026-10-14 | Wrap all six `/v1/custom-voices` endpoints on both clients | XK-CV-AC-1 through XK-CV-AC-9. Multipart create, sentinel PATCH (`None` clears, omit leaves the field out), `CustomVoiceError`, checks before HTTP, create never retried, 30s default and 120s for create and download. Response enums tolerate unknown values. A created `voice_id` is passed through unchanged to TTS, the TTS websocket, and realtime. |
| 2026-10-21 | Malformed STT, REST TTS, and voice-roster 2xx records one failed event, then raises | MM-AC-1 / MM-AC-2. The event `error` is the raised text. A roster entry that is not an object with `voice_id` uses the missing-list error. 401 records nothing. |

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
- [x] Voice roster helper (`list_tts_voices` / `GET /v1/tts/voices`; optional `get_tts_voice`)
- [x] `generate_image` forwards `resolution` / `quality` / `response_format`; `quality` omitted on non-2.0 Imagine SKUs
- [x] REST `synthesize_speech` forwards unary TTS knobs (`output_format`, `speed`, latency opt, normalize, timestamps, `replace`); >15k chars rejected before HTTP
- [x] `edit_image` accepts up to 3 source images
- [x] XK-AC-IMGN-1: sync `generate_image` with n=4 against a response `data` of 4 items returns all 4 urls in order, and the meter records cost equal to 4 times the per-image rate
- [x] XK-AC-IMGN-2: async `generate_image` does the same for the same mock: 4 urls in order and cost equal to 4 times the per-image rate
- [x] XK-AC-DOC-2: `README.md` git-install example and `.github/ISSUE_TEMPLATE/config.yml` say 0.2.0, and neither file contains `0.1.3`
- [x] XK-CV-AC-1: `create_custom_voice` sends one multipart POST with the file and only the fields the caller set
- [x] XK-CV-AC-2: enum, limit, `voice_id`, empty PATCH string, empty file, and missing file checks raise `ValueError` before HTTP
- [x] XK-CV-AC-3: `list_custom_voices` and `iter_custom_voices` paginate; an empty page is valid
- [x] XK-CV-AC-4: get, PATCH (omit vs null), and delete use `/v1/custom-voices/{voice_id}`
- [x] XK-CV-AC-5: `download_custom_voice_audio` returns the original bytes and content type
- [x] XK-CV-AC-6: 400, 401, 403, 404, and 500 raise `CustomVoiceError` with the key removed; retry policy applies; create is not retried
- [x] XK-CV-AC-7: a created `voice_id` passes unchanged to `synthesize_speech`, `open_tts_session`, and `open_realtime_session`
- [x] XK-CV-AC-8: `AsyncXaiClient` matches the sync methods, usage records, and custom `base_url`
- [x] XK-CV-AC-9: `XAI_CUSTOM_VOICES_URL`, `CustomVoice`, `CustomVoicePage`, and `CustomVoiceError` are exported; docs and changelog name these ids
- [x] MM-AC-1: a malformed HTTP 200 from `transcribe`, `synthesize_speech`, `list_tts_voices`, and `get_tts_voice` records one failed event (`error` equals the raised text), then raises, on sync and async
- [x] MM-AC-2: 401 on those calls records nothing; this spec states the malformed 2xx rule

## Visual references

*(none — library stem)*

## Current status

- **Shipped** (library-only): REST STT/TTS (unary knobs + 15k cap) / Imagine (generate knobs + per-SKU `quality` contraction + multi-image edit) + streaming STT/TTS + built-in TTS voice roster + custom voices (`/v1/custom-voices`)
- **Queued**: none on this stem (human extras / knobs look-lists closed 2026-08-16)
- **Last reconciled with code**: 2026-10-21 (malformed media 2xx metering: MM-AC-1, MM-AC-2)
