# xAIkit — Master Index

**Purpose**: Single entry point for this project's documentation — overview, locations, and Document Map. Read only the files relevant to the current task.

**Pack version**: 2.10.1 *(from [`templates/VERSION`](templates/VERSION))*

## 1. Project Overview

xAIkit is a **library-first Python kit** for xAI (Grok). The **target product** is one typed client: chat (including tools, vision parts, structured outputs), living catalog with `cheapest` / `economy` / `best` per role, connect/credentials, usage metering, REST media (STT / TTS / image generate + edit), video, realtime voice, and Files/`file_id` plus the remaining xAI surfaces on [ApiCoverage](features/ApiCoverage.md). It is **not** a product UI, marketplace, or multi-provider SDK.

Consumers call `XaiClient` (and optional meter/tracer/catalog helpers). Domain schemas stay in apps. Offline CI uses `MockChatProvider`. Contributor/agent docs live here under `docs/`; **release/consumer docs are `README.md` only**. Whole-product end-state: [`Product-Vision.md`](Product-Vision.md).

### 1.1 Project Profile

| Field | Value |
|-------|--------|
| **Project type** | Python library (PyPI/git install) |
| **Engine / stack** | Python ≥3.10 (lockstep with xAI SDK), hatchling, uv, pytest, httpx, pydantic, websockets, xai-sdk |
| **Game extensions** | Skip |
| **Docs profile** | `build-first` — spec; Understanding not required |

The Document Map lists specs. Do not add a TODO column.

## 2. Key Locations & At a Glance

### 2.1 Key Locations

| Path | Purpose |
|------|---------|
| `README.md` | Consumer / PyPI documentation |
| `src/xaikit/` | Installable package |
| `tests/` | Offline contract + unit tests (canonical wiring prove-out) |
| `examples/` | Optional FastAPI mount (not package surface) |
| `scripts/` | Offline smoke helpers |
| `docs/` | Agent/contributor modular docs |
| `docs/features/` | Library-surface specs (+ Understanding when the profile requires it) |
| `docs/reference/` | Optional chat exports / clippings — not living contracts |
| `docs/Tooling.md` | Dev machine tools + verify commands |
| `docs/Product-Vision.md` | Whole-product end-state picture — is / is not + how the map fits. Always create (lightweight). **`build-first`:** destination, not a gate until *lock product shape* |
| `docs/Human-TODO.md` | Human inbox |
| `docs/Team-Roster.md` | Optional team inbox roster — **create only when `team_inbox` is enabled** (unset here = human-only inbox; file not present) |
| `docs/templates/` | Upstream template pack — **pack-owned; do not edit; full overwrite on sync** ([`templates/README.md`](templates/README.md)). Scaffolds, `help/`, `agent/` (workflow index + modules, optional roles, per-tool install); [`VERSION`](templates/VERSION) and [`CHANGELOG.md`](templates/CHANGELOG.md) |
| `docs/ADT-settings.yaml` | Pack preferences — **docs profile**, **standing.instructions** (playbook overrides, not a notes pad), sync mode, tools, optionals, upstream stamps ([`ADT-settings.example.yaml`](templates/agent/ADT-settings.example.yaml)). No git-delivery key |

### 2.2 At a Glance *(pointers — full rules in the workflow)*

