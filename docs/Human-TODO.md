# xAIkit — Human TODO

**Last Updated**: 2026-08-15  
**Related**: [Master_Index.md](Master_Index.md) · [Tooling.md](Tooling.md)

---

**Your inbox** — everything waiting on a human.

---

## Open

- [ ] **VideoGeneration extras look-list** (`playtest`) — 2026-08-15 — Split from fat video row: `extend_video`; live `reference_audios` on a speaking shot; 1080p contraction look (1.5 T2V/I2V only; R2V/older → 720p); README `wait=False` + `poll_video` example. Owner: [VideoGeneration-TODO.md](features/VideoGeneration-TODO.md) · Blocks: none
- [ ] **MediaRest extras remainder** (`playtest`) — 2026-08-15 — Split from extras row: streaming STT/TTS (`open_stt_session` / `open_tts_session`); `get_tts_voice`. Owner: [MediaRest-TODO.md](features/MediaRest-TODO.md) · Blocks: none
- [ ] **Catalog extras look-list** (`playtest`) — 2026-08-13 — Split from fat Catalog row: `persist_path=` / `save_catalog_snapshot`; `role=video` (Rivenquill has no video job). Owner: [Catalog-TODO.md](features/Catalog-TODO.md) · Blocks: none
- [ ] **ClientChat extras look-list** (`playtest`) — 2026-08-13 — Split from fat ClientChat row: tools/vision parts, `service_tier`, `AsyncXaiClient` (Rivenquill did not exercise these). Owner: [ClientChat-TODO.md](features/ClientChat-TODO.md) · Blocks: none
- [ ] **ApiCoverage library look-list** (`playtest`) — 2026-08-13 — Files, embed, tokenize, batch, collections, Responses, deferred chat (orchestration). Owner: [ApiCoverage-TODO.md](features/ApiCoverage-TODO.md) · Blocks: none
- [ ] **UsageObservability extras look-list** (`playtest`) — 2026-08-15 — Split from fat meter row: `OpenTelemetryUsageSink`; modalities for files / embed / tokenize / batch / collections / responses / realtime mint (orchestration). Owner: [UsageObservability-TODO.md](features/UsageObservability-TODO.md) · Blocks: none
- [ ] **ConnectAuth library look-list** (`playtest`) — 2026-08-13 — Caller-supplied OAuth URLs (orchestration). Owner: [ConnectAuth-TODO.md](features/ConnectAuth-TODO.md) · Blocks: none

---

## Done

