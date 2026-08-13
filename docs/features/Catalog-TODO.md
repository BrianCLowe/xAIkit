# Catalog — TODO

**Last Updated**: 2026-08-13  
**Related Spec**: [Catalog.md](Catalog.md)

---

## Current focus *(session handoff)*

**Active task:** Persist catalog snapshot to disk (today is in-process)  
**Blocked by:** —  
**Last session:** 2026-08-13 — bootstrap `grok-4.6`; offline fallback `grok-4.6` + `grok-4.3`; public chat rates in `pricing.py`

---

## High Priority / Next Actions

*(none blocking — role-filtered catalog landed.)*

## Medium Priority

*(none)*

## Low Priority / Future Ideas

- [ ] Persist catalog snapshot to disk (today is in-process)

## Completed

- [x] Catalog module + resolve + thought_level mapping (2026-08-12 — in tree)
- [x] Resolve-chain contract tests + `non-reasoning` slug tag (2026-08-12 — live catalog)
- [x] Three intents + coding-SKU skip (2026-08-12)
- [x] Role-filtered resolve — `role=image|video|voice` using the same cheapest / economy / best rules (2026-08-13)
- [x] Surface image/video/voice models in fetch (not chat-only `list_language_models`) (2026-08-13)
- [x] Refresh bootstrap / fixture models when xAI retires slugs (2026-08-13 — `BOOTSTRAP_MODEL=grok-4.6`; offline cheap row `grok-4.3`; grok-3-mini out of fallback)
