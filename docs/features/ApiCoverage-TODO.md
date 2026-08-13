# ApiCoverage — TODO

**Last Updated**: 2026-08-13 *(async client twin)*  
**Related Spec**: [ApiCoverage.md](ApiCoverage.md)

---

## Current focus *(session handoff)*

**Active task:** Target kit Low drained. Human verify look-list is open. Spec Acceptance still has two process-guard lines (each implemented slice matches home; no silent wrap-the-SDK).  
**Blocked by:** —  
**Last session:** 2026-08-13 — Async twin `AsyncXaiClient` (same method names; REST `httpx.AsyncClient`; WS `connect_*_websocket_async`; live chat `xai_sdk.AsyncClient`); covering [ClientChat-TODO.md](ClientChat-TODO.md)

---

## High Priority / Next Actions

*(none on this stem — video then realtime voice are their own rows.)*

## Medium Priority

*(no order — pick when a caller needs the surface; **homes** on [ApiCoverage.md](ApiCoverage.md))*

*(none)*

## Low Priority / Future Ideas

*(none)*

## Cross-Feature Dependencies & Integration Notes

- **library-only.** Inventory slices shipped on this stem or homes; do not invent a second client.
- Human rank after video was realtime voice (2026-08-12); that stem is shipped.

## Human verify (orchestration 2026-08-13)

Library-only look-list — reply in chat when done (do not mark this row yourself).

- **Surfaces:** Files; `embed`; `tokenize`; batch; collections; `create_response` / `get_response`; `create_deferred_chat` / `get_deferred_chat`; `AsyncXaiClient`
- **Placement:** `src/xaikit/client.py`, `async_client.py`; README sections for each
- **Copy:** Responses tools are opt-in; `get_response` does not re-count tokens; deferred GET 202 is `{status: "pending"}`
- **Happy path:** `uv run pytest tests/test_files_wiring.py tests/test_embed_wiring.py tests/test_tokenize_wiring.py tests/test_batch_wiring.py tests/test_collections_wiring.py tests/test_responses_wiring.py tests/test_deferred_chat_wiring.py tests/test_async_client_wiring.py`
- **Rough edges:** collections management uses `XAI_MANAGEMENT_KEY`; no invented USD on these modalities

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
