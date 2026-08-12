# ApiCoverage — TODO

**Last Updated**: 2026-08-12  
**Related Spec**: [ApiCoverage.md](ApiCoverage.md)

---

## Current focus *(session handoff)*

**Active task:** Wait for video slice unless the user ranks a different surface first.  
**Blocked by:** [Human-TODO.md](../Human-TODO.md) — "Priority after video"  
**Last session:** 2026-08-12 — bootstrap inventory from xai-sdk + xAI docs

---

## High Priority / Next Actions

- [ ] **Rank remaining API surfaces** (`decide` — dual-write Human-TODO) — tools, vision, files, realtime voice, batch, collections, embeddings, image edit, responses API, tokenizer
- [ ] After rank: **split the winner into its own Document Map row** (spec + TODO) before implementing

## Medium Priority

- [ ] Files API (upload) — unblocks video/image `file_id`
- [ ] Chat tools / function calling
- [ ] Vision / multimodal messages
- [ ] Image edit
- [ ] Realtime voice (WebSocket)
- [ ] Built-in agent tools / Responses API
- [ ] Batch
- [ ] Collections / documents
- [ ] Embeddings
- [ ] Tokenizer
- [ ] Native structured outputs

## Low Priority / Future Ideas

- [ ] Async client
- [ ] Service tier / deferred APIs

## Cross-Feature Dependencies & Integration Notes

- **Needs a human** (`decide`): Rank remaining API surfaces (see [Human-TODO.md](../Human-TODO.md) — "Priority after video")
- Do not implement the whole table in one PR.

## Completed

- [x] Inventory vs `xai_sdk` + public docs (2026-08-12 — this spec)
