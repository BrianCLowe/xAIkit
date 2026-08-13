# PyPI alpha then stable

**Date**: 2026-08-13  
**Status**: accepted  
**Related**: [Master_Index.md](../Master_Index.md) · [Tooling.md](../Tooling.md)

---

## Context

xAIkit is installable from git. The first PyPI upload should claim `xaikit` without implying a finished API. Casual `pip install xaikit` should not get an accidental alpha.

## Decision

- First public version is **`0.1.0a1`** (PEP 440 pre-release) with classifier **Alpha**.
- Publish via **Trusted Publishing** (GitHub Actions OIDC) on tags `v*`. No long-lived PyPI token in the repo.
- Default installs skip alphas; testers opt in with `--pre` / `--prerelease allow`.
- A later non-alpha (`0.1.0` or `0.2.0`) is the “post-testing” release. Do not reuse a version number.

## Rationale

Pre-releases are how PyPI already hides work-in-progress. A README warning alone does not stop `pip install xaikit`.

## Consequences

- Human must add a **pending publisher** on PyPI before the first tag (account [BrianCLowe](https://pypi.org/user/BrianCLowe/)).
- CI builds the wheel on every PR and pytest-installs it (not only `pythonpath = src`).
- Wheel stays code-only (`docs/` excluded).
