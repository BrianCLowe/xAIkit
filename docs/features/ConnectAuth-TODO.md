# ConnectAuth — TODO

**Last Updated**: 2026-08-16  
**Related Spec**: [ConnectAuth.md](ConnectAuth.md)

---

## Current focus *(session handoff)*

**Active task:** — (Human verify closed via tester 2026-08-16)  
**Blocked by:** —  
**Last session:** 2026-08-16 — Tester: caller-supplied authorize/token URLs (incl. `accounts.x.ai` when the app sets them); exchange stubbed. Dual-write Human-TODO Done.

---

## High Priority / Next Actions

*(none)*

## Medium Priority

*(none)*

## Human verify (orchestration 2026-08-13)

- [x] **2026-08-16 — Live via xAIkit tester** — `build_oauth_authorize_url` uses caller `authorize_url` (app may pass `accounts.x.ai`; kit does not inject it); `exchange_oauth_code` posts caller `token_url`. Outcome: works. Dual-write: [Human-TODO.md](../Human-TODO.md) Done. Not a registered OAuth app / product login.

## Completed

- [x] **Contract tests** — authorize URL params, missing client_id, env store fallback (**library-only**) (2026-08-13)
- [x] Credential stores + OAuth helpers (2026-08-12 — in tree)
- [x] Document OAuth endpoints as caller-supplied (no hardcoded xAI portal URLs in kit) (2026-08-13)
- [x] Document weekly Grok remaining as out of kit (Settings → Usage; no scrape) (2026-08-13)
