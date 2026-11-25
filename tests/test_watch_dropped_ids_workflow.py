"""Offline reads of .github/workflows/watch-xai-models.yml (no network, no gh)."""

from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "watch-xai-models.yml"
WATCHER_TESTS = ROOT / "tests" / "test_watch_xai_models.py"

_COMPARE = re.compile(
    r"steps\.scan\.outputs\.has_(new|dropped)\s*==\s*'([^']*)'"
)
_STATUS = re.compile(r"\b(always|failure|success)\(\)")


def _step_block(workflow: str, name: str) -> str:
    marker = f"- name: {name}\n"
    start = workflow.index(marker)
    rest = workflow[start + len(marker) :]
    nxt = rest.find("\n      - name:")
    end = start + len(marker) + (len(rest) if nxt == -1 else nxt)
    return workflow[start:end]


def _if_line(step: str) -> str:
    for line in step.splitlines():
        stripped = line.strip()
        if stripped.startswith("if:"):
            return stripped
    raise AssertionError("step has no if condition")


def _token_issue_eligible(
    if_line: str,
    *,
    previous_failed: bool,
    has_new: bool,
    has_dropped: bool,
) -> bool:
    """Evaluate the token-issue ``if`` the way Actions does after a prior step."""
    expr = if_line.strip()
    if expr.startswith("if:"):
        expr = expr.split(":", 1)[1].strip()
    if expr.startswith("${{") and expr.endswith("}}"):
        expr = expr[3:-2].strip()

    calls_always = re.search(r"\balways\(\)", expr) is not None
    calls_failure = re.search(r"\bfailure\(\)", expr) is not None
    if previous_failed and not calls_always and not calls_failure:
        return False

    values = {"new": has_new, "dropped": has_dropped}

    def replace_compare(match: re.Match[str]) -> str:
        actual = "true" if values[match.group(1)] else "false"
        return "True" if actual == match.group(2) else "False"

    def replace_status(match: re.Match[str]) -> str:
        name = match.group(1)
        if name == "always":
            return "True"
        if name == "failure":
            return "True" if previous_failed else "False"
        return "False" if previous_failed else "True"

    rewritten = _COMPARE.sub(replace_compare, expr)
    rewritten = _STATUS.sub(replace_status, rewritten)
    rewritten = rewritten.replace("&&", " and ").replace("||", " or ")
    tree = ast.parse(rewritten, mode="eval")
    allowed = (
        ast.Expression,
        ast.BoolOp,
        ast.And,
        ast.Or,
        ast.UnaryOp,
        ast.Not,
        ast.Constant,
    )
    for node in ast.walk(tree):
        if not isinstance(node, allowed):
            raise AssertionError(f"unrecognized token-issue condition: {if_line!r}")
    return bool(eval(compile(tree, "<if>", "eval"), {"__builtins__": {}}, {}))


def test_wdi_c05_workflow_token_issue_condition() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    step = _step_block(workflow, "Open issue for tokens not already listed")
    condition = _if_line(step)
    assert "always()" in condition
    assert "steps.scan.outputs.has_new == 'true'" in condition
    assert "steps.scan.outputs.has_dropped == 'true'" in condition
    assert "||" in condition
    assert workflow.count("always()") == 1

    assert _token_issue_eligible(
        condition, previous_failed=True, has_new=False, has_dropped=True
    )
    assert not _token_issue_eligible(
        condition, previous_failed=True, has_new=False, has_dropped=False
    )
    assert _token_issue_eligible(
        condition, previous_failed=True, has_new=True, has_dropped=False
    )
    assert not _token_issue_eligible(
        condition, previous_failed=False, has_new=False, has_dropped=False
    )


def test_wdi_c06_workflow_dropped_issue_body() -> None:
    step = _step_block(
        WORKFLOW.read_text(encoding="utf-8"),
        "Open issue for tokens not already listed",
    )
    assert "DROPPED_SLUGS: ${{ steps.scan.outputs.dropped_slugs }}" in step
    assert "DROPPED_RESOLUTIONS: ${{ steps.scan.outputs.dropped_resolutions }}" in step
    body_at = step.index("body=\"$(cat <<EOF")
    body = step[body_at:]
    slug_lines = [line for line in body.splitlines() if "**Dropped slugs:**" in line]
    res_lines = [line for line in body.splitlines() if "**Dropped resolutions:**" in line]
    assert len(slug_lines) == 1
    assert len(res_lines) == 1
    assert "${dropped_slugs" in slug_lines[0]
    assert "${dropped_res" in res_lines[0]
    assert "DROPPED_SLUGS" not in slug_lines[0]
    assert "DROPPED_RESOLUTIONS" not in res_lines[0]
    assert "NEW_SLUGS" not in slug_lines[0]
    assert "NEW_RES" not in slug_lines[0]
    assert "NEW_SLUGS" not in res_lines[0]
    assert "NEW_RES" not in res_lines[0]
    assert '--dropped-slugs "$DROPPED_SLUGS"' in step
    assert '--dropped-resolutions "$DROPPED_RESOLUTIONS"' in step
    assert '[ "$has_dropped" != "true" ]' in step
    assert '[ -z "${DROPPED_SLUGS:-}" ]' not in step


