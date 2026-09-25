# ConnectAuth — TODO

**Last Updated**: 2026-09-25  
**Related Spec**: [ConnectAuth.md](ConnectAuth.md)
**Related Understanding**: —

---

**Humans:** [`help/SCAFFOLDS.md`](../templates/help/SCAFFOLDS.md). Inbox: [`Human-TODO.md`](../Human-TODO.md).

**Agents:** Fill-in blanks. If context is thin, re-open [`agent/workflow/todos.md`](../templates/agent/workflow/todos.md) (Current focus §5.1 · operable §5.3 · outcomes §5.5 · kit coverage §5.4). Human dual-write: [`agent/workflow/human-todo.md`](../templates/agent/workflow/human-todo.md). Shared foundation: [`agent/workflow/shared-components.md`](../templates/agent/workflow/shared-components.md).

---

## Current focus *(session handoff)*

**Active task:** Exercise credential-store — run the scenario and record the first break.  
**Blocked by:** —  
**Last session:** 2026-09-25 — Outcomes pass: Acceptance rewritten to scenarios and left open (no passing exercise note).

---

## Outcomes

- [ ] **credential-store** — A caller stores an API key in a dict or env store, and `XaiClient` resolves `api_key=` else `credential_store.get_api_key(subject)`. There is no User or Session type.
- [ ] **oauth-exchange** — A caller with both a client id and a secret builds an authorize URL (`response_type=code`, default scope `openid`, required `client_id` and a caller-supplied `authorize_url`) and posts the code to the caller-supplied `token_url`. A failed exchange raises `RuntimeError`. If either id or secret is empty, OAuth is not configured.
- [ ] **caller-supplied-urls** — A caller supplies `authorize_url` and `token_url`. The kit does not embed an xAI or any other portal hostname, and the consumer docs say the same.
- [ ] **no-weekly-remaining** — A caller does not get a weekly Grok remaining balance from this kit: no unofficial billing scrape, no leftover-pool display, and no User type.

## High Priority / Next Actions

- [ ] **Exercise credential-store** — Run the scenario and record the first break (path, date, observed result). `outcome: credential-store`
- [ ] **Exercise oauth-exchange** — Run the scenario and record the first break (path, date, observed result). `outcome: oauth-exchange`
- [ ] **Exercise caller-supplied-urls** — Run the scenario and record the first break (path, date, observed result). `outcome: caller-supplied-urls`
- [ ] **Exercise no-weekly-remaining** — Run the scenario and record the first break (path, date, observed result). `outcome: no-weekly-remaining`

## Medium Priority

*(none)*

## Low Priority / Future Ideas

*(none)*

## Cross-Feature Dependencies & Integration Notes

*(none)*

## Human verify (orchestration 2026-08-13)

- [x] **2026-08-16 — Live via xAIkit tester** — `build_oauth_authorize_url` uses caller `authorize_url` (app may pass `accounts.x.ai`; kit does not inject it); `exchange_oauth_code` posts caller `token_url`. Outcome: works. Dual-write: [Human-TODO.md](../Human-TODO.md) Done. Not a registered OAuth app / product login.

## Completed

- [x] **Contract tests** — authorize URL params, missing client_id, env store fallback (**library-only**) (2026-08-13)
- [x] Credential stores + OAuth helpers (2026-08-12 — in tree)
- [x] Document OAuth endpoints as caller-supplied (no hardcoded xAI portal URLs in kit) (2026-08-13) `outcome: caller-supplied-urls`
- [x] Document weekly Grok remaining as out of kit (Settings → Usage; no scrape) (2026-08-13) `outcome: no-weekly-remaining`