- [x] **Model feature map for resolve** (`decide`) — 2026-08-15 — Implement extras list + `need=` on resolve so `best` is best for the job (1.5 is newest video but cannot extend/edit). Settings knobs via `feature_options`. Chat/4.6 tool ids + video extras. Owner: [Catalog-TODO.md](features/Catalog-TODO.md)
- [x] **UsageObservability core — purpose meter + parent_id via Reelwright** (`playtest`) — 2026-08-15 — Live: `UsageMeter` + `InMemoryUsageSink`; purpose tags (`roster.*`, `pipeline.plot` / `board` / `image` / `storyboard` / `video` / `extend`); `parent_id` = short id; `events(parent_id=)` rollup by purpose with estimated USD on the job. Modalities hit: chat, imagine, video, tts roster listing. Does **not** cover OTel or files/embed/tokenize/batch/collections/responses/realtime mint (see Open extras). Owner: [UsageObservability-TODO.md](features/UsageObservability-TODO.md)
- [x] **VideoGeneration core — generate/poll/download via Reelwright** (`playtest`) — 2026-08-15 — Live: `generate_video` (`wait=True` poll) + `download_video`; duration + `aspect_ratio`; R2V `reference_images`. First short had no dialogue, so `reference_audios` was not sent. Does **not** cover `extend_video` or the 1080p contraction look (see Open extras). Owner: [VideoGeneration-TODO.md](features/VideoGeneration-TODO.md)
- [x] **MediaRest extras — TTS roster via Reelwright** (`playtest`) — 2026-08-15 — Live: `list_tts_voices` on the character voice picker (filter by sex). `get_tts_voice` not called. First short had no dialogue, so the picked `voice_id` was not sent as video `reference_audios`. Owner: [MediaRest-TODO.md](features/MediaRest-TODO.md)
- [x] **MediaRest extras — `edit_image` via Reelwright** (`playtest`) — 2026-08-15 — Live: prompt edit of reference art; single source `image_url=` and multi `images=` (data URIs). Does **not** cover streaming STT/TTS or `get_tts_voice` (see Open remainder). Owner: [MediaRest-TODO.md](features/MediaRest-TODO.md)
- [x] **MediaRest knobs — `response_format` + `images=` via Reelwright** (`playtest`) — 2026-08-15 — Live: `generate_image` / `edit_image` with `response_format=b64_json`; `edit_image` `images=` (up to 3). Does **not** cover `resolution`/`quality` or unary TTS knobs (see Open remainder). Owner: [MediaRest-TODO.md](features/MediaRest-TODO.md)
- [x] **Catalog core — role, model, effort via Rivenquill** (`playtest`) — 2026-08-13 — Live: `role=chat` + intent/pin + `thought_level` in the Quill picker; Imagine/voice use admin `best` (`role=image` / `role=voice`). `BOOTSTRAP_MODEL` (`grok-4.6`) is the resolve fallback. Does **not** cover persist snapshot or `role=video` (see Open extras). Owner: [Catalog-TODO.md](features/Catalog-TODO.md)
- [x] **Alert when xAI ships a new model / resolution** (`procure`) — 2026-08-14 — Daily GitHub Action `Watch xAI models` diffs public docs vs `scripts/data/xai_models_watch.json` and opens an issue labeled `xai-models`. Watch the repo's issues (or that label). When it fires: check knobs/families/prices, then `uv run python scripts/watch_xai_models.py --write-baseline` and close the issue. Owner: [Catalog-TODO.md](features/Catalog-TODO.md)
- [x] **RealtimeVoice library look-list** (`playtest`) — 2026-08-13 — Live via Rivenquill conversation mode: ephemeral mint + browser STS WS + server VAD confirmed working (consumer proof). Kit surfaces exercised: `create_realtime_client_secret` / protocol / realtime session path. Owner: [RealtimeVoice-TODO.md](features/RealtimeVoice-TODO.md)
- [x] **ClientChat core — live via Rivenquill** (`playtest`) — 2026-08-13 — Quill chat + `chat_json`/`schema=` (propose-edits / structured paths) confirmed working in Rivenquill against PyPI `xaikit-py`. Does **not** cover tools/vision/`service_tier`/`AsyncXaiClient` (see Open extras). Owner: [ClientChat-TODO.md](features/ClientChat-TODO.md)
- [x] **MediaRest core — Imagine + unary STT/TTS via Rivenquill** (`playtest`) — 2026-08-13 — `generate_image` (Imagine) + voice chat (`transcribe` → chat → `synthesize_speech`) confirmed in Rivenquill. Does **not** cover `edit_image` / streaming STT/TTS / voice roster (see Open extras). Owner: [MediaRest-TODO.md](features/MediaRest-TODO.md)
- [x] **Confirm Document Map + ship-first prefs** (`decide`) — 2026-08-12 — User confirmed doc shape (map + ship-first). Owner: [Master_Index.md](Master_Index.md)
- [x] **Priority after video** (`decide`) — 2026-08-12 — Next slice is **realtime voice**; remaining API surfaces have no order preference. Owner: [ApiCoverage-TODO.md](features/ApiCoverage-TODO.md) · split: [RealtimeVoice-TODO.md](features/RealtimeVoice-TODO.md)
- [x] **Optional live xAI key for smoke** (`procure`) — 2026-08-12 — Environment set up; key in local env only (not git)
- [x] **PyPI pending Trusted Publisher for `xaikit-py`** (`procure`) — 2026-08-13 — Account [BrianCLowe](https://pypi.org/user/BrianCLowe/). Name `xaikit` was too similar to existing `xai-kit`; pending publisher is **`xaikit-py`** (display xAIkit-py). Owner: this file. First upload still needs tag `v0.1.0a1` after the dist name lands on master.

---

## Instructions for Humans

- Work **Open**, then tell the agent in chat so they sync owner TODOs.
- Keep secrets out of git.
- Orchestration look-lists are **library-only** (paths + pytest), not a UI tour. Reply in chat when a row is done.
- Consumer proof (e.g. Rivenquill) can close a **core** slice; leave **extras** open when the fat look-list bundled unused surfaces.

## Instructions for AI Agents

- Dual-write human-gated tasks. Do not mark done from assumptions.
- Do **not** add Open rows for tagging `v*` / “mark the PyPI tag done.” Publish is the tag + Actions; a Done-only follow-up commit is wasted. Existing historical tag rows in Done can stay.
- When a consumer confirms a subset: **split** the Human-TODO row + owner Human verify section (Done = exercised; Open = remainder). Do not close RealtimeVoice from Rivenquill voice chat (that path is REST STT/TTS).
