# xAIkit — Human TODO

**Last Updated**: 2026-08-13  
**Related**: [Master_Index.md](Master_Index.md) · [Tooling.md](Tooling.md)

---

**Your inbox** — everything waiting on a human.

---

## Open

- [ ] **Tag `v0.1.0a2` after the version bump is on master** (`procure`) — 2026-08-13 — PyPI still serves `0.1.0a1` (no Issues pointer). After [#39](https://github.com/BrianCLowe/xAIkit/pull/39) is on master:

  ```bash
  git checkout master && git pull
  git tag v0.1.0a2
  git push origin v0.1.0a2
  ```

  That is what runs **Publish to PyPI**. Do not retag `v0.1.0a1`. Owner: this file. Blocks: none
- [ ] **GitHub About + topics** (`procure`) — 2026-08-13 — Cloud Agents cannot write repo settings. On the repo homepage, click the gear next to **About** (or Settings → General). Paste:

  - **Description:** `Unofficial Python kit for the xAI (Grok) API — typed client, catalog, usage metering, media, and realtime voice. Not a multi-provider SDK.`
  - **Website:** `https://pypi.org/project/xaikit-py/`
  - **Topics** (paste as tags): `python`, `grok`, `grok-api`, `llm`, `sdk`, `generative-ai`, `python-sdk`, `text-to-speech`, `speech-to-text`, `image-generation`, `video-generation`
  - **Do not** add topic `xai` — on GitHub that tag is mostly explainable-AI, the same collision as PyPI `xai-kit`. Prefer `grok` / `grok-api`.

  PyPI summary/keywords are already in `pyproject.toml` (next publish). Owner: this file. Blocks: none
- [ ] **VideoGeneration library look-list** (`playtest`) — 2026-08-12 — Confirm generate/extend/poll/download + README example feel right; optional live start-only smoke if you want. Owner: [VideoGeneration-TODO.md](features/VideoGeneration-TODO.md) · Blocks: none
- [ ] **RealtimeVoice library look-list** (`playtest`) — 2026-08-13 — Session + ephemeral mint + custom `voice=` (orchestration). Owner: [RealtimeVoice-TODO.md](features/RealtimeVoice-TODO.md) · Blocks: none
- [ ] **MediaRest library look-list** (`playtest`) — 2026-08-13 — Image edit, streaming STT/TTS, voice roster (orchestration). Owner: [MediaRest-TODO.md](features/MediaRest-TODO.md) · Blocks: none
- [ ] **Catalog library look-list** (`playtest`) — 2026-08-13 — `role=`, grok-4.6 bootstrap, persist_path (orchestration). Owner: [Catalog-TODO.md](features/Catalog-TODO.md) · Blocks: none
- [ ] **ClientChat library look-list** (`playtest`) — 2026-08-13 — Tools/vision/schema, service_tier, AsyncXaiClient (orchestration). Owner: [ClientChat-TODO.md](features/ClientChat-TODO.md) · Blocks: none
- [ ] **ApiCoverage library look-list** (`playtest`) — 2026-08-13 — Files, embed, tokenize, batch, collections, Responses, deferred chat (orchestration). Owner: [ApiCoverage-TODO.md](features/ApiCoverage-TODO.md) · Blocks: none
- [ ] **UsageObservability library look-list** (`playtest`) — 2026-08-13 — New modalities + optional OTel sink (orchestration). Owner: [UsageObservability-TODO.md](features/UsageObservability-TODO.md) · Blocks: none
- [ ] **ConnectAuth library look-list** (`playtest`) — 2026-08-13 — Caller-supplied OAuth URLs (orchestration). Owner: [ConnectAuth-TODO.md](features/ConnectAuth-TODO.md) · Blocks: none

---

## Done

- [x] **Confirm Document Map + ship-first prefs** (`decide`) — 2026-08-12 — User confirmed doc shape (map + ship-first). Owner: [Master_Index.md](Master_Index.md)
- [x] **Priority after video** (`decide`) — 2026-08-12 — Next slice is **realtime voice**; remaining API surfaces have no order preference. Owner: [ApiCoverage-TODO.md](features/ApiCoverage-TODO.md) · split: [RealtimeVoice-TODO.md](features/RealtimeVoice-TODO.md)
- [x] **Optional live xAI key for smoke** (`procure`) — 2026-08-12 — Environment set up; key in local env only (not git)
- [x] **PyPI pending Trusted Publisher for `xaikit-py`** (`procure`) — 2026-08-13 — Account [BrianCLowe](https://pypi.org/user/BrianCLowe/). Name `xaikit` was too similar to existing `xai-kit`; pending publisher is **`xaikit-py`** (display xAIkit-py). Owner: this file. First upload still needs tag `v0.1.0a1` after the dist name lands on master.

---

## Instructions for Humans

- Work **Open**, then tell the agent in chat so they sync owner TODOs.
- Keep secrets out of git.
- Orchestration look-lists are **library-only** (paths + pytest), not a UI tour. Reply in chat when a row is done.

## Instructions for AI Agents

- Dual-write human-gated tasks. Do not mark done from assumptions.
