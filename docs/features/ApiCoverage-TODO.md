# ApiCoverage — TODO

**Last Updated**: 2026-08-13 *(Responses API on XaiClient)*  
**Related Spec**: [ApiCoverage.md](ApiCoverage.md)

---

## Current focus *(session handoff)*

**Active task:** Remainder unordered — implement against [ApiCoverage.md](ApiCoverage.md); do not invent a second client.  
**Blocked by:** —  
**Last session:** 2026-08-13 — Responses (`XaiClient.create_response` / `get_response`) + UsageObservability `modality="responses"`; chat stays the paved text path

---

## High Priority / Next Actions

*(none on this stem — video then realtime voice are their own rows.)*

## Medium Priority

*(no order — pick when a caller needs the surface; **homes** on [ApiCoverage.md](ApiCoverage.md))*

*(none)*

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
- [x] Streaming STT — home: [MediaRest-TODO.md](MediaRest-TODO.md) (2026-08-13)
- [x] Embeddings — `XaiClient.embed` REST `/v1/embeddings`; meter `modality="embed"` (2026-08-13)
- [x] Tokenizer — `XaiClient.tokenize` REST `/v1/tokenize-text`; meter `modality="tokenize"` (2026-08-13)
- [x] Batch — `XaiClient` create/add/get/list/cancel/list_results via SDK `call_batch_rpc`; meter `modality="batch"` (2026-08-13)
- [x] Collections / documents — `XaiClient` create/get/list/delete/upload_document/search via SDK `call_collections_rpc`; meter `modality="collections"` (2026-08-13)
- [x] Built-in agent tools / Responses API — `XaiClient.create_response` / `get_response` REST `/v1/responses`; tools opt-in; meter `modality="responses"`; do not replace `chat` (2026-08-13)
