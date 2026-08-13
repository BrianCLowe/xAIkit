# Python version lockstep with xAI SDK

**Date**: 2026-08-13  
**Status**: accepted  
**Related**: [Master_Index.md](../Master_Index.md) · [Tooling.md](../Tooling.md)

---

## Context

xAIkit originally declared `requires-python = ">=3.14"`. The official `xai-sdk` package supports **Python 3.10+**. A higher floor blocked SDK consumers who are still on 3.10–3.13.

## Decision

xAIkit’s Python floor **tracks `xai-sdk`**: currently `>=3.10,<4.0`. When the SDK raises its floor, raise ours to match. Do not require a newer CPython than the SDK.

Transitive deps that drop 3.10 before the SDK does (today: `websockets` 17 needs 3.11) stay **pinned below that break** until the SDK floor moves.

CI runs the offline suite on **3.10** (floor) and **3.14** (current newest).

## Rationale

Callers installing `xai-sdk` should be able to add xAIkit without a Python upgrade. The kit is a thin typed layer over that SDK plus REST/WS — not a reason to demand 3.14.

## Consequences

- `pyproject.toml` `requires-python` and Tooling/README stay aligned with the SDK README.
- `websockets>=14,<17` until 3.10 is no longer required.
- Agents must not bump the floor “because the agent VM has 3.14.”
