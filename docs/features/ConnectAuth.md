# ConnectAuth

**Last Updated**: 2026-10-12  
**Related Understanding**: —  

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

`XaiClient` resolves a key from explicit `api_key=` else `credential_store.get_api_key(subject)`, then `normalize_api_key`. `EnvCredentialStore()` reads its variable when the store is built.

## Behavior (stable)

- OAuth configured iff client id and secret are both non-empty
- Authorize URL: `response_type=code`, default scope `openid`, required `client_id` / `authorize_url`. An existing query is kept and merged, caller parameters first, then `client_id`, `redirect_uri`, `response_type`, `scope`, `state`. Kit values win for those five names, so those names are not repeated. The fragment stays after the query. A blank `client_id` or `authorize_url` (including a URL that is only `?`) raises `ValueError`.
- Token exchange via HTTP; failures raise `RuntimeError`
- **Authorize and token URLs are caller-supplied.** The kit does not embed xAI (or any) portal hostnames. Consumer docs: README **Credentials and OAuth**.
- **No weekly Grok-account remaining.** SuperGrok / grok.com Settings → Usage is not a public API. The kit does not scrape unofficial billing URLs, does not display leftover weekly pool, and does not add User types. `UsageMeter` is app-side call accounting. Team API prepaid remaining is the xAI Console (management key), not OAuth.
- `EnvCredentialStore()` reads `os.environ` once at construction. The default variable is `XAI_API_KEY`. `name=` selects another variable. An unset or whitespace-only value raises `RuntimeError` then, before a client request. The message contains "api key" and the variable name. Passing `api_key` positionally stores that string and does not consult the environment. A blank positional value still means no key.
- `XaiClient` applies `normalize_api_key` to an explicit `api_key=` and to the store key. The helper trims whitespace, drops one leading `Bearer` prefix (any case) when at least one whitespace character follows, then trims again. A bare `Bearer` is empty. `BearerToken` is unchanged. An empty result raises `RuntimeError` before any network call, and that message contains "api key". An explicit `api_key=` that normalizes to a key wins over the store.

## Decisions

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-08-12 | No User/Session in the kit | Extractable transport; apps own identity |
| 2026-08-13 | OAuth `authorize_url` / `token_url` are caller-supplied; no portal URLs in the kit | Apps own the IdP; README documents the helpers without hardcoding xAI hosts |
| 2026-08-13 | Weekly Grok remaining is out of kit | Consumer weekly pool is grok.com Settings → Usage only. Unofficial `/v1/billing` scrapes are unstable. ConnectAuth stays stores + OAuth helpers. |
| 2026-10-12 | `EnvCredentialStore()` reads the environment at construction | Omit `api_key` to read `name` (default `XAI_API_KEY`) once while building the store. An unset or empty variable raises immediately and names the variable. A positional `api_key` still stores that string and does not read the environment. |
| 2026-10-12 | `normalize_api_key` strips one leading Bearer prefix | Any case, and only when whitespace follows. Then trim again. A bare `Bearer` is empty. `BearerToken` stays. `XaiClient` applies this to explicit `api_key=` and the store key. |
| 2026-10-12 | Existing authorize query is merged; kit values win | Caller parameters stay, in order, ahead of the kit parameters. `client_id`, `redirect_uri`, `response_type`, `scope`, and `state` always use the kit value. The fragment stays after the query. |

## Dependencies

| Piece | Relationship |
|-------|--------------|
| [ClientChat.md](ClientChat.md) | Client consumes store / api_key |

## Acceptance *(library stem)*

- [x] **credential-store** — A caller stores an API key in a dict or env store, and `XaiClient` resolves `api_key=` else `credential_store.get_api_key(subject)`. There is no User or Session type.
  - [x] XK-AC-CRED-1: An `XaiClient` built with only a `DictCredentialStore` sends the stored key for its subject as the bearer credential on a real request. A subject miss and a `None` subject use the store default key. A client with explicit `api_key=` sends that key, not the stored one.
  - [x] XK-AC-CRED-2: `EnvCredentialStore` reads the environment when it is built if no `api_key` argument is passed. The default variable is `XAI_API_KEY`. `name=` selects another variable. The key is fixed at that construction, not read again per request. An unset or empty variable raises before any network call. The error contains "api key" and the variable name. A positional `api_key` stays a pre-loaded string and does not read the environment.
  - [x] XK-AC-CRED-3: `XaiClient` runs `normalize_api_key` on an explicit `api_key=` and on the store key. The helper trims whitespace, removes one leading `Bearer` prefix of any case when whitespace follows it, then trims again. A bare `Bearer` counts as empty and raises the clear error (the message contains "api key") before any network call. `BearerToken` is left untouched.
- [x] **oauth-exchange** — A caller with both a client id and a secret builds an authorize URL (`response_type=code`, default scope `openid`, required `client_id` and a caller-supplied `authorize_url`) and posts the code to the caller-supplied `token_url`. A failed exchange raises `RuntimeError`. If either id or secret is empty, OAuth is not configured.
  - [x] XK-AC-OAUTH-1: When `authorize_url` already has a query, that query is kept and merged with the kit parameters. The result has one `?`. Scheme, host, and path stay the same. Caller parameters stay in their original order, ahead of `client_id`, `redirect_uri`, `response_type`, `scope`, and `state`. An encoded caller value is preserved. Names are not repeated.
  - [x] XK-AC-OAUTH-2: Kit values replace caller values for `client_id`, `redirect_uri`, `response_type`, `scope`, and `state`, including repeated caller names for those keys. Other caller parameters (for example `audience`) stay. The `scopes=` argument is the `scope` that is sent.
  - [x] XK-AC-OAUTH-3: An authorize URL with no query, a trailing `?`, or a trailing `??` returns the same string as a URL with no query. A fragment on the caller URL stays after the query.
- [x] **caller-supplied-urls** — A caller supplies `authorize_url` and `token_url`. The kit does not embed an xAI or any other portal hostname, and the consumer docs say the same.
- [x] **no-weekly-remaining** — A caller does not get a weekly Grok remaining balance from this kit: no unofficial billing scrape, no leftover-pool display, and no User type.

## Visual references

*(none — library stem)*

## Current status

- **Last reconciled with code**: 2026-10-12 (XK-AC-OAUTH-1 existing query kept and merged; XK-AC-OAUTH-2 kit values win on the five authorize names; XK-AC-OAUTH-3 no-query and trailing question marks stay the same string, fragment after the query)
