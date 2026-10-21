# xAIkit agent notes

## Testing

Run only the affected tests while iterating. CI is the full check.

From the repo root, run plain pytest on the test files the change touches. Do not invoke bare pytest, and do not put `-n auto` in `addopts`. The CI pytest job runs the full suite with `pytest -n auto`.
