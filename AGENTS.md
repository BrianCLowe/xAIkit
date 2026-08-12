# AGENTS.md

## Cursor Cloud specific instructions

XaiKit is a **library-first** Python kit (typed xAI/Grok client + model catalog + connect +
usage metering) with a `MockChatProvider` so everything runs **offline with no API key**.
There is no long-running production service — the "app" surface is the typed `XaiClient`
API plus an optional example FastAPI mount under `examples/`.

Canonical tooling and verify commands live in [`docs/Tooling.md`](docs/Tooling.md); package
deps are in `pyproject.toml`. Notes below are only the non-obvious bits.

- Toolchain is `uv` with **Python 3.14** (`requires-python = ">=3.14,<4.0`). The startup
  update script runs `uv sync --group dev`, which provisions the pinned CPython and the
  `.venv`. Prefix everything with `uv run` (e.g. `uv run pytest`); the system `python3` is
  3.12 and cannot build/run this package.
- `uv` installs to `~/.local/bin`. It is normally on `PATH`; if a fresh shell can't find it,
  run `export PATH="$HOME/.local/bin:$PATH"`.
- Tests / verify: `uv run pytest` (47 tests, fully offline, ~1s). This is the canonical gate.
  There is **no separate lint/type-check step configured** (no `ruff`/`mypy` declared as
  deps) — `pytest` is the project's handoff verify per `docs/Tooling.md`.
- Exercise path (no key): `uv run python scripts/smoke_meter_mock.py`.
- Example HTTP mount: FastAPI/uvicorn are **not** package deps — run the sample with an
  ephemeral env: `uv run --with fastapi --with "uvicorn[standard]" python examples/run_mock_server.py`
  (serves `GET /status` and `POST /chat` on `127.0.0.1:8765`). The docstrings mention
  `packages/xaikit/...` paths from an upstream monorepo layout; in this repo run from the
  repo root as shown above.
- Live xAI calls require an API key and are **never** part of default CI. Keep them
  env-gated; do not commit `.env`/keys.
