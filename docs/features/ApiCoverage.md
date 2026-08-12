# ApiCoverage

**Last Updated**: 2026-08-12  
**Related TODO**: [ApiCoverage-TODO.md](ApiCoverage-TODO.md)

## Overview

Catch-all stem for **xAI API / `xai_sdk` surfaces this kit does not wrap yet**, excluding video (owned by [VideoGeneration](VideoGeneration.md)). Goal: a typed, metered, mock-testable client for what we take on — not a 1:1 dump of every SDK submodule on day one.

Inventory vs current `xai_sdk.Client` and xAI docs (2026-08):

| Surface | In XaiKit today | Notes |
|---------|-----------------|--------|
| Chat complete / stream | Yes | No tools, no vision parts |
| Models list / catalog | Partial | Chat-oriented resolve |
| Image generate | Yes (REST) | No edit / i2i |
| STT / TTS (REST) | Yes | No realtime voice / streaming STT |
| Video | No | [VideoGeneration](VideoGeneration.md) |
| Function calling / custom tools | No | |
| Built-in tools (web, X, code, collections, image-in-chat) | No | Often Responses / agent-tools API |
| Structured outputs | Partial | `chat_json` heuristic only |
| Files | No | Needed for some video/image `file_id`s |
| Collections / documents | No | |
| Batch | No | |
| Embeddings | No | `embed` in SDK proto |
| Tokenizer | No | |
| Auth subclient | No | |
| Realtime voice / speech-to-speech | No | [RealtimeVoice](RealtimeVoice.md) — next after video |
| Responses API | No | Docs quickstart path |
| Service tiers / deferred | No | |

## Architecture / Contract

- **Owns**: prioritized backlog of remaining API; split a surface into its own Document Map row when implementation starts
- **Does not own**: shipped chat/media/catalog/connect contracts
- **Public API**: none yet — future methods on `XaiClient` or small submodules, same mock + purpose + meter rules

When a slice starts, **add a map row** (spec + TODO) rather than growing this file past ~inventory + ranking.

## Behavior (stable)

- Prefer wrapping upstream rather than reimplementing protocol details
- Every new method: empty-input guards, purpose-when-metered, failed usage, offline contract tests
- Stay library-first (no UI)

## Decisions

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-08-12 | Video first, then ranked remainder | User request |
| 2026-08-12 | Human ranks post-video slices | Avoid agent-guessed product order |
| 2026-08-12 | After video: realtime voice; rest unordered | User confirm 2026-08-12 |

## Dependencies

| Piece | Relationship |
|-------|--------------|
| [VideoGeneration.md](VideoGeneration.md) | First slice; Files may unblock `file_id` |
| [RealtimeVoice.md](RealtimeVoice.md) | Next slice after video |
| [ClientChat.md](ClientChat.md) | Tools / vision / structured outputs land here or split off |

## Acceptance

- [x] Human ranking recorded (Human-TODO)
- [x] Winner split: [RealtimeVoice](RealtimeVoice.md)
- [ ] Each taken slice has its own spec/TODO or a clearly scoped PR
- [ ] No silent “wrap the entire SDK” in one change

## Current status

- **In progress**: remainder unordered after video + realtime voice
- **Blocked by**: —
