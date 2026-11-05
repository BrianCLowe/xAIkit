"""Offline reads of .github/workflows/watch-xai-models.yml (no network, no gh)."""

from __future__ import annotations

import ast
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
    assert "${DROPPED_SLUGS" in slug_lines[0]
    assert "${DROPPED_RESOLUTIONS" in res_lines[0]
    assert "NEW_SLUGS" not in slug_lines[0]
    assert "NEW_RES" not in slug_lines[0]
    assert "NEW_SLUGS" not in res_lines[0]
    assert "NEW_RES" not in res_lines[0]
    assert '[ -z "${DROPPED_SLUGS:-}" ]' in step
    assert '[ -z "${DROPPED_RESOLUTIONS:-}" ]' in step


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


def test_wdi_g7_watcher_tests_assert_output_without_gh() -> None:
    source = WATCHER_TESTS.read_text(encoding="utf-8")
    assert "subprocess" not in source
    assert "urlopen" not in source
    assert "gh issue" not in source
    assert 'outputs["has_dropped"] == "true"' in source
    assert "--github-output" in source
