# Security

This is a small public Python library (`xaikit-py`). Please report vulnerabilities **privately** — do not open a public issue for a secret leak, auth bypass, or anything that could be exploited before a fix is out.

## How to report

Use GitHub’s private advisory form:

https://github.com/BrianCLowe/xAIkit/security/advisories/new

Include the package version (`python -c "import xaikit; print(xaikit.__version__)"`), how you installed it, and a short repro. Redact API keys.

## What to expect

We will acknowledge the report, rotate anything leaked, and cut a release if the installed package is affected.

## Not in scope

- Guessing or brute-forcing xAI API keys (those are the caller’s secret)
- Issues in `xai-sdk`, xAI’s API, or other dependencies — report those upstream
- Live-test spend / rate limits

## Maintainers

Do not commit `.env`, API keys, or PyPI tokens. Publish uses Trusted Publishing on `v*` tags only.
