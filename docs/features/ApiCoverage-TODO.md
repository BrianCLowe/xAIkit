# ApiCoverage — TODO

**Last Updated**: 2026-08-31  
**Related Spec**: [ApiCoverage.md](ApiCoverage.md)

---

## Current focus *(session handoff)*

**Active task:** Embed live playtest blocked on team roster. Collections search-lag helper still open.  
**Blocked by:** —  
**Last session:** 2026-08-16 — Batch remaps 4.6/4.5 via `need=batch`. Embed README no longer treats `v1` as a live pin. Collections search-lag documented (no wait/retry yet).

---

## High Priority / Next Actions

*(none blocking)*

## Medium Priority

- [ ] **Collections search lag helper** — Create/upload on the management key can succeed while inference `search_collections` 404s until the id is visible/indexed. Kit documents the two keys and the lag; it does not wait/retry. Optional helper later — do not invent a long poll this turn. Cite: tester live 2026-08-16.

## Low Priority / Future Ideas

*(none)*

## Cross-Feature Dependencies & Integration Notes

- **library-only.** Inventory slices shipped on this stem or homes; do not invent a second client. Optional live smokes: files / tokenize / Responses / deferred on `XAITKIT_LIVE=1`; batch `XAITKIT_LIVE_BATCH=1`; collections `XAITKIT_LIVE_COLLECTIONS=1` + `XAI_MANAGEMENT_KEY` (search is one-shot — no kit retry).
- Human rank after video was realtime voice (2026-08-12); that stem is shipped.

## Human verify (orchestration 2026-08-13)

### Library look-list — done except embed

- [x] **2026-08-16 — Live via xAIkit tester** — Files upload/get/delete; `tokenize`; batch create/add/get (`model=grok-4.3` — 4.6/4.5 rejected); collections create/upload/search (management key + inference search; new id can 404 until visible); `create_response` / `get_response`; `create_deferred_chat` / `get_deferred_chat`. `AsyncXaiClient` closed on [ClientChat-TODO.md](ClientChat-TODO.md). Outcome: works. Dual-write: [Human-TODO.md](../Human-TODO.md) Done (embed split).

### Embed — still open

Library look-list — reply in chat when done (do not mark this row yourself). Dual-write: [Human-TODO.md](../Human-TODO.md) Open.

- **Surfaces:** live `embed` (`POST /v1/embeddings`)
- **Placement:** `src/xaikit/client.py`; README Embeddings (`model=` required; OpenAPI example `v1`)
- **Copy:** callers should list `GET /v1/embedding-models`; `v1` is an example id, not a guaranteed live SKU. Collections index (`grok-embedding-small`) is not this endpoint.
- **Happy path:** `uv run pytest tests/test_embed_wiring.py`. Live: team roster non-empty then `client.embed(..., model=<id>)`.
- **Rough edges:** 2026-08-16 tester team roster empty; 404 is team access, not a bad wrap. No invented USD.

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
- [x] Service tier / deferred APIs — `service_tier` on chat + `create_response`; `create_deferred_chat` / `get_deferred_chat` REST; covering [ClientChat-TODO.md](ClientChat-TODO.md) (2026-08-13)
- [x] Async client — `AsyncXaiClient` same-name twin of the full sync surface; covering [ClientChat-TODO.md](ClientChat-TODO.md) (2026-08-13)
- [x] **Batch model contract** — omitted / 4.6 / 4.5 remap via `need=batch` to `grok-4.3`; unknown pins stay. README + offline tests. Cite: tester live 2026-08-16 (2026-08-16)
- [x] **Embed docs: `v1` is not a live pin** — README/spec say list `GET /v1/embedding-models`; no kit default. Live playtest still open until the team roster has a SKU. (2026-08-16)
