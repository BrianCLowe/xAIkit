# xAIkit — Human TODO

**Last Updated**: 2026-08-13  
**Related**: [Master_Index.md](Master_Index.md) · [Tooling.md](Tooling.md)

---

**Your inbox** — everything waiting on a human.

---

## Open

- [ ] **VideoGeneration library look-list** (`playtest`) — 2026-08-12 — Confirm generate/extend/poll/download + README example feel right; optional live start-only smoke if you want. Owner: [VideoGeneration-TODO.md](features/VideoGeneration-TODO.md) · Blocks: none
- [ ] **MediaRest extras look-list** (`playtest`) — 2026-08-13 — Split from fat MediaRest row: `edit_image`, streaming STT/TTS (`open_stt_session` / `open_tts_session`), TTS voice roster. Owner: [MediaRest-TODO.md](features/MediaRest-TODO.md) · Blocks: none
- [ ] **Catalog library look-list** (`playtest`) — 2026-08-13 — `role=`, grok-4.6 bootstrap, persist_path (orchestration). Owner: [Catalog-TODO.md](features/Catalog-TODO.md) · Blocks: none
- [ ] **ClientChat extras look-list** (`playtest`) — 2026-08-13 — Split from fat ClientChat row: tools/vision parts, `service_tier`, `AsyncXaiClient` (Rivenquill did not exercise these). Owner: [ClientChat-TODO.md](features/ClientChat-TODO.md) · Blocks: none
- [ ] **ApiCoverage library look-list** (`playtest`) — 2026-08-13 — Files, embed, tokenize, batch, collections, Responses, deferred chat (orchestration). Owner: [ApiCoverage-TODO.md](features/ApiCoverage-TODO.md) · Blocks: none
- [ ] **UsageObservability library look-list** (`playtest`) — 2026-08-13 — New modalities + optional OTel sink (orchestration). Owner: [UsageObservability-TODO.md](features/UsageObservability-TODO.md) · Blocks: none
- [ ] **ConnectAuth library look-list** (`playtest`) — 2026-08-13 — Caller-supplied OAuth URLs (orchestration). Owner: [ConnectAuth-TODO.md](features/ConnectAuth-TODO.md) · Blocks: none

---

## Done

- [x] **RealtimeVoice library look-list** (`playtest`) — 2026-08-13 — Live via Rivenquill conversation mode: ephemeral mint + browser STS WS + server VAD confirmed working (consumer proof). Kit surfaces exercised: `create_realtime_client_secret` / protocol / realtime session path. Owner: [RealtimeVoice-TODO.md](features/RealtimeVoice-TODO.md)
- [x] **ClientChat core — live via Rivenquill** (`playtest`) — 2026-08-13 — Quill chat + `chat_json`/`schema=` (propose-edits / structured paths) confirmed working in Rivenquill against PyPI `xaikit-py`. Does **not** cover tools/vision/`service_tier`/`AsyncXaiClient` (see Open extras). Owner: [ClientChat-TODO.md](features/ClientChat-TODO.md)
- [x] **MediaRest core — Imagine + unary STT/TTS via Rivenquill** (`playtest`) — 2026-08-13 — `generate_image` (Imagine) + voice chat (`transcribe` → chat → `synthesize_speech`) confirmed in Rivenquill. Does **not** cover `edit_image` / streaming STT/TTS / voice roster (see Open extras). Owner: [MediaRest-TODO.md](features/MediaRest-TODO.md)
- [x] **Confirm Document Map + ship-first prefs** (`decide`) — 2026-08-12 — User confirmed doc shape (map + ship-first). Owner: [Master_Index.md](Master_Index.md)
- [x] **Priority after video** (`decide`) — 2026-08-12 — Next slice is **realtime voice**; remaining API surfaces have no order preference. Owner: [ApiCoverage-TODO.md](features/ApiCoverage-TODO.md) · split: [RealtimeVoice-TODO.md](features/RealtimeVoice-TODO.md)
- [x] **Optional live xAI key for smoke** (`procure`) — 2026-08-12 — Environment set up; key in local env only (not git)
- [x] **Tag `v0.1.0a3`** (`procure`) — 2026-08-13 — Pushed on `a859769`; Publish to PyPI succeeded ([run](https://github.com/BrianCLowe/xAIkit/actions/runs/31733361715)). Live: [xaikit-py 0.1.0a3](https://pypi.org/project/xaikit-py/0.1.0a3/). Owner: this file
- [x] **Tag `v0.1.0a2`** (`procure`) — 2026-08-13 — Pushed on `34835b9`; Publish to PyPI succeeded ([run](https://github.com/BrianCLowe/xAIkit/actions/runs/31730769690)). Live: [xaikit-py 0.1.0a2](https://pypi.org/project/xaikit-py/0.1.0a2/). Owner: this file
- [x] **PyPI pending Trusted Publisher for `xaikit-py`** (`procure`) — 2026-08-13 — Account [BrianCLowe](https://pypi.org/user/BrianCLowe/). Name `xaikit` was too similar to existing `xai-kit`; pending publisher is **`xaikit-py`** (display xAIkit-py). Owner: this file. First upload still needs tag `v0.1.0a1` after the dist name lands on master.

---

## Instructions for Humans

- Work **Open**, then tell the agent in chat so they sync owner TODOs.
- Keep secrets out of git.
- Orchestration look-lists are **library-only** (paths + pytest), not a UI tour. Reply in chat when a row is done.
- Consumer proof (e.g. Rivenquill) can close a **core** slice; leave **extras** open when the fat look-list bundled unused surfaces.

## Instructions for AI Agents

- Dual-write human-gated tasks. Do not mark done from assumptions.
- When a consumer confirms a subset: **split** the Human-TODO row + owner Human verify section (Done = exercised; Open = remainder). Do not close RealtimeVoice from Rivenquill voice chat (that path is REST STT/TTS).
