# ConnectAuth

**Last Updated**: 2026-08-13  
**Related TODO**: [ConnectAuth-TODO.md](ConnectAuth-TODO.md)

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

- [x] Stores + OAuth helpers exist
- [x] Focused unit tests for authorize URL / exchange / env store
- [x] Consumer docs: OAuth endpoints are caller-supplied (no kit portal URLs)
- [x] Consumer docs: weekly Grok remaining is not fetched (no unofficial scrape)

## Current status

- **Last reconciled with code**: 2026-08-13
