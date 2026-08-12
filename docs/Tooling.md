# XaiKit — Tooling

**Last Updated**: 2026-08-12  
**Related**: [Master_Index.md](Master_Index.md)

---

Machine / workflow tools to **develop this library** — not the package dependencies in `pyproject.toml`.

## Host platforms

| Platform | Notes |
|----------|--------|
| Linux / macOS | `uv` installer; CPython 3.14 via uv |
| Windows | Same via uv; not the primary CI image |

## Required

| Tool | Why | Install hint | Verify |
|------|-----|--------------|--------|
| Git | Version control | OS package manager | `git --version` |
| uv | Python + deps + pytest | https://docs.astral.sh/uv/ | `uv --version` |
| Python 3.14 | Package `requires-python` | `uv python install 3.14` | `uv run python --version` |

## Optional

| Tool | Why | Install hint | Verify |
|------|-----|--------------|--------|
| GitHub CLI (`gh`) | Inspect PRs / CI (read-only in Cloud Agents) | https://cli.github.com/ | `gh --version` |
| FastAPI + uvicorn | Run `examples/run_mock_server.py` | `uv run --with fastapi --with "uvicorn[standard]"` | — |

## After tools are installed

1. `uv sync --group dev`
2. `uv run pytest`
3. Optional: `uv run python scripts/smoke_meter_mock.py`

Do not commit `.env` / API keys. Live xAI calls are optional and not default CI.

## Project verify *(agent handoff)*

| Scope | When | Command(s) | Notes |
|-------|------|------------|--------|
| **Cheap / default** | Most code changes | `uv run pytest` | Offline; no API key. Live smokes stay skipped. |
| **Touched package** | Library modules only | `uv run pytest tests/` | Same suite today |
| **Full handoff** | Claiming the kit works | `uv run pytest` and `uv run python scripts/smoke_meter_mock.py` | Still offline |
| **Tests** | Always for Python changes | `uv run pytest` | Canonical wiring prove-out |
| **Live (optional)** | Key present + explicit opt-in | `XAITKIT_LIVE=1 uv run pytest tests/test_live_smoke.py -m live -v` | Needs `XAI_API_KEY`; not CI |

## Instructions for AI Agents

- Before claiming code is good, run **Cheap / default**.
- Do not invent extra required tools. Live-key smokes stay optional and env-gated (key procured — see Human-TODO Done).
