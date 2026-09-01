# MediaRest — TODO

**Last Updated**: 2026-08-31  
**Related Spec**: [MediaRest.md](MediaRest.md)

---

## Current focus *(session handoff)*

**Active task:** —  
**Blocked by:** —  
**Last session:** 2026-08-16 — Tester live knobs remainder green: `generate_image` (`grok-imagine-image-2.0`, `2k`, `quality=medium`) + unary `synthesize_speech` (`wav` / 24 kHz / `speed` / normalize). Dual-write Human-TODO Done. Inbox leftover is REST embed only.

---

## High Priority / Next Actions

*library-only · exercise path: `uv run pytest` (mocked). Same contraction pattern as `contract_thought_level` — do not send knobs a SKU rejects.*

*(none)*

## Medium Priority

*(none)*

## Low Priority / Future Ideas

*(none — vision `detail` already on chat parts; STS `reasoning_effort` stays `high`\|`none` on [RealtimeVoice](RealtimeVoice.md))*

## Human verify (orchestration 2026-08-13)

### Core — done (consumer proof)

- [x] **2026-08-13 — Live via Rivenquill** — Imagine (`generate_image`) + voice conversation (`transcribe` → chat → `synthesize_speech`). Outcome: works. Dual-write: [Human-TODO.md](../Human-TODO.md) Done.  
  Note: Rivenquill voice is **not** STS realtime and **not** streaming STT/TTS sessions.

### Extras — done

- [x] **2026-08-15 — Live via Reelwright** — `edit_image` with a prompt: single source `image_url=` and multi `images=` (data URIs, character refs). Outcome: works. Dual-write: [Human-TODO.md](../Human-TODO.md) Done.
- [x] **2026-08-15 — Live via Reelwright** — `list_tts_voices` on the character voice picker (sex filter). Outcome: works. `get_tts_voice` not called. Dual-write: [Human-TODO.md](../Human-TODO.md) Done.

- [x] **2026-08-16 — Live via xAIkit tester** — `open_stt_session` / `SttSession`; `open_tts_session` / `TtsSession`; `get_tts_voice`. Outcome: works. Dual-write: [Human-TODO.md](../Human-TODO.md) Done.

## Human verify (orchestration 2026-08-14)

### Knobs — done

- [x] **2026-08-15 — Live via Reelwright** — `generate_image` / `edit_image` with `response_format=b64_json`; `edit_image` `images=` (up to 3). Outcome: works. Dual-write: [Human-TODO.md](../Human-TODO.md) Done.

- [x] **2026-08-16 — Live via xAIkit tester** — `generate_image` on `grok-imagine-image-2.0` (`resolution=2k`, `quality=medium`, `response_format=b64_json`); unary `synthesize_speech` (`wav` / 24 kHz / `speed=1.0` / `text_normalization`). Outcome: works. Dual-write: [Human-TODO.md](../Human-TODO.md) Done.

## Cross-Feature Dependencies

- **library-only** — mocked HTTP/WS tests, not a recorder UI. Optional live: unary TTS knobs + `get_tts_voice` on `XAITKIT_LIVE=1`; streaming STT `XAITKIT_LIVE_STT=1`; streaming TTS `XAITKIT_LIVE_TTS=1`; Imagine 2.0 `2k`/`quality=medium` `XAITKIT_LIVE_IMAGE_KNOBS=1`.
- Files upload / `file_id` minting stays on [ApiCoverage-TODO.md](ApiCoverage-TODO.md); this stem forwards `file_id` on the wire and surfaces Imagine `file_output.file_id`.
- STS (`wss://api.x.ai/v1/realtime`) stays on [RealtimeVoice-TODO.md](RealtimeVoice-TODO.md). Streaming TTS-only WS (`wss://api.x.ai/v1/tts`) lives here — same home as streaming STT (`/v1/stt` ≠ `/v1/realtime`).
- Custom-voice clone (`POST /v1/custom-voices`) stays out of kit; opaque custom ids already pass through on TTS/realtime `voice=` / `voice_id=`.
- Video 1080p contraction is done on [VideoGeneration-TODO.md](VideoGeneration-TODO.md), not this stem.

## Completed

- [x] **Multi-image edit** — `edit_image` accepts up to **3** source images (URL / data URI / `file_id`, mixable). One source still wires `image`; 2–3 via `images=` wire `images`. Keep JSON `/v1/images/edits`. Offline tests in `tests/test_media_wiring.py` (+ async twin). (2026-08-14)
- [x] **REST TTS knobs** — `synthesize_speech` forwards the unary docs set: `output_format` (`codec` / `sample_rate` / `bit_rate`), `speed` (0.7–1.5), `optimize_streaming_latency`, `text_normalization`, `with_timestamps`, `replace`. Rejects empty and **>15,000** chars before HTTP. Flat knobs match streaming names and nest as `output_format` on the wire. Offline tests in `tests/test_media_wiring.py` (+ async twin). (2026-08-14)
- [x] **Imagine generate knobs + contraction** — `generate_image` forwards `resolution` (`1k` \| `2k`), `quality` (`low` \| `medium`, **`grok-imagine-image-2.0` only**), `response_format` (`b64_json`). Unknown `aspect_ratio` / `resolution` omitted (Imagine list incl. `auto`, `19.5:9`, `20:9`). `quality` omitted on `grok-imagine-image` / `grok-imagine-image-quality`. Offline tests in `tests/test_media_wiring.py`. (2026-08-14)
- [x] `transcribe` / `synthesize_speech` / `generate_image` (2026-08-12 — in tree)
- [x] Media REST wiring tests (PR #2; 2026-08-12)
- [x] Env-gated live TTS / STT / Imagine smokes (2026-08-12)
- [x] **Image edit / i2i** — `edit_image` per [MediaRest.md](MediaRest.md) (`POST /v1/images/edits` JSON, not multipart) (2026-08-13)
- [x] Surface Imagine `file_output.file_id` on generate/edit when upstream returns it (2026-08-13)
- [x] **Streaming STT** — `XaiClient.open_stt_session` / `SttSession` wrapping `wss://api.x.ai/v1/stt` (unary-transcribe; not STS) (2026-08-13)
- [x] **Streaming TTS** — `XaiClient.open_tts_session` / `TtsSession` wrapping `wss://api.x.ai/v1/tts` (bidirectional TTS; not STS, not REST `synthesize_speech`) (2026-08-13)
- [x] Voice roster helper (list TTS `voice_id`s) instead of hard-coded default only (2026-08-13)
