# xAIkit — Product vision

**Status**: draft  
**Last Updated**: 2026-09-18  
**Related**: [Master_Index.md](Master_Index.md)

---

**Humans:** Confirm **whole-product shape** — is / is not + the **end-state picture** + any real-fork Assumptions. Not a feature list. How to review: [`help/SCAFFOLDS.md`](templates/help/SCAFFOLDS.md). Under **build-first**, confirm only when you *lock product shape*.

**Agents:** Fill-in blanks. If context is thin, re-open [`agent/workflow/product-vision.md`](templates/agent/workflow/product-vision.md). Lock gate: [`agent/workflow/understanding.md`](templates/agent/workflow/understanding.md) §4. Feature shape stays on each `-Understanding.md`. Under **build-first**, `draft` is destination-only — do **not** wait for confirm before coding. *Lock product shape* starts the confirm gate.

---

## What this product is

xAIkit is a **straightforward Python kit** whose job is to support **everything the xAI API offers**. One typed client for apps that talk to Grok / xAI. Consumers install the package and call `XaiClient` (plus optional meter, tracer, and catalog helpers). Domain schemas stay in those apps. Offline CI uses `MockChatProvider`.

## What this product is NOT

- NOT a product UI, marketplace, operator console, or playground
- NOT a multi-provider SDK
- NOT contributor/agent ceremony in `README.md` (that file is consumer/release docs only)

## End-state picture

A Python developer constructs one `XaiClient` and reaches every xAI surface through that client. One sitting is “call the typed method the kit already has” — not assembling a second HTTP stack, not opening a dashboard, not swapping vendors. When the kit is whole, nothing xAI publishes is left as a raw leftover the app has to invent.

## How the map fits

| Stem | Role in the whole |
|------|-------------------|
| ClientChat | Typed chat transport (tools, vision, structured outputs) on the same client |
| Catalog | Living model list and `cheapest` / `economy` / `best` resolve per role |
| UsageObservability | Optional purpose-tagged metering and traces |
| MediaRest | REST media: STT / TTS / image generate + edit |
| ConnectAuth | Credentials and OAuth helpers — no product login types |
| VideoGeneration | Imagine video generate / poll / extend |
| RealtimeVoice | Speech-to-speech realtime session + client-secret mint |
| ApiCoverage | Remaining xAI surfaces on the same client (inventory stem) |

## Assumptions (real forks only)

*(none — empty is success)*

## Confirmed with user

- [2026-09-18] — Sync ask: product is a straightforward kit that supports everything the xAI API offers; `docs/reference/` is sparse on purpose (not a second product).
