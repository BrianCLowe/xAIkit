# xAIkit — Tooling

**Last Updated**: 2026-08-14  
**Related**: [Master_Index.md](Master_Index.md)

---

Machine / workflow tools to **develop this library** — not the package dependencies in `pyproject.toml`.

## Host platforms

| Platform | Notes |
|----------|--------|
| Linux / macOS | `uv` installer; CPython 3.10+ via uv (floor matches xAI SDK) |
| Windows | Same via uv; not the primary CI image |

## Required

| Tool | Why | Install hint | Verify |
|------|-----|--------------|--------|
| Git | Version control | OS package manager | `git --version` |
| uv | Python + deps + pytest | https://docs.astral.sh/uv/ | `uv --version` |
| Python 3.10+ | Package `requires-python` (SDK lockstep) | `uv python install 3.10` | `uv run python --version` |

## Optional

| Tool | Why | Install hint | Verify |
|------|-----|--------------|--------|
| GitHub CLI (`gh`) | Inspect PRs / CI (read-only in Cloud Agents) | https://cli.github.com/ | `gh --version` |
| FastAPI + uvicorn | Run `examples/run_mock_server.py` | `uv run --with fastapi --with "uvicorn[standard]"` | — |

## After tools are installed

1. `uv sync --group dev`
2. `uv run pytest`
3. Optional: `uv run python scripts/smoke_meter_mock.py`
4. Optional packaging: `uv build` then install the wheel (see Project verify)

Do not commit `.env` / API keys. Live xAI calls are optional and not default CI. Do not store PyPI tokens in git — publish uses Trusted Publishing.

## Project verify *(agent handoff)*

| Scope | When | Command(s) | Notes |
|-------|------|------------|--------|
| **Cheap / default** | Most code changes | `uv run pytest` | Offline; no API key. Live smokes stay skipped. |
| **Touched package** | Library modules only | `uv run pytest tests/` | Same suite today |
| **Full handoff** | Claiming the kit works | `uv run pytest` and `uv run python scripts/smoke_meter_mock.py` | Still offline |
| **Package** | Wheel / PyPI / hatchling changes | `uv build`; `uv run --isolated --no-project --with dist/*.whl python -c "import xaikit; print(xaikit.__version__)"`; `uv run --isolated --no-project --with dist/*.whl --with pytest pytest tests -o pythonpath= -m "not live"` | Tests the artifact, not `src/` on `PYTHONPATH`. Wheel must not contain `docs/`. |
| **Tests** | Always for Python changes | `uv run pytest` | Canonical wiring prove-out |
| **Live (optional)** | Key present + explicit opt-in | `XAITKIT_LIVE=1 uv run pytest tests/test_live_smoke.py -m live -v` | Needs `XAI_API_KEY`; not CI. Video also needs `XAITKIT_LIVE_VIDEO=1`; realtime voice also needs `XAITKIT_LIVE_VOICE=1`; streaming STT also needs `XAITKIT_LIVE_STT=1`; embeddings also need `XAITKIT_LIVE_EMBED=1`. |
| **Model watch** | New xAI SKU / resolution on public docs | `uv run python scripts/watch_xai_models.py` | No API key. Diffs models/pricing/release-notes/Imagine pages vs `scripts/data/xai_models_watch.json`. Daily Actions workflow `.github/workflows/watch-xai-models.yml` opens a `xai-models` issue. After you update the kit, `--write-baseline` and close the issue. |

## Instructions for AI Agents

- Before claiming code is good, run **Cheap / default**. After packaging/PyPI edits, also run **Package**.
- Do not invent extra required tools. Live-key smokes stay optional and env-gated (`XAITKIT_LIVE=1` plus `XAI_API_KEY` — see Human-TODO Done).
- PyPI publish: bump `pyproject.toml` version (and the `PackageNotFoundError` fallback in `src/xaikit/__init__.py`), merge to master, then tag `v<that-version>` (currently `v0.1.0a4`). Never reuse a version. Trusted Publishing — no tokens in the repo.