def test_wdi_c07_commit_gate_unchanged() -> None:
    step = _step_block(
        WORKFLOW.read_text(encoding="utf-8"),
        "Commit price gap file when the extract changes",
    )
    assert (
        "if: steps.scan.outputs.exit_code != '1' && steps.guard.outcome == 'success'"
        in step
    )
    assert "always()" not in step
    assert "xai_models_watch.json" not in step
    assert "git add scripts/data/xai_public_prices.json" in step
    assert "git push" in step


_ISSUE_STEP_SHA = "36c21169f5a2042bba23dcf2f42ae99d807bd836eabb0ca7eb7336d2fe8fd62a"


def test_xts_scan_pending_commit_step() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    step = _step_block(workflow, "Commit watch pending file when the scan changes")
    condition = _if_line(step)
    assert condition == "if: ${{ !cancelled() && steps.scan.outputs.scan_ok == 'true' }}"
    assert "cancelled()" in condition
    assert "steps.scan.outputs.scan_ok == 'true'" in condition
    assert "steps.guard" not in step
    assert "exit_code" not in step
    assert "git add scripts/data/xai_models_watch_pending.json" in step
    assert "git diff --cached --quiet" in step
    assert "git commit" in step
    assert "git push" in step
    assert 'git config user.name "github-actions[bot]"' in step
    assert (
        'git config user.email "41898282+github-actions[bot]@users.noreply.github.com"'
        in step
    )
    price = _step_block(workflow, "Commit price gap file when the extract changes")
    assert "xai_models_watch_pending.json" not in price
    assert "Commit watch pending file when the scan changes" not in price
    assert step != price


def test_xts_mark_reported_step() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    step = _step_block(workflow, "Mark reported watch tokens")
    assert "if: ${{ !cancelled() && steps.issue.outcome == 'success' }}" in step
    assert "steps.guard" not in step
    assert "DROPPED_SLUGS: ${{ steps.issue.outputs.dropped_slugs }}" in step
    assert "DROPPED_RESOLUTIONS: ${{ steps.issue.outputs.dropped_resolutions }}" in step
    assert "steps.scan.outputs" not in step
    script = step.split("run: |", 1)[1]
    assert "${{" not in script
    assert '"$DROPPED_SLUGS"' in script
    assert '"$DROPPED_RESOLUTIONS"' in script
    command = (
        "uv run python scripts/watch_xai_models.py --mark-reported "
        "--pending scripts/data/xai_models_watch_pending.json "
        '--dropped-slugs "$DROPPED_SLUGS" '
        '--dropped-resolutions "$DROPPED_RESOLUTIONS"'
    )
    assert command in script
    assert "git add scripts/data/xai_models_watch_pending.json" in script
    assert "git diff --cached --quiet" in script
    assert "git commit" in script
    assert "git push" in script
    assert 'git config user.name "github-actions[bot]"' in script
    issue = _step_block(workflow, "Open issue for tokens not already listed")
    assert "\n        id: issue\n" in issue
    early = issue.index(
        'if [ -z "$slugs" ] && [ -z "$res" ] && [ "$has_dropped" != "true" ]'
    )
    for line in (
        'echo "dropped_slugs=${dropped_slugs}" >> "$GITHUB_OUTPUT"',
        'echo "dropped_resolutions=${dropped_res}" >> "$GITHUB_OUTPUT"',
        'echo "has_dropped=${has_dropped}" >> "$GITHUB_OUTPUT"',
    ):
        assert line in issue
        assert issue.index(line) < early
    stripped = issue.replace("        id: issue\n", "", 1)
    assert "id:" not in stripped
    assert hashlib.sha256(stripped.encode()).hexdigest() == _ISSUE_STEP_SHA
    assert "--select-unlisted" in issue
    assert "steps.guard" not in step


def test_wdi_g7_watcher_tests_assert_output_without_gh() -> None:
    source = WATCHER_TESTS.read_text(encoding="utf-8")
    assert "subprocess" not in source
    assert "urlopen" not in source
    assert "gh issue" not in source
    assert 'outputs["has_dropped"] == "true"' in source
    assert "--github-output" in source
