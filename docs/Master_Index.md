# xAIkit — Master Index

**Purpose**: Single entry point for this project's documentation — overview, locations, and Document Map. Read only the files relevant to the current task.

**Pack version**: 2.7.28 *(from [`templates/VERSION`](templates/VERSION))*

## 1. Project Overview

xAIkit is a **library-first Python kit** for xAI (Grok). The **target product** is one typed client: chat (including tools, vision parts, structured outputs), living catalog with `cheapest` / `economy` / `best` per role, connect/credentials, usage metering, REST media (STT / TTS / image generate + edit), video, realtime voice, and Files/`file_id` plus the remaining xAI surfaces on [ApiCoverage](features/ApiCoverage.md). It is **not** a product UI, marketplace, or multi-provider SDK.

Consumers call `XaiClient` (and optional meter/tracer/catalog helpers). Domain schemas stay in apps. Offline CI uses `MockChatProvider`. Contributor/agent docs live here under `docs/`; **release/consumer docs are `README.md` only**.

### 1.1 Project Profile

| Field | Value |
|-------|--------|
| **Project type** | Python library (PyPI/git install) |
| **TODO labels** | Core (no InEditor / Asset columns) |
| **Engine / stack** | Python ≥3.10 (lockstep with xAI SDK), hatchling, uv, pytest, httpx, pydantic, websockets, xai-sdk |
| **Game extensions** | Skip |
| **Docs profile** | `ship-first` — spec + TODO; no Understanding files |

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
| `docs/features/` | Library-surface specs + TODOs |
| `docs/reference/` | Optional chat exports / clippings — not living contracts |
| `docs/Tooling.md` | Dev machine tools + verify commands |
| `docs/Human-TODO.md` | Human inbox |
| `docs/templates/` | Agentic Doc Templates pack (overwrite on sync) |
| `docs/ADT-settings.yaml` | Pack prefs — docs profile, orchestrator git, **standing.instructions** (playbook overrides, not a notes pad), sync mode, tools, optionals, upstream stamps |

### 2.2 At a Glance *(pointers — full rules in the workflow)*

| Topic | Where the rule lives |
|-------|----------------------|
| **Docs profile** | `docs/ADT-settings.yaml` → `docs_profile.mode`. This repo: **`ship-first`** (typed APIs / CRUD). **`prevent`** = editors / games / multi-surface (default if unset). [§0.1](templates/agent/workflow/profile-standing.md#01-docs-profile-ceremony-modes) |
| **Orchestrator git** | Durable **`milestone-pr`**. Host worktrees: already-in-a-worktree → stay; pack does not `git worktree add`. [orchestrator-git](templates/agent/roles/orchestrator-git.md) |
| **File layout / kit leftovers** | Leftovers stay as TODOs on the inventory stem ([ApiCoverage](features/ApiCoverage.md)) until that slice is next. [§0](templates/agent/workflow/naming-layout.md#0-naming--file-layout-read-before-creating-files) · [§5.4](templates/agent/workflow/todos.md#54-finished-kit-contract--covering-todos-not-wait-for-pickup) |
| **Understanding / Spec** | Ship-first: spec + TODO; *lock shape* only if a stem gets identity pressure. [§4](templates/agent/workflow/understanding.md#4-understanding-features--shared) · [§2](templates/agent/workflow/understanding.md#2-understanding--spec-graduation) |
| **Shared** | Only when actually shared. None yet. [§1](templates/agent/workflow/shared-components.md#1-shared-components--foundation-vs-consumption) |
| **Human inbox / Tooling** | [`Human-TODO.md`](Human-TODO.md) · [`Tooling.md`](Tooling.md) |
| **Size / split** | Split when a file is bloated. [§8](templates/agent/workflow/extensions.md#8-how-to-split-a-large-document) |

**Project notes:** Library, not an app — operable “done” for shipped stems is contract tests + typed API, not a UI. README for consumers; this tree for agents and contributors; wheel stays code-only.

**Next product work** — Tester live look-lists closed 2026-08-16 except REST embed (empty team embed roster). Kit live smokes now cover those extras (`XAITKIT_LIVE=1`; spendier surfaces extra-gated — see [Tooling.md](Tooling.md)). Human inbox: [Human-TODO.md](Human-TODO.md).

## 3. Document Map

### 3.0 Note-type exceptions *(registry)*

| Component / Feature | Omitted note types | Recorded |
|---------------------|-------------------|----------|
| *(none — ship-first omits Understanding by profile, not by exception)* | | |

### 3.1 Shared / Core Components

*(none yet)* — provider protocol lives with [ClientChat](features/ClientChat.md).

### 3.2 Features & Modules

| Feature | Spec | Understanding | Core TODO |
|---------|------|---------------|-----------|
| ClientChat | [ClientChat.md](features/ClientChat.md) | — | [ClientChat-TODO.md](features/ClientChat-TODO.md) |
| Catalog | [Catalog.md](features/Catalog.md) | — | [Catalog-TODO.md](features/Catalog-TODO.md) |
| UsageObservability | [UsageObservability.md](features/UsageObservability.md) | — | [UsageObservability-TODO.md](features/UsageObservability-TODO.md) |
| MediaRest | [MediaRest.md](features/MediaRest.md) | — | [MediaRest-TODO.md](features/MediaRest-TODO.md) |
| ConnectAuth | [ConnectAuth.md](features/ConnectAuth.md) | — | [ConnectAuth-TODO.md](features/ConnectAuth-TODO.md) |
| VideoGeneration | [VideoGeneration.md](features/VideoGeneration.md) | — | [VideoGeneration-TODO.md](features/VideoGeneration-TODO.md) |
| RealtimeVoice | [RealtimeVoice.md](features/RealtimeVoice.md) | — | [RealtimeVoice-TODO.md](features/RealtimeVoice-TODO.md) |
| ApiCoverage | [ApiCoverage.md](features/ApiCoverage.md) | — | [ApiCoverage-TODO.md](features/ApiCoverage-TODO.md) |

### 3.3 Project-Level Work

| Area | TODO File |
|------|-----------|
| **Human inbox** | [Human-TODO.md](Human-TODO.md) |

### 3.4 Reference, Decisions, Tooling & Legacy

| Document | Description |
|----------|-------------|
| [Human-TODO.md](Human-TODO.md) | Human inbox |
| [Tooling.md](Tooling.md) | Dev tools + `uv run pytest` |
| [decisions/](decisions/) | Cross-cutting decisions ([Python version](decisions/python-version.md), [PyPI release](decisions/pypi-release.md)) |
| [reference/](reference/) | Chat exports / clippings (empty at bootstrap) |

## 4. Quick Start

1. Consumers: `README.md`.
2. Agents: this map → the stem spec + TODO.
3. Workflow: [`templates/agent/Modular_Docs_Workflow.md`](templates/agent/Modular_Docs_Workflow.md) (ship-first: no Understanding gate).
4. Current focus: [Human-TODO.md](Human-TODO.md) — only Open item is REST embed live (empty team roster).

---

Live docs layout based on [Agentic Doc Templates](https://github.com/BrianCLowe/Agentic-Doc-Templates) by Brian Lowe, licensed under CC BY 4.0. Pack copy: `docs/templates/` (v2.7.28).
