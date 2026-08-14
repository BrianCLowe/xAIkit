# PyPI alpha then stable

**Date**: 2026-08-13  
**Status**: accepted  
**Related**: [Master_Index.md](../Master_Index.md) · [Tooling.md](../Tooling.md)

---

## Context

xAIkit is installable from git. The first PyPI upload should not imply a finished API. The distribution name **`xaikit`** was rejected as too similar to existing [`xai-kit`](https://pypi.org/project/xai-kit/) (explainable-AI, unrelated).

## Decision

- PyPI / pip name is **`xaikit-py`**. Import and display stay **`xaikit` / xAIkit**.
- First public version was **`0.1.0a1`**. Consumer-facing README/summary updates that should reach PyPI go out as the next pre-release (**`0.1.0a5`**, then `a6`…). Classifier stays **Alpha**.
- Publish via **Trusted Publishing** (GitHub Actions OIDC) on tags `v*`. Merging to master does **not** publish. No long-lived PyPI token in the repo.
- Default installs skip alphas; testers opt in with `--pre` / `--prerelease allow`.
- A later non-alpha (`0.1.0` or `0.2.0`) is the “post-testing” release. Do not reuse a version number.

## Rationale

Pre-releases hide work-in-progress from a plain `pip install`. Hyphenating `xai-kit` vs `xaikit` is not enough for PyPI’s similarity check; `-py` is.

## Consequences

- Pending publisher project name must be `xaikit-py` (account [BrianCLowe](https://pypi.org/user/BrianCLowe/)).
- CI builds the wheel on every PR and pytest-installs it (not only `pythonpath = src`).
- Wheel stays code-only (`docs/` excluded). Extra install: `xaikit-py[otel]`.
- PyPI **summary** is consumer-facing (“Unofficial Python kit for the xAI (Grok) API…”), not the old “extractable transport” line. Keywords lead with `grok` / `grok-api`; keep `xai` on PyPI (pip search) but **do not** use GitHub topic `xai` (that tag is explainable-AI). GitHub About / website / topics are a Human-TODO (repo settings).
