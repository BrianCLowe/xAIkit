"""Offline extract/diff tests for scripts/watch_xai_models.py (no network)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "watch_xai_models.py"


def _load():
    spec = importlib.util.spec_from_file_location("watch_xai_models", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_extract_slugs_and_resolutions_from_docs_like_html() -> None:
    watch = _load()
    html = """
    <td>grok-4.6</td>
    <td>grok-imagine-image-2.0</td>
    See grok-api in prose. Resolution 2k and 1080p. Four-k not listed.
    <a href="/developers/models/grok-4.5">Grok 4.5</a>
    <a href="?utm_content=highlights-grok-46">Try in playground</a>
    """
    slugs = watch.extract_slugs(html)
    assert "grok-4.6" in slugs
    assert "grok-imagine-image-2.0" in slugs
    assert "grok-4.5" in slugs
    assert "grok-api" not in slugs
    assert "grok-46" not in slugs
    assert watch.extract_resolutions(html) == ["1080p", "2k"]
    assert "grok-4-is-released" not in watch.extract_slugs(
        "heading grok-4-is-released and grok-voice-agent-api-is-released"
    )


def test_looks_like_model_slug_rejects_collapsed_dotted_utm() -> None:
    watch = _load()
    assert watch._looks_like_model_slug("grok-4.6") is True
    assert watch._looks_like_model_slug("grok-4") is True
    assert watch._looks_like_model_slug("grok-4.20-0309") is True
    assert watch._looks_like_model_slug("grok-46") is False
    assert watch._looks_like_model_slug("grok-420") is False


def test_diff_watch_reports_new_slug_and_4k() -> None:
    watch = _load()
    baseline = {
        "slugs": ["grok-4.6", "grok-imagine-image-2.0"],
        "resolutions": ["1k", "2k", "480p", "720p", "1080p"],
    }
    live = {
        "slugs": ["grok-4.6", "grok-imagine-image-2.0", "grok-imagine-image-3.0"],
        "resolutions": ["1k", "2k", "4k", "1080p"],
    }
    delta = watch.diff_watch(live, baseline)
    assert delta["slugs"] == ["grok-imagine-image-3.0"]
    assert delta["resolutions"] == ["4k"]


def test_unlisted_watch_tokens_ignore_other_open_issue_and_checklist() -> None:
    watch = _load()
    issues = [
        {
            "number": 57,
            "title": "xAI public docs added models or resolutions",
            "body": (
                "**New slugs:** `grok-voice-transcribe-1.0,grok-voice-transcribe-2.0`\n"
                "**New resolutions:** `none`\n"
                "- [ ] Imagine quality (2.0 vs later; 4k?)\n"
            ),
            "comments": "saw grok-4 in passing",
        }
    ]
    pending_slugs = watch.unlisted_watch_tokens(
        ["grok-4-7", "grok-4.7", "grok-voice-transcribe-1.0"],
        issues,
    )
    assert pending_slugs == ["grok-4-7", "grok-4.7"]
    assert watch.unlisted_watch_tokens(["4k"], issues) == ["4k"]
    assert watch.token_is_listed("grok-4", "prefix grok-4.7 suffix") is False
    assert watch.token_is_listed("grok-4.7", "prefix grok-4.7 suffix") is True


def test_comment_or_title_lists_a_token_the_body_line_omits() -> None:
    watch = _load()
    issues = [
        {
            "number": 60,
            "title": "flagship grok-4.7",
            "body": "**New slugs:** `none`\n**New resolutions:** `none`\n",
            "comments": [{"body": "also grok-voice-transcribe-2.0"}],
        }
    ]
    assert watch.unlisted_watch_tokens(
        ["grok-4.7", "grok-voice-transcribe-2.0", "grok-4-7"],
        issues,
    ) == ["grok-4-7"]


def _printed_outputs(text: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in text.splitlines():
        key, value = line.split("=", 1)
        parsed[key] = value
    return parsed


def test_already_reported_drop_opens_no_new_issue(tmp_path, capsys) -> None:
    """A drop already named on an open watch issue does not open another."""
    watch = _load()
    body = (
        "**New slugs:** `none`\n"
        "**New resolutions:** `none`\n"
        "**Dropped slugs:** `grok-retired`\n"
        "**Dropped resolutions:** `720p`\n"
        "- [ ] Imagine quality (2.0 vs later; grok-other?)\n"
    )
    issues = [
        {
            "number": 80,
            "title": "xAI public docs added models or resolutions",
            "body": body,
            "comments": "",
        }
    ]
    assert watch.unlisted_watch_tokens(["grok-other"], issues, dropped=True) == ["grok-other"]
    assert watch.declared_watch_tokens(body) >= {"grok-retired", "720p"}
    assert watch.unlisted_watch_tokens(
        ["grok-retired", "grok-legacy"], issues, dropped=True
    ) == ["grok-legacy"]
    assert watch.unlisted_watch_tokens(["720p", "4k"], issues, dropped=True) == ["4k"]

    path = tmp_path / "issues.json"
    path.write_text(json.dumps(issues), encoding="utf-8")
    code = watch.main(
        [
            "--select-unlisted",
            "--slugs", "none",
            "--resolutions", "none",
            "--dropped-slugs", "grok-retired",
            "--dropped-resolutions", "720p",
            "--issues-json", str(path),
        ]
    )
    assert code == 0
    reported = _printed_outputs(capsys.readouterr().out)
    assert reported["slugs"] == ""
    assert reported["resolutions"] == ""
    assert reported["dropped_slugs"] == ""
    assert reported["dropped_resolutions"] == ""
    assert reported["has_dropped"] == "false"

    code = watch.main(
        [
            "--select-unlisted",
            "--slugs", "none",
            "--resolutions", "none",
            "--dropped-slugs", "grok-legacy",
            "--dropped-resolutions", "4k",
            "--issues-json", str(path),
        ]
    )
    assert code == 0
    fresh = _printed_outputs(capsys.readouterr().out)
    assert fresh["dropped_slugs"] == "grok-legacy"
    assert fresh["dropped_resolutions"] == "4k"
    assert fresh["has_dropped"] == "true"

    workflow = (ROOT / ".github" / "workflows" / "watch-xai-models.yml").read_text(encoding="utf-8")
    assert "--dropped-slugs \"$DROPPED_SLUGS\"" in workflow
    assert "--dropped-resolutions \"$DROPPED_RESOLUTIONS\"" in workflow
    assert '[ "$has_dropped" != "true" ]' in workflow
    assert '[ -z "${DROPPED_SLUGS:-}" ]' not in workflow
    assert "if: always() && (steps.scan.outputs.has_new == 'true' || steps.scan.outputs.has_dropped == 'true')" in workflow


def test_guard_issue_title_does_not_suppress_dropped_token(tmp_path, capsys) -> None:
    """A price-guard issue that names an id still leaves a drift issue to file."""
    watch = _load()
    dropped = "grok-imagine-image-2.0"
    guard = {
        "number": 90,
        "title": f"xAI shipped image price guard failed: {dropped}",
        "body": (
            "The watcher extract is missing a shipped image id "
            "or its per_call_usd does not match the shipped default.\n\n"
            f"- {dropped}\n"
        ),
        "comments": f"ping {dropped}",
    }
    assert watch.unlisted_watch_tokens([dropped], [guard]) == []
    assert watch.unlisted_watch_tokens([dropped], [guard], dropped=True) == [dropped]

    path = tmp_path / "issues.json"
    path.write_text(json.dumps([guard]), encoding="utf-8")
    code = watch.main(
        [
            "--select-unlisted",
            "--slugs", "none",
            "--resolutions", "none",
            "--dropped-slugs", dropped,
            "--dropped-resolutions", "none",
            "--issues-json", str(path),
        ]
    )
    assert code == 0
    filed = _printed_outputs(capsys.readouterr().out)
    assert filed["slugs"] == ""
    assert filed["resolutions"] == ""
    assert filed["dropped_slugs"] == dropped
    assert filed["dropped_resolutions"] == ""
    assert filed["has_dropped"] == "true"

    reported = {
        "number": 80,
        "title": f"xAI public docs added models or resolutions {dropped}",
        "body": (
            "**New slugs:** `none`\n"
            "**New resolutions:** `none`\n"
            f"**Dropped slugs:** `{dropped}`\n"
            "**Dropped resolutions:** `none`\n"
        ),
        "comments": "",
    }
    path.write_text(json.dumps([guard, reported]), encoding="utf-8")
    code = watch.main(
        [
            "--select-unlisted",
            "--slugs", "none",
            "--resolutions", "none",
            "--dropped-slugs", dropped,
            "--dropped-resolutions", "none",
            "--issues-json", str(path),
        ]
    )
    assert code == 0
    quiet = _printed_outputs(capsys.readouterr().out)
    assert quiet["dropped_slugs"] == ""
    assert quiet["has_dropped"] == "false"


def test_select_unlisted_cli_prints_only_new_tokens(tmp_path, capsys) -> None:
    watch = _load()
    path = tmp_path / "issues.json"
    path.write_text(
        '[{"number": 57, "title": "watch", "body": "**New slugs:** `grok-4.6`", "comments": ""}]',
        encoding="utf-8",
    )
    code = watch.main(
        [
            "--select-unlisted",
            "--slugs", "grok-4.6,grok-4.7,none",
            "--resolutions", "4k",
            "--issues-json",
            str(path),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "slugs=grok-4.7" in out
    assert "resolutions=4k" in out


def test_extract_public_prices_prefers_us_east_and_scales() -> None:
    watch = _load()
    blob = {
        "clusterConfigs": [
            {
                "clusterName": "us-central-1",
                "languageModels": [
                    {
                        "name": "grok-4.7",
                        "promptTextTokenPrice": "22000",
                        "completionTextTokenPrice": "66000",
                    }
                ],
            },
            {
                "clusterName": "us-east-1",
                "languageModels": [
                    {
                        "name": "grok-4.7",
                        "promptTextTokenPrice": "20000",
                        "completionTextTokenPrice": "60000",
                        "cachedPromptTokenPrice": "5000",
                        "promptTextTokenPriceLongContext": "40000",
                        "completionTokenPriceLongContext": "120000",
                    }
                ],
                "imageGenerationModels": [
                    {"name": "grok-imagine-image-quality", "imagePrice": "500000000"}
                ],
                "videoGenerationModels": [
                    {
                        "name": "grok-imagine-video-1.5",
                        "resolutionPricing": [
                            {"resolution": "VIDEO_RESOLUTION_480P", "pricePerSecond": "800000000"},
                            {"resolution": "VIDEO_RESOLUTION_720P", "pricePerSecond": "1400000000"},
                        ],
                    }
                ],
                "audioModels": [
                    {
                        "name": "grok-voice-transcribe-1.0",
                        "endpoints": [
                            {
                                "pricing": {
                                    "perAudioSecond": "277778",
                                    "perAudioSecondStreaming": "555556",
                                }
                            }
                        ],
                    },
                    {
                        "name": "grok-voice-think-fast-2.0",
                        "aliases": ["grok-voice-latest"],
                        "endpoints": [
                            {"pricing": {"realtimeAudioSecondPrice": "13333333"}}
                        ],
                    },
                ],
            },
        ]
    }
    import json

    html = f"<script>globalThis.__XAI_PUBLIC_MODELS__={json.dumps(blob)};</script>"
    prices = watch.extract_public_prices(
        {"https://docs.x.ai/developers/models": html}
    )
    flagship = prices["models"]["grok-4.7"]
    assert flagship["input_per_million"] == 2.0
    assert flagship["output_per_million"] == 6.0
    assert flagship["cached_input_per_million"] == 0.5
    assert flagship["input_long_per_million"] == 4.0
    assert prices["models"]["grok-imagine-image-quality"]["per_call_usd"] == 0.05
    video = prices["models"]["grok-imagine-video-1.5"]
    assert video["per_second_usd"] == 0.08
    assert video["per_second_usd_by_resolution"]["720p"] == 0.14
    assert prices["models"]["grok-voice-latest"]["per_minute_usd"] == 0.08
    assert prices["models"]["stt"]["per_minute_usd"] == round(555556 / 10_000_000_000 * 60, 8)


def test_language_zero_token_side_is_kept() -> None:
    watch = _load()
    priced = watch._language_price(
        {"promptTextTokenPrice": "0", "completionTextTokenPrice": "60000"}
    )
    assert priced["input_per_million"] == 0.0
    assert priced["output_per_million"] == 6.0
    assert watch._language_price({"completionTextTokenPrice": "60000"}) == {}


def test_write_public_prices_refuses_empty_extract(tmp_path) -> None:
    watch = _load()
    path = tmp_path / "xai_public_prices.json"
    path.write_text('{"models": {"keep-me": {}}}\n', encoding="utf-8")
    changed = watch.write_public_prices(
        path,
        {"https://docs.x.ai/developers/models": "<html>no blob</html>"},
    )
    assert changed is None
    assert "keep-me" in path.read_text(encoding="utf-8")


def test_committed_public_prices_parse() -> None:
    import json

    raw = json.loads((ROOT / "scripts" / "data" / "xai_public_prices.json").read_text(encoding="utf-8"))
    models = raw["models"]
    assert models["grok-4.7"]["input_per_million"] > 0
    assert models["grok-4.7"]["output_per_million"] > 0
    video = models["grok-imagine-video-1.5"]["per_second_usd_by_resolution"]
    assert video["480p"] > 0
    assert models["stt"]["per_minute_usd"] > 0


def _github_outputs(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in text.splitlines():
        key, value = line.split("=", 1)
        found[key] = value
    return found


def _run_offline_main(watch, tmp_path, monkeypatch, live: dict, baseline: dict):
    baseline_path = tmp_path / "baseline.json"
    payload = json.dumps(baseline)
    baseline_path.write_text(payload, encoding="utf-8")
    output_path = tmp_path / "github_output.txt"
    repo_baseline = (ROOT / "scripts" / "data" / "xai_models_watch.json").read_bytes()
    repo_prices = (ROOT / "scripts" / "data" / "xai_public_prices.json").read_bytes()

    def fake_fetch(url: str, *, timeout: float = 30.0) -> str:
        return "offline"

    def fake_scan(pages, **kwargs):
        return live

    monkeypatch.setattr(watch, "fetch_text", fake_fetch)
    monkeypatch.setattr(watch, "scan_pages", fake_scan)
    code = watch.main(
        ["--baseline", str(baseline_path), "--github-output", str(output_path)]
    )
    written = output_path.read_text(encoding="utf-8")
    assert baseline_path.read_text(encoding="utf-8") == payload
    assert (ROOT / "scripts" / "data" / "xai_models_watch.json").read_bytes() == repo_baseline
    assert (ROOT / "scripts" / "data" / "xai_public_prices.json").read_bytes() == repo_prices
    return code, _github_outputs(written)


def test_diff_watch_reports_dropped_slugs_and_resolutions() -> None:
    watch = _load()
    baseline = {
        "slugs": ["grok-4.6", "Grok-Kept", "grok-retired", "grok-legacy"],
        "resolutions": ["1k", "480P", "720p"],
    }
    live = {
        "slugs": ["grok-4.6", "grok-kept", "grok-imagine-image-3.0"],
        "resolutions": ["1k", "480p", "4k"],
    }
    delta = watch.diff_watch(live, baseline)
    assert delta["slugs"] == ["grok-imagine-image-3.0"]
    assert delta["resolutions"] == ["4k"]
    assert delta["dropped_slugs"] == ["grok-retired", "grok-legacy"]
    assert delta["dropped_resolutions"] == ["720p"]


def test_main_writes_dropped_outputs_and_exits_2(tmp_path, monkeypatch, capsys) -> None:
    watch = _load()
    code, outputs = _run_offline_main(
        watch,
        tmp_path,
        monkeypatch,
        live={"slugs": ["grok-4.6"], "resolutions": ["1k"]},
        baseline={
            "slugs": ["grok-4.6", "grok-retired"],
            "resolutions": ["1k", "720p"],
        },
    )
    assert code == 2
    assert outputs["dropped_slugs"] == "grok-retired"
    assert outputs["dropped_resolutions"] == "720p"
    assert outputs["has_dropped"] == "true"
    assert outputs["has_new"] == "false"
    assert outputs["new_slugs"] == ""
    assert outputs["new_resolutions"] == ""
    stdout = capsys.readouterr().out
    assert "grok-retired" in stdout
    assert "720p" in stdout
    assert "Dropped xAI public-docs tokens" in stdout


def test_main_no_drop_outputs_false_and_exits_0(tmp_path, monkeypatch, capsys) -> None:
    watch = _load()
    live = {
        "slugs": ["grok-4.6", "grok-imagine-image-2.0"],
        "resolutions": ["1k", "720p"],
    }
    code, outputs = _run_offline_main(
        watch,
        tmp_path,
        monkeypatch,
        live=live,
        baseline=dict(live),
    )
    assert code == 0
    assert outputs["dropped_slugs"] == ""
    assert outputs["dropped_resolutions"] == ""
    assert outputs["has_dropped"] == "false"
    assert outputs["has_new"] == "false"
    stdout = capsys.readouterr().out
    assert "xAI public docs match the committed watch baseline" in stdout


def test_main_new_and_dropped_both_reported(tmp_path, monkeypatch, capsys) -> None:
    watch = _load()
    code, outputs = _run_offline_main(
        watch,
        tmp_path,
        monkeypatch,
        live={
            "slugs": ["grok-4.6", "grok-imagine-image-3.0"],
            "resolutions": ["1k", "4k"],
        },
        baseline={
            "slugs": ["grok-4.6", "grok-retired"],
            "resolutions": ["1k", "720p"],
        },
    )
    assert code == 2
    assert outputs["has_new"] == "true"
    assert outputs["has_dropped"] == "true"
    assert outputs["new_slugs"] == "grok-imagine-image-3.0"
    assert outputs["new_resolutions"] == "4k"
    assert outputs["dropped_slugs"] == "grok-retired"
    assert outputs["dropped_resolutions"] == "720p"
    stdout = capsys.readouterr().out
    assert "New xAI public-docs signals" in stdout
    assert "Dropped xAI public-docs tokens" in stdout
    assert "grok-imagine-image-3.0" in stdout
    assert "4k" in stdout
    assert "grok-retired" in stdout
    assert "720p" in stdout


def test_committed_baseline_has_current_public_table() -> None:
    watch = _load()
    baseline = watch.load_baseline(watch.BASELINE_PATH)
    slugs = set(baseline["slugs"])
    assert "grok-4.6" in slugs
    assert "grok-imagine-image-2.0" in slugs
    assert "1k" in baseline["resolutions"]
    assert "4k" not in baseline["resolutions"]
