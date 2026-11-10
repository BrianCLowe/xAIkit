"""Offline price-guard diagnostics. Mocked uv/gh only: no network, issue, or database."""

from __future__ import annotations

import importlib.util
import json
import os
import shlex
import stat
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "watch_xai_models.py"
WORKFLOW = ROOT / ".github" / "workflows" / "watch-xai-models.yml"

NODE_A = (
    "tests/test_pricing.py::test_shipped_ranked_image_rates_match_public_watch"
    "[grok-imagine-image-2.0]"
)
NODE_B = (
    "tests/test_pricing.py::test_every_shipped_image_per_call_matches_watch_file"
    "[grok-imagine-image-2.0]"
)
NODE_C = "tests/test_pricing.py::test_image_2_0_base_rate_is_0_04"
NODES = (NODE_A, NODE_B, NODE_C)
UNKNOWN_FALLBACK = "**Ids:** `unknown`"


def _load():
    spec = importlib.util.spec_from_file_location("watch_xai_models_reporting", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _shipped_rates() -> dict[str, float]:
    from xaikit.pricing import default_price_table

    rates = {
        str(model_id): float(price.per_call_usd)
        for model_id, price in default_price_table().models.items()
        if str(model_id).startswith("grok-imagine-image") and price.per_call_usd is not None
    }
    assert "grok-imagine-image-2.0" in rates
    return rates


def _extract(rates: dict[str, float]) -> dict:
    return {
        "models": {
            model_id: {"per_call_usd": rate} for model_id, rate in rates.items()
        }
    }


def _pytest_log(nodes: tuple[str, ...] = NODES) -> str:
    lines = ["=========================== short test summary info ============================"]
    for node in nodes:
        lines.append(f"FAILED {node} - AssertionError")
    lines.append(f"========================= {len(nodes)} failed in 0.01s =========================")
    return "\n".join(lines) + "\n"


def _extract_run_blocks(yaml_text: str) -> list[tuple[str, str]]:
    """Return (step name, shell script) for each `run: |` step."""
    lines = yaml_text.splitlines()
    blocks: list[tuple[str, str]] = []
    step_name = ""
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("- name:"):
            step_name = stripped.split(":", 1)[1].strip()
        if stripped != "run: |":
            continue
        run_indent = len(line) - len(line.lstrip(" "))
        body: list[str] = []
        for raw in lines[i + 1 :]:
            if raw.strip() == "":
                body.append("")
                continue
            indent = len(raw) - len(raw.lstrip(" "))
            if indent <= run_indent:
                break
            body.append(raw)
        indents = [len(item) - len(item.lstrip(" ")) for item in body if item.strip()]
        cut = min(indents) if indents else 0
        script = "\n".join((item[cut:] if len(item) >= cut else item) for item in body) + "\n"
        blocks.append((step_name, script))
    return blocks


def _step_script(name: str) -> str:
    for step_name, script in _extract_run_blocks(WORKFLOW.read_text(encoding="utf-8")):
        if step_name == name:
            return script
    raise AssertionError(f"missing workflow step {name}")


def _parse_github_output(text: str) -> dict[str, str]:
    outputs: dict[str, str] = {}
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if "<<" in line:
            name, _, delim = line.partition("<<")
            delim = delim.strip()
            index += 1
            chunk: list[str] = []
            while index < len(lines) and lines[index] != delim:
                chunk.append(lines[index])
                index += 1
            outputs[name] = "\n".join(chunk) + ("\n" if chunk else "")
            index += 1
            continue
        if "=" in line:
            name, _, value = line.partition("=")
            outputs[name] = value
        index += 1
    return outputs


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _run_workflow_case(
    tmp_path: Path,
    *,
    rates: dict[str, float],
    pytest_rc: int,
    nodes: tuple[str, ...] = NODES,
) -> dict:
    """Run the real guard shell and, on failure, the real failed-guard issue shell."""
    work = tmp_path / "work"
    bin_dir = tmp_path / "bin"
    (work / "scripts" / "data").mkdir(parents=True)
    bin_dir.mkdir(parents=True)
    prices = work / "scripts" / "data" / "xai_public_prices.json"
    prices.write_text(json.dumps(_extract(rates), indent=2) + "\n", encoding="utf-8")
    (work / "scripts" / "watch_xai_models.py").symlink_to(SCRIPT)
    log_fixture = tmp_path / "pytest-output.txt"
    log_fixture.write_text(_pytest_log(nodes), encoding="utf-8")
    marker = tmp_path / "guard-python-invoked"
    gh_capture = tmp_path / "gh-capture.json"
    github_output = tmp_path / "github-output.txt"
    github_output.write_text("", encoding="utf-8")
    _write_executable(
        bin_dir / "uv",
        textwrap.dedent(
            """\
            #!/bin/bash
            if [ "${1:-}" = "sync" ]; then
              exit 0
            fi
            if [ "${1:-}" = "run" ] && [ "${2:-}" = "pytest" ]; then
              cat "$PGI_PYTEST_LOG"
              exit "$PGI_PYTEST_RC"
            fi
            if [ "${1:-}" = "run" ] && [ "${2:-}" = "python" ]; then
              printf 'invoked\\n' >> "$PGI_GUARD_MARKER"
              exec "$PGI_PYTHON" "${@:3}"
            fi
            echo "unexpected uv invocation: $*" >&2
            exit 99
            """
        ),
    )
    quoted_capture = shlex.quote(str(gh_capture))
    _write_executable(
        bin_dir / "gh",
        textwrap.dedent(
            f"""\
            #!/bin/bash
            if [ "${{1:-}}" = "issue" ] && [ "${{2:-}}" = "create" ]; then
              "$PGI_PYTHON" - {quoted_capture} "$@" << 'PY'
            import json, sys
            path, args = sys.argv[1], sys.argv[2:]
            data = {{"argv": args}}
            index = 0
            while index < len(args):
                token = args[index]
                if token.startswith("--") and index + 1 < len(args):
                    data[token[2:]] = args[index + 1]
                    index += 2
                else:
                    index += 1
            open(path, "w", encoding="utf-8").write(json.dumps(data))
            PY
            fi
            exit 0
            """
        ),
    )
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env.pop("GH_TOKEN", None)
    env.pop("GITHUB_TOKEN", None)
    env["GITHUB_OUTPUT"] = str(github_output)
    env["PGI_PYTEST_LOG"] = str(log_fixture)
    env["PGI_PYTEST_RC"] = str(pytest_rc)
    env["PGI_GUARD_MARKER"] = str(marker)
    env["PGI_PYTHON"] = sys_executable()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    guard_script = tmp_path / "guard.sh"
    guard_script.write_text(_step_script("Guard price extract"), encoding="utf-8")
    guard = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", str(guard_script)],
        cwd=work,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    outputs = _parse_github_output(github_output.read_text(encoding="utf-8"))
    issue_body = ""
    issue_title = ""
    if guard.returncode != 0:
        issue_env = env.copy()
        issue_env["GUARD_TITLE"] = outputs.get("guard_title", "")
        issue_env["GUARD_BODY"] = outputs.get("guard_body", "")
        issue_env["GUARD_IDS"] = outputs.get("guard_ids", "")
        issue_script = tmp_path / "issue.sh"
        issue_script.write_text(
            _step_script("Open issue for failed price guard"),
            encoding="utf-8",
        )
        issue = subprocess.run(
            ["bash", "--noprofile", "--norc", "-eo", "pipefail", str(issue_script)],
            cwd=work,
            env=issue_env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert issue.returncode == 0, issue.stderr
        assert gh_capture.is_file(), "failed guard did not reach gh issue create"
        captured = json.loads(gh_capture.read_text(encoding="utf-8"))
        issue_body = captured.get("body", "")
        issue_title = captured.get("title", "")
    return {
        "exit": guard.returncode,
        "stdout": guard.stdout,
        "stderr": guard.stderr,
        "outputs": outputs,
        "python_invoked": marker.is_file(),
        "issue_body": issue_body,
        "issue_title": issue_title,
        "gh_called": gh_capture.is_file(),
    }


def sys_executable() -> str:
    import sys

    return sys.executable


def test_parse_pytest_failing_nodes_keeps_first_and_suffix() -> None:
    watch = _load()
    colored = (
        "\x1b[31mFAILED\x1b[0m "
        f"{NODE_A} - AssertionError\n"
        f"FAILED {NODE_B} - AssertionError\n"
        f"FAILED {NODE_C} - assert False\n"
        f"FAILED {NODE_A} - AssertionError\n"
    )
    nodes = watch.parse_pytest_failing_nodes(colored)
    assert nodes == NODES
    assert nodes[0].endswith("[grok-imagine-image-2.0]")
    assert nodes[0] != NODE_C


def test_c02_formatter_names_first_node_not_a_later_one() -> None:
    watch = _load()
    result = watch.GuardResult(ok=True, ids=())
    title, body = watch.guard_diagnostic_text(result, NODES)
    assert title.startswith("xAI shipped image price guard failed")
    assert "This is a pytest failure, not missing shipped image ids." in body
    assert "The shipped image id check passed" in body
    assert f"First failing test: {NODE_A}" in body
    assert f"First failing test: {NODE_B}" not in body
    assert f"First failing test: {NODE_C}" not in body
    assert "The watcher extract is missing a shipped image id" not in body
    assert "or its per_call_usd does not match the shipped default" not in body
    assert "unknown" not in body.lower()
    assert body.index(NODE_A) < body.index(NODE_C)


def test_c01_formatter_names_ids_and_nodes() -> None:
    watch = _load()
    shipped = _shipped_rates()
    rates = dict(shipped)
    rates["grok-imagine-image-2.0"] = 0.06
    result = watch.check_shipped_image_prices(_extract(rates), shipped)
    assert result.ok is False
    assert result.ids == ("grok-imagine-image-2.0",)
    _title, body = watch.guard_diagnostic_text(result, NODES)
    assert "grok-imagine-image-2.0" in body
    assert NODE_A in body
    assert body.index(NODE_A) < body.index(NODE_C)
    assert "unknown" not in body.lower()
    assert UNKNOWN_FALLBACK not in body


def test_c01_workflow_mock_reaches_issue_with_ids(tmp_path: Path) -> None:
    rates = _shipped_rates()
    rates["grok-imagine-image-2.0"] = 0.06
    ran = _run_workflow_case(tmp_path, rates=rates, pytest_rc=1)
    assert ran["exit"] == 1, ran["stderr"]
    assert ran["python_invoked"] is True
    assert ran["outputs"].get("guard_ids") == "grok-imagine-image-2.0"
    body = ran["issue_body"]
    assert body == ran["outputs"].get("guard_body")
    assert "grok-imagine-image-2.0" in body
    assert NODE_A in body
    assert body.index(NODE_A) < body.index(NODE_C)
    assert "unknown" not in body.lower()
    assert UNKNOWN_FALLBACK not in body
    assert "short test summary info" in ran["stdout"]
    assert ran["exit"] != 0


def test_c02_workflow_mock_distinguishes_pytest_from_missing_ids(tmp_path: Path) -> None:
    ran = _run_workflow_case(tmp_path, rates=_shipped_rates(), pytest_rc=1)
    assert ran["exit"] == 1, ran["stderr"]
    assert ran["python_invoked"] is True
    assert ran["outputs"].get("guard_ids") == ""
    body = ran["issue_body"]
    assert body == ran["outputs"].get("guard_body")
    assert "This is a pytest failure, not missing shipped image ids." in body
    assert "The shipped image id check passed" in body
    assert f"First failing test: {NODE_A}" in body
    assert f"First failing test: {NODE_B}" not in body
    assert f"First failing test: {NODE_C}" not in body
    assert NODE_A.endswith("[grok-imagine-image-2.0]")
    assert "The watcher extract is missing a shipped image id" not in body
    assert "or its per_call_usd does not match the shipped default" not in body
    assert UNKNOWN_FALLBACK not in body
    assert "unknown" not in body.lower()
    assert "short test summary info" in ran["stdout"]
    assert ran["exit"] != 0


def test_c03_id_check_only_still_names_failing_id(tmp_path: Path) -> None:
    watch = _load()
    rates = _shipped_rates()
    shipped = dict(rates)
    rates["grok-imagine-image-2.0"] = 0.06
    result = watch.check_shipped_image_prices(_extract(rates), shipped)
    title, body = watch.guard_issue_text(result)
    assert result.ids == ("grok-imagine-image-2.0",)
    assert "grok-imagine-image-2.0" in title
    assert "grok-imagine-image-2.0" in body
    assert "per_call_usd does not match the shipped default" in body

    ran = _run_workflow_case(tmp_path, rates=rates, pytest_rc=0)
    assert ran["exit"] == 1, ran["stderr"]
    assert ran["python_invoked"] is True
    assert "grok-imagine-image-2.0" in ran["issue_body"]
    assert "per_call_usd does not match the shipped default" in ran["issue_body"]
    assert "This is a pytest failure" not in ran["issue_body"]
    assert UNKNOWN_FALLBACK not in ran["issue_body"]
    assert "short test summary info" not in ran["stdout"]


def test_c04_clean_pytest_and_extract_do_not_open_an_issue(tmp_path: Path) -> None:
    ran = _run_workflow_case(tmp_path, rates=_shipped_rates(), pytest_rc=0)
    assert ran["exit"] == 0, ran["stderr"]
    assert ran["python_invoked"] is True
    assert ran["gh_called"] is False
    assert ran["outputs"].get("guard_ok") == "true"
    assert ran["outputs"].get("guard_ids") == ""
    assert "short test summary info" not in ran["stdout"]


def test_c06_failures_stay_nonzero_and_commit_stays_gated(tmp_path: Path) -> None:
    watch = _load()
    rates = _shipped_rates()
    clean = tmp_path / "clean.json"
    clean.write_text(json.dumps(_extract(rates)), encoding="utf-8")
    log = tmp_path / "pytest.txt"
    log.write_text(_pytest_log(), encoding="utf-8")
    output = tmp_path / "out.txt"
    pytest_fail = watch.main(
        [
            "--guard-prices",
            str(clean),
            "--github-output",
            str(output),
            "--pytest-log",
            str(log),
            "--pytest-exit-code",
            "1",
        ]
    )
    assert pytest_fail == 1
    assert "guard_ok=false" in output.read_text(encoding="utf-8")

    mismatch = _shipped_rates()
    mismatch["grok-imagine-image-2.0"] = 0.06
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(_extract(mismatch)), encoding="utf-8")
    id_fail = watch.main(["--guard-prices", str(bad)])
    assert id_fail == 1
    omitted = watch.main(
        [
            "--guard-prices",
            str(clean),
            "--pytest-exit-code",
            "0",
        ]
    )
    assert omitted == 0

    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert (
        "if: steps.scan.outputs.exit_code != '1' && steps.guard.outcome == 'success'"
        in workflow
    )
    assert (
        "if: always() && (steps.scan.outputs.has_new == 'true' || "
        "steps.scan.outputs.has_dropped == 'true')"
    ) in workflow
    assert "--select-unlisted" in workflow
    assert "name: Commit price gap file when the extract changes" in workflow
    assert "name: Open issue for tokens not already listed" in workflow
    guard = _step_script("Guard price extract")
    assert guard.index("uv run pytest") < guard.index("--guard-prices")
    assert "set +e" in guard
    assert 'exit 1' in guard

    failed = _run_workflow_case(tmp_path / "pytest-only", rates=rates, pytest_rc=1)
    assert failed["exit"] != 0
    id_only = _run_workflow_case(
        tmp_path / "id-only",
        rates=mismatch,
        pytest_rc=0,
    )
    assert id_only["exit"] != 0


def test_workflow_shell_parses() -> None:
    blocks = _extract_run_blocks(WORKFLOW.read_text(encoding="utf-8"))
    assert blocks
    for name, script in blocks:
        proc = subprocess.run(
            ["bash", "-n"],
            input=script,
            text=True,
            capture_output=True,
            check=False,
        )
        assert proc.returncode == 0, f"{name}: {proc.stderr}"
