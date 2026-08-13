# ConnectAuth — TODO

**Last Updated**: 2026-08-13  
**Related Spec**: [ConnectAuth.md](ConnectAuth.md)

---

## Current focus *(session handoff)*

**Active task:** Stem shipped (library-only). OAuth URLs stay caller-supplied.  
**Blocked by:** —  
**Last session:** 2026-08-13 — README + spec: authorize/token URLs are caller-supplied (no portal hosts in the kit)

---

## High Priority / Next Actions

*(none)*

## Medium Priority

*(none)*

## Human verify (orchestration 2026-08-13)

Library-only look-list — reply in chat when done (do not mark this row yourself).

- **Surfaces:** `build_oauth_authorize_url` / `exchange_oauth_code`; README Connect / OAuth
- **Placement:** `src/xaikit/connect.py`
- **Copy:** authorize/token URLs are **caller-supplied** — no xAI portal hosts in the kit
- **Happy path:** `uv run pytest tests/test_connect_auth.py`
- **Rough edges:** not product login; ephemeral realtime tokens live on RealtimeVoice

## Completed

- [x] **Contract tests** — authorize URL params, missing client_id, env store fallback (**library-only**) (2026-08-13)
- [x] Credential stores + OAuth helpers (2026-08-12 — in tree)
- [x] Document OAuth endpoints as caller-supplied (no hardcoded xAI portal URLs in kit) (2026-08-13)
