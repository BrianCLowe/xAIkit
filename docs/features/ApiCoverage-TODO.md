# ApiCoverage — TODO

**Last Updated**: 2026-08-13 *(ClientChat tools / vision / schema)*  
**Related Spec**: [ApiCoverage.md](ApiCoverage.md)

---

## Current focus *(session handoff)*

**Active task:** Remainder unordered — implement against [ApiCoverage.md](ApiCoverage.md); do not invent a second client.  
**Blocked by:** —  
**Last session:** 2026-08-13 — ClientChat extras (tools / vision / `chat_json` schema) homed and shipped

---

## High Priority / Next Actions

*(none on this stem — video then realtime voice are their own rows.)*

## Medium Priority

*(no order — pick when a caller needs the surface; **homes** on [ApiCoverage.md](ApiCoverage.md))*

- [ ] Streaming STT — home: [MediaRest-TODO.md](MediaRest-TODO.md)
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
- [x] Role-filtered catalog (image / video / voice) — home: [Catalog-TODO.md](Catalog-TODO.md) (2026-08-13)
- [x] Image edit — home: [MediaRest-TODO.md](MediaRest-TODO.md) (2026-08-13)
- [x] Files API (upload / `file_id`) — `XaiClient` files helpers; unblocks video/image `file_id` (2026-08-13)
- [x] Chat tools / function calling — home: [ClientChat-TODO.md](ClientChat-TODO.md) (2026-08-13)
- [x] Vision / multimodal messages — home: [ClientChat-TODO.md](ClientChat-TODO.md) (2026-08-13)
- [x] Native structured outputs — home: [ClientChat-TODO.md](ClientChat-TODO.md) (2026-08-13)
