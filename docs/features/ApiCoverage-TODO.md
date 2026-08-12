# ApiCoverage — TODO

**Last Updated**: 2026-08-12  
**Related Spec**: [ApiCoverage.md](ApiCoverage.md)

---

## Current focus *(session handoff)*

**Active task:** Target spec locked on [ApiCoverage.md](ApiCoverage.md). Wait for video, then [RealtimeVoice](RealtimeVoice-TODO.md). Remainder unordered — implement against that spec, do not invent a second client.  
**Blocked by:** —  
**Last session:** 2026-08-12 — target kit spec locked (homes + shared rules)

---

## High Priority / Next Actions

*(none on this stem — video then realtime voice are their own rows.)*

## Medium Priority

*(no order — pick when a caller needs the surface; **homes** on [ApiCoverage.md](ApiCoverage.md))*

- [ ] Files API (upload / `file_id`) — `XaiClient` files helpers; unblocks video/image `file_id`
- [ ] Chat tools / function calling — home: [ClientChat-TODO.md](ClientChat-TODO.md)
- [ ] Vision / multimodal messages — home: [ClientChat-TODO.md](ClientChat-TODO.md)
- [ ] Native structured outputs — home: [ClientChat-TODO.md](ClientChat-TODO.md)
- [ ] Image edit — home: [MediaRest-TODO.md](MediaRest-TODO.md)
- [ ] Built-in agent tools / Responses API — additive; do not replace `chat`
- [ ] Batch
- [ ] Collections / documents
- [ ] Embeddings
- [ ] Tokenizer

## Low Priority / Future Ideas

- [ ] Async client
- [ ] Service tier / deferred APIs

## Cross-Feature Dependencies & Integration Notes

- **library-only.** Do not implement the whole table in one PR. Implement against the **target kit** on the spec — no interim second client.
- Next after video: [RealtimeVoice-TODO.md](RealtimeVoice-TODO.md) (human rank 2026-08-12).
- Remaining rows above: **no order preference**.

## Completed

- [x] Inventory vs `xai_sdk` + public docs (2026-08-12 — this spec)
- [x] Rank remaining API surfaces (2026-08-12 — realtime voice next; rest unordered)
- [x] Split winner into Document Map row (2026-08-12 — RealtimeVoice)
- [x] Target kit spec (homes + shared rules) (2026-08-12)
