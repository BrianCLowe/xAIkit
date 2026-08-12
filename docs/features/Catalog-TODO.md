# Catalog — TODO

**Last Updated**: 2026-08-12  
**Related Spec**: [Catalog.md](Catalog.md)

---

## Current focus *(session handoff)*

**Active task:** Optional: role-filtered catalog (image/video/voice); not blocking video.  
**Blocked by:** —  
**Last session:** 2026-08-12 — three intents (`cheapest` / `economy` / `best`) with overlap

---

## High Priority / Next Actions

*(none blocking — resolve-chain tests + reasoning-tag fix landed.)*

## Medium Priority

- [ ] **Role-filtered resolve** — `role=image|video|voice` using the same cheapest / economy / best rules (target: [Catalog.md](Catalog.md))
- [ ] Refresh bootstrap / fixture models when xAI retires slugs
- [ ] Surface image/video/voice models in fetch (not chat-only `list_language_models`)

## Low Priority / Future Ideas

- [ ] Persist catalog snapshot to disk (today is in-process)

## Completed

- [x] Catalog module + resolve + thought_level mapping (2026-08-12 — in tree)
- [x] Resolve-chain contract tests + `non-reasoning` slug tag (2026-08-12 — live catalog)
- [x] Three intents + coding-SKU skip (2026-08-12)
