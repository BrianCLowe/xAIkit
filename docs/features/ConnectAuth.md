# ConnectAuth

**Last Updated**: 2026-09-25  
**Related Understanding**: —  
**Related TODO**: [ConnectAuth-TODO.md](ConnectAuth-TODO.md)

---

**Humans:** This is the contract. How to read it: [`help/SCAFFOLDS.md`](../templates/help/SCAFFOLDS.md) · [`help/USAGE.md`](../templates/help/USAGE.md).

**Agents:** Fill-in blanks — not a tutorial. If context is thin, re-open [`agent/workflow/understanding.md`](../templates/agent/workflow/understanding.md) §2. Catalog: [`agent/workflow/extensions.md`](../templates/agent/workflow/extensions.md) §7.1. Decisions: [`agent/workflow/decisions.md`](../templates/agent/workflow/decisions.md). Operable Acceptance: [`agent/workflow/todos.md`](../templates/agent/workflow/todos.md) §5.3. build-first (no Understanding): [`agent/workflow/profile-standing.md`](../templates/agent/workflow/profile-standing.md) §0.1.

---

## Overview

Credential injection and OAuth helpers with **no User/Session types**. Apps pass config dicts / stores.

## Architecture / Contract

- **Owns**: `CredentialStore` protocol, `DictCredentialStore`, `EnvCredentialStore`; OAuth authorize URL + code exchange; `normalize_api_key`
- **Does not own**: login UI, token persistence, user accounts
- **Public API**: `oauth_is_configured`, `build_oauth_authorize_url`, `exchange_oauth_code`, `normalize_api_key`, stores

`XaiClient` resolves key from `api_key=` else `credential_store.get_api_key(subject)`.

## Behavior (stable)

- OAuth configured iff client id and secret are both non-empty
- Authorize URL: `response_type=code`, default scope `openid`, required `client_id` / `authorize_url`
- Token exchange via HTTP; failures raise `RuntimeError`
- **Authorize and token URLs are caller-supplied.** The kit does not embed xAI (or any) portal hostnames. Consumer docs: README **Credentials and OAuth**.
- **No weekly Grok-account remaining.** SuperGrok / grok.com Settings → Usage is not a public API. The kit does not scrape unofficial billing URLs, does not display leftover weekly pool, and does not add User types. `UsageMeter` is app-side call accounting. Team API prepaid remaining is the xAI Console (management key), not OAuth.

## Decisions

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-08-12 | No User/Session in the kit | Extractable transport; apps own identity |
| 2026-08-13 | OAuth `authorize_url` / `token_url` are caller-supplied; no portal URLs in the kit | Apps own the IdP; README documents the helpers without hardcoding xAI hosts |
| 2026-08-13 | Weekly Grok remaining is out of kit | Consumer weekly pool is grok.com Settings → Usage only. Unofficial `/v1/billing` scrapes are unstable. ConnectAuth stays stores + OAuth helpers. |

## Dependencies

| Piece | Relationship |
|-------|--------------|
| [ClientChat.md](ClientChat.md) | Client consumes store / api_key |

## Acceptance *(library stem)*

- [ ] **credential-store** — A caller stores an API key in a dict or env store, and `XaiClient` resolves `api_key=` else `credential_store.get_api_key(subject)`. There is no User or Session type.
- [ ] **oauth-exchange** — A caller with both a client id and a secret builds an authorize URL (`response_type=code`, default scope `openid`, required `client_id` and a caller-supplied `authorize_url`) and posts the code to the caller-supplied `token_url`. A failed exchange raises `RuntimeError`. If either id or secret is empty, OAuth is not configured.
- [ ] **caller-supplied-urls** — A caller supplies `authorize_url` and `token_url`. The kit does not embed an xAI or any other portal hostname, and the consumer docs say the same.
- [ ] **no-weekly-remaining** — A caller does not get a weekly Grok remaining balance from this kit: no unofficial billing scrape, no leftover-pool display, and no User type.

## Visual references

*(none — library stem)*

## Current status

- **Last reconciled with code**: 2026-08-13