| Topic | Where the rule lives |
|-------|----------------------|
| **Docs profile** | `docs/ADT-settings.yaml` → `docs_profile.mode`. This repo: **`build-first`** (typed APIs / CRUD). **`prevent`** = editors / games / multi-surface (default if unset). **`balanced`** = mixed. [§0.1](templates/agent/workflow/profile-standing.md#01-docs-profile-ceremony-modes) |
| **Docs freshness** | Once per session: `git status` + `git worktree list` before treating Master Index as current. Sibling `docs/` drift = content (`git diff`), not ancestry after squash-merge. Same-stem live docs on an open PR → add there (do not stack PRs). [§0.3](templates/agent/workflow/session-freshness.md) |
| **File layout / kit leftovers** | Flat sibling files; no map-only planned rows; leftovers stay on the existing spec ([ApiCoverage](features/ApiCoverage.md) until that slice is next). Do not create `*-TODO.md`. [§0](templates/agent/workflow/naming-layout.md#0-naming--file-layout-read-before-creating-files) |
| **Understanding / Spec** | build-first: spec; *lock shape* only if a stem gets identity pressure. Shape vs contract. [§4](templates/agent/workflow/understanding.md#4-understanding-features--shared) · [§2](templates/agent/workflow/understanding.md#2-understanding--spec-graduation) |
| **Shared** | Only when actually shared. None yet. [§1](templates/agent/workflow/shared-components.md#1-shared-components--foundation-vs-consumption) |
| **Product vision** | [`Product-Vision.md`](Product-Vision.md) — whole-product end-state; destination-only under `build-first`. [§4.5](templates/agent/workflow/product-vision.md) |
| **Human inbox / Tooling** | [`Human-TODO.md`](Human-TODO.md) · [`Tooling.md`](Tooling.md). Team-Roster only if `team_inbox` is on (unset here) |
| **Size / split** | Split when a file is bloated. [§8](templates/agent/workflow/extensions.md#8-how-to-split-a-large-document) |

**Project notes:** Library, not an app — operable “done” for shipped stems is contract tests + typed API, not a UI. README for consumers; this tree for agents and contributors; wheel stays code-only.

**Next product work** — Tester live look-lists closed 2026-08-16 except REST embed (empty team embed roster). Kit live smokes now cover those extras (`XAITKIT_LIVE=1`; spendier surfaces extra-gated — see [Tooling.md](Tooling.md)). Human inbox: [Human-TODO.md](Human-TODO.md).

## 3. Document Map

### 3.0 Note-type exceptions *(registry)*

| Component / Feature | Omitted note types | Recorded |
|---------------------|-------------------|----------|
| *(none — build-first omits Understanding by profile, not by exception)* | | |

**Default file set** when adding a row (same turn, on disk — no map-only “planned” rows): Spec; **Understanding** per `docs_profile`; Catalog when that work applies. Do not create `*-TODO.md`.

### 3.1 Shared / Core Components

*(none yet)* — provider protocol lives with [ClientChat](features/ClientChat.md).

### 3.2 Features & Modules

| Feature | Spec | Understanding | Catalog |
|---------|------|---------------|---------|
| ClientChat | [ClientChat.md](features/ClientChat.md) | — | — |
| Catalog | [Catalog.md](features/Catalog.md) | — | — |
| UsageObservability | [UsageObservability.md](features/UsageObservability.md) | — | — |
| MediaRest | [MediaRest.md](features/MediaRest.md) | — | — |
| ConnectAuth | [ConnectAuth.md](features/ConnectAuth.md) | — | — |
| VideoGeneration | [VideoGeneration.md](features/VideoGeneration.md) | — | — |
| RealtimeVoice | [RealtimeVoice.md](features/RealtimeVoice.md) | — | — |
| ApiCoverage | [ApiCoverage.md](features/ApiCoverage.md) | — | — |

### 3.3 Project-Level Work

| Area | File |
|------|------|
| **Human inbox** (procure, decide, waiting) | [Human-TODO.md](Human-TODO.md) |

### 3.4 Reference, Decisions, Tooling & Legacy

| Document | Description |
|----------|-------------|
| [Product-Vision.md](Product-Vision.md) | Whole-product end-state — is / is not + one picture the map must fit |
| [Human-TODO.md](Human-TODO.md) | Human inbox |
| Team-Roster | Optional — create only when `team_inbox` is on (unset here; named humans self-ID if enabled) |
| [Tooling.md](Tooling.md) | Dev tools + `uv run pytest` |
| [decisions/](decisions/) | Cross-cutting decisions ([Python version](decisions/python-version.md), [PyPI release](decisions/pypi-release.md)) |
| [reference/](reference/) | Chat exports / clippings (empty at bootstrap) |

## 4. Quick Start

1. Docs freshness first ([Workflow §0.3](templates/agent/workflow/session-freshness.md)) — then read this file; find the stem in **§3 Document Map**.
2. Consumers: `README.md`.
3. Agents: this map → the stem spec.
4. Follow **[`templates/agent/Modular_Docs_Workflow.md`](templates/agent/Modular_Docs_Workflow.md)** (paved path; build-first: no Understanding gate).
5. If this session changed shape or contract, update the spec. There is no Current focus.

---

Live docs layout based on [Agentic Doc Templates](https://github.com/BrianCLowe/Agentic-Doc-Templates) by Brian Lowe, licensed under CC BY 4.0. Pack copy: `docs/templates/` (v2.10.1).
