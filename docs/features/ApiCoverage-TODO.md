# ApiCoverage — TODO

**Last Updated**: 2026-08-12  
**Related Spec**: [ApiCoverage.md](ApiCoverage.md)

---

## Current focus *(session handoff)*

**Active task:** Wait for video, then [RealtimeVoice](RealtimeVoice-TODO.md). Remainder has no order.  
**Blocked by:** —  
**Last session:** 2026-08-12 — human ranked realtime voice after video; rest unordered

---

## High Priority / Next Actions

*(none on this stem — video then realtime voice are their own rows.)*

## Medium Priority

*(no order — pick when a caller needs the surface)*

- [ ] Files API (upload) — unblocks video/image `file_id`
- [ ] Chat tools / function calling
- [ ] Vision / multimodal messages
- [ ] Image edit
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

- **library-only.** Do not implement the whole table in one PR.
- Next after video: [RealtimeVoice-TODO.md](RealtimeVoice-TODO.md) (human rank 2026-08-12).
- Remaining rows above: **no order preference**.

## Completed

- [x] Inventory vs `xai_sdk` + public docs (2026-08-12 — this spec)
- [x] Rank remaining API surfaces (2026-08-12 — realtime voice next; rest unordered)
- [x] Split winner into Document Map row (2026-08-12 — RealtimeVoice)
