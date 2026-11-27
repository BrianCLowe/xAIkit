"""Offline extract/diff tests for scripts/watch_xai_models.py (no network)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import urllib.error
from datetime import datetime
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
            "--pending", str(tmp_path / "pending.json"),
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
            "--pending", str(tmp_path / "pending.json"),
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
            "--pending", str(tmp_path / "pending.json"),
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
            "--pending", str(tmp_path / "pending.json"),
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
            "--pending",
            str(tmp_path / "pending.json"),
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


def _image_model_price(watch, row: dict) -> dict:
    blob = {
        "clusterConfigs": [
            {
                "clusterName": "us-east-1",
                "imageGenerationModels": [row],
            }
        ]
    }
    html = "<script>globalThis.__XAI_PUBLIC_MODELS__=" + json.dumps(blob) + ";</script>"
    prices = watch.extract_public_prices({"https://docs.x.ai/developers/models": html})
    return prices["models"][row["name"]]


def test_image_price_prefers_1k_low_over_image_price() -> None:
    watch = _load()
    priced = _image_model_price(
        watch,
        {
            "name": "grok-imagine-image-2.0",
            "imagePrice": "600000000",
            "resolutionPricing": [
                {
                    "resolution": "IMAGE_RESOLUTION_1K",
                    "quality": "low",
                    "pricePerImage": "400000000",
                }
            ],
        },
    )
    assert priced == {
        "input_per_million": 0.0,
        "output_per_million": 0.0,
        "per_call_usd": 0.04,
    }


def test_image_price_falls_back_to_image_price_when_no_1k_tier() -> None:
    watch = _load()
    priced = _image_model_price(
        watch,
        {"name": "grok-imagine-image-quality", "imagePrice": "500000000"},
    )
    assert priced == {
        "input_per_million": 0.0,
        "output_per_million": 0.0,
        "per_call_usd": 0.05,
    }


def test_image_price_parses_image_resolution_1k_key() -> None:
    watch = _load()
    assert watch._resolution_key("IMAGE_RESOLUTION_1K") == "1k"
    assert watch._resolution_key("VIDEO_RESOLUTION_720P") == "720p"
    priced = _image_model_price(
        watch,
        {
            "name": "grok-imagine-image-2.0",
            "imagePrice": "600000000",
            "resolutionPricing": [
                {
                    "resolution": "IMAGE_RESOLUTION_1K",
                    "quality": "low",
                    "pricePerImage": "400000000",
                }
            ],
        },
    )
    assert priced["per_call_usd"] == 0.04


def test_image_price_uses_no_quality_1k_row() -> None:
    watch = _load()
    priced = _image_model_price(
        watch,
        {
            "name": "grok-imagine-image",
            "imagePrice": "600000000",
            "resolutionPricing": [
                {"resolution": "IMAGE_RESOLUTION_1K", "pricePerImage": "200000000"}
            ],
        },
    )
    assert priced == {
        "input_per_million": 0.0,
        "output_per_million": 0.0,
        "per_call_usd": 0.02,
    }


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


def _run_offline_main(
    watch, tmp_path, monkeypatch, live: dict, baseline: dict, pending_path=None
):
    if pending_path is None:
        pending_path = tmp_path / "pending.json"
    baseline_path = tmp_path / "baseline.json"
    payload = json.dumps(baseline)
    baseline_path.write_text(payload, encoding="utf-8")
    output_path = tmp_path / "github_output.txt"
    repo_baseline = (ROOT / "scripts" / "data" / "xai_models_watch.json").read_bytes()
    repo_prices = (ROOT / "scripts" / "data" / "xai_public_prices.json").read_bytes()
    repo_pending = ROOT / "scripts" / "data" / "xai_models_watch_pending.json"
    repo_pending_bytes = repo_pending.read_bytes() if repo_pending.is_file() else None

    def fake_fetch(url: str, *, timeout: float = 30.0) -> str:
        return "offline"

    def fake_scan(pages, **kwargs):
        return live

    monkeypatch.setattr(watch, "fetch_text", fake_fetch)
    monkeypatch.setattr(watch, "scan_pages", fake_scan)
    code = watch.main(
        [
            "--baseline",
            str(baseline_path),
            "--github-output",
            str(output_path),
            "--pending",
            str(pending_path),
        ]
    )
    written = output_path.read_text(encoding="utf-8")
    assert baseline_path.read_text(encoding="utf-8") == payload
    assert (ROOT / "scripts" / "data" / "xai_models_watch.json").read_bytes() == repo_baseline
    assert (ROOT / "scripts" / "data" / "xai_public_prices.json").read_bytes() == repo_prices
    after_pending = repo_pending.read_bytes() if repo_pending.is_file() else None
    assert after_pending == repo_pending_bytes
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
    assert code != 2
    assert outputs["dropped_slugs"] == ""
    assert outputs["dropped_resolutions"] == ""
    assert outputs["has_dropped"] == "false"
    assert outputs["has_new"] == "false"
    assert outputs["new_slugs"] == ""
    assert outputs["new_resolutions"] == ""
    stdout = capsys.readouterr().out
    assert "Dropped xAI public-docs tokens" not in stdout
    assert "dropped slugs:" not in stdout
    assert "dropped resolutions:" not in stdout
    assert "xAI public docs match the committed watch baseline" not in stdout
    assert (
        "xAI public docs watch pending: first-miss 720p,grok-retired; still-absent none"
        in stdout
    )


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
    assert outputs["has_dropped"] == "false"
    assert outputs["new_slugs"] == "grok-imagine-image-3.0"
    assert outputs["new_resolutions"] == "4k"
    assert outputs["dropped_slugs"] == ""
    assert outputs["dropped_resolutions"] == ""
    stdout = capsys.readouterr().out
    assert "New xAI public-docs signals" in stdout
    assert "Dropped xAI public-docs tokens" not in stdout
    assert "dropped slugs:" not in stdout
    assert "dropped resolutions:" not in stdout
    assert "grok-imagine-image-3.0" in stdout
    assert "4k" in stdout
    assert (
        "xAI public docs watch pending: first-miss 720p,grok-retired; still-absent none"
        in stdout
    )


def test_committed_baseline_has_current_public_table() -> None:
    watch = _load()
    baseline = watch.load_baseline(watch.BASELINE_PATH)
    slugs = set(baseline["slugs"])
    assert "grok-4.6" in slugs
    assert "grok-imagine-image-2.0" in slugs
    assert "1k" in baseline["resolutions"]
    assert "4k" not in baseline["resolutions"]


def _stamp_ok(value: str) -> bool:
    if len(value) != 20:
        return False
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


def _read_pending(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_xts_c1_first_miss_not_reported(tmp_path, monkeypatch) -> None:
    """C1 and C10.2: a missing pending file records the first miss and does not report it."""
    watch = _load()
    baseline = {
        "slugs": ["grok-4.6", "grok-retired"],
        "resolutions": ["1k", "720p"],
    }
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    output_path = tmp_path / "github_output.txt"
    pending_path = tmp_path / "pending.json"

    def fake_fetch(url, *, timeout=30.0):
        return "offline"

    def fake_scan(pages, **kwargs):
        return {"slugs": ["grok-4.6"], "resolutions": ["1k"]}

    monkeypatch.setattr(watch, "fetch_text", fake_fetch)
    monkeypatch.setattr(watch, "scan_pages", fake_scan)
    code = watch.main(
        [
            "--baseline",
            str(baseline_path),
            "--github-output",
            str(output_path),
            "--pending",
            str(pending_path),
        ]
    )
    outputs = _github_outputs(output_path.read_text(encoding="utf-8"))
    dropped_slugs = outputs["dropped_slugs"].split(",") if outputs["dropped_slugs"] else []
    dropped_resolutions = (
        outputs["dropped_resolutions"].split(",") if outputs["dropped_resolutions"] else []
    )
    failures = []
    if "grok-retired" in dropped_slugs or "720p" in dropped_resolutions:
        failures.append("first-miss token in dropped_*")
    if outputs["has_dropped"] != "false":
        failures.append("has_dropped")
    if code == 2:
        failures.append("exit 2")
    assert failures == []
    state = _read_pending(pending_path)
    assert set(state) == {"resolutions", "slugs"}
    assert set(state["slugs"]) == {"grok-retired"}
    assert set(state["resolutions"]) == {"720p"}
    assert set(state["slugs"]["grok-retired"]) == {"first_miss"}
    assert set(state["resolutions"]["720p"]) == {"first_miss"}
    assert _stamp_ok(state["slugs"]["grok-retired"]["first_miss"])
    assert _stamp_ok(state["resolutions"]["720p"]["first_miss"])
    assert outputs["scan_ok"] == "true"
    assert code == 0
    assert "grok-imagine" not in pending_path.read_text(encoding="utf-8")


def test_xts_c2_second_miss_reported(tmp_path, monkeypatch) -> None:
    watch = _load()
    pending = tmp_path / "pending.json"
    live = {"slugs": ["grok-4.6"], "resolutions": ["1k"]}
    baseline = {
        "slugs": ["grok-4.6", "grok-retired"],
        "resolutions": ["1k", "720p"],
    }
    code, outputs = _run_offline_main(
        watch, tmp_path, monkeypatch, live, baseline, pending_path=pending
    )
    assert code != 2
    assert outputs["has_dropped"] == "false"
    first_slug = _read_pending(pending)["slugs"]["grok-retired"]["first_miss"]
    first_res = _read_pending(pending)["resolutions"]["720p"]["first_miss"]
    code, outputs = _run_offline_main(
        watch, tmp_path, monkeypatch, live, baseline, pending_path=pending
    )
    assert code == 2
    assert outputs["dropped_slugs"] == "grok-retired"
    assert outputs["dropped_resolutions"] == "720p"
    assert outputs["has_dropped"] == "true"
    assert outputs["scan_ok"] == "true"
    state = _read_pending(pending)
    assert state["slugs"]["grok-retired"]["first_miss"] == first_slug
    assert state["resolutions"]["720p"]["first_miss"] == first_res
    assert "reported_at" not in state["slugs"]["grok-retired"]
    assert "reported_at" not in state["resolutions"]["720p"]


def test_xts_c3_reappearance_clears_pending(tmp_path, monkeypatch) -> None:
    watch = _load()
    pending = tmp_path / "pending.json"
    pending.write_text(
        watch.dump_pending(
            {
                "slugs": {"grok-retired": {"first_miss": "2026-11-25T01:00:00Z"}},
                "resolutions": {"720p": {"first_miss": "2026-11-25T01:00:00Z"}},
            }
        ),
        encoding="utf-8",
    )
    live = {
        "slugs": ["grok-4.6", "grok-retired"],
        "resolutions": ["1k", "720p"],
    }
    baseline = dict(live)
    code, outputs = _run_offline_main(
        watch, tmp_path, monkeypatch, live, baseline, pending_path=pending
    )
    assert code == 0
    assert outputs["dropped_slugs"] == ""
    assert outputs["dropped_resolutions"] == ""
    assert outputs["has_dropped"] == "false"
    assert pending.read_bytes() == b"{}\n"


def test_xts_c4_prune_token_outside_baseline(tmp_path, monkeypatch) -> None:
    watch = _load()
    pending = tmp_path / "pending.json"
    pending.write_text(
        watch.dump_pending(
            {
                "slugs": {
                    "grok-ghost": {"first_miss": "2026-11-25T01:00:00Z"},
                    "grok-reported": {
                        "first_miss": "2026-11-25T01:00:00Z",
                        "reported_at": "2026-11-25T01:05:00Z",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    live = {"slugs": ["grok-4.6"], "resolutions": ["1k"]}
    baseline = {"slugs": ["grok-4.6"], "resolutions": ["1k"]}
    code, outputs = _run_offline_main(
        watch, tmp_path, monkeypatch, live, baseline, pending_path=pending
    )
    assert code == 0
    assert outputs["has_dropped"] == "false"
    assert pending.read_bytes() == b"{}\n"


def test_xts_c4_write_baseline_prunes_removed(tmp_path, monkeypatch) -> None:
    watch = _load()
    pending = tmp_path / "pending.json"
    baseline_path = tmp_path / "baseline.json"
    output_path = tmp_path / "out.txt"
    old = {
        "source_urls": ["https://example.invalid/models"],
        "slugs": ["grok-4.6", "grok-retired", "grok-kept"],
        "resolutions": ["1k", "1080p"],
    }
    baseline_path.write_text(json.dumps(old, indent=2) + "\n", encoding="utf-8")
    pending.write_text(
        watch.dump_pending(
            {
                "slugs": {
                    "grok-retired": {"first_miss": "2026-11-25T01:00:00Z"},
                    "grok-kept": {"first_miss": "2026-11-25T01:00:00Z"},
                    "grok-ghost": {"first_miss": "2026-11-25T01:00:00Z"},
                },
                "resolutions": {
                    "1080p": {
                        "first_miss": "2026-11-25T01:00:00Z",
                        "reported_at": "2026-11-25T01:05:00Z",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    def fake_fetch(url, *, timeout=30.0):
        return "offline"

    def fake_scan(pages, **kwargs):
        return {"slugs": ["grok-4.6", "grok-kept"], "resolutions": ["1k"]}

    monkeypatch.setattr(watch, "fetch_text", fake_fetch)
    monkeypatch.setattr(watch, "scan_pages", fake_scan)
    code = watch.main(
        [
            "--baseline",
            str(baseline_path),
            "--pending",
            str(pending),
            "--github-output",
            str(output_path),
            "--write-baseline",
        ]
    )
    assert code == 0
    written = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert written["slugs"] == ["grok-4.6", "grok-kept"]
    assert written["resolutions"] == ["1k"]
    assert "grok-retired" not in written["slugs"]
    assert pending.read_bytes() == b"{}\n"
    assert _github_outputs(output_path.read_text(encoding="utf-8"))["scan_ok"] == "true"


def test_xts_c4_fetch_failure_leaves_pending_byte_identical(tmp_path, monkeypatch) -> None:
    watch = _load()
    pending = tmp_path / "pending.json"
    body = watch.dump_pending(
        {"slugs": {"grok-retired": {"first_miss": "2026-11-25T01:00:00Z"}}}
    )
    pending.write_text(body, encoding="utf-8")
    before = pending.read_bytes()
    digest = hashlib.sha256(before).hexdigest()
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_bytes(b"KEEP\n")
    output_path = tmp_path / "out.txt"
    errors = (
        urllib.error.URLError("offline"),
        TimeoutError("timed out"),
        OSError("reset"),
    )
    for exc in errors:
        output_path.write_bytes(b"")

        def fake_fetch(url, *, timeout=30.0, exc=exc):
            raise exc

        monkeypatch.setattr(watch, "fetch_text", fake_fetch)
        code = watch.main(
            [
                "--baseline",
                str(baseline_path),
                "--pending",
                str(pending),
                "--github-output",
                str(output_path),
                "--write-baseline",
            ]
        )
        assert code == 1
        assert hashlib.sha256(pending.read_bytes()).hexdigest() == digest
        assert pending.read_bytes() == before
        assert baseline_path.read_bytes() == b"KEEP\n"
        assert _github_outputs(output_path.read_text(encoding="utf-8"))["scan_ok"] == "false"

    missing = tmp_path / "missing-pending.json"
    output_path.write_bytes(b"")

    def fail_fetch(url, *, timeout=30.0):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(watch, "fetch_text", fail_fetch)
    code = watch.main(
        [
            "--baseline",
            str(baseline_path),
            "--pending",
            str(missing),
            "--github-output",
            str(output_path),
        ]
    )
    assert code == 1
    assert not missing.exists()
    assert baseline_path.read_bytes() == b"KEEP\n"


def test_xts_c4_fetch_gap_does_not_reset_the_count(tmp_path, monkeypatch) -> None:
    watch = _load()
    pending = tmp_path / "pending.json"
    baseline = {
        "slugs": ["grok-4.6", "grok-retired"],
        "resolutions": ["1k", "720p"],
    }
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    output_path = tmp_path / "out.txt"
    mode = {"name": "miss"}

    def fake_fetch(url, *, timeout=30.0):
        if mode["name"] == "fail":
            raise TimeoutError("timed out")
        return "offline"

    def fake_scan(pages, **kwargs):
        if mode["name"] == "present":
            return {
                "slugs": ["grok-4.6", "grok-retired"],
                "resolutions": ["1k", "720p"],
            }
        return {"slugs": ["grok-4.6"], "resolutions": ["1k"]}

    monkeypatch.setattr(watch, "fetch_text", fake_fetch)
    monkeypatch.setattr(watch, "scan_pages", fake_scan)

    def run():
        output_path.write_text("", encoding="utf-8")
        code = watch.main(
            [
                "--baseline",
                str(baseline_path),
                "--github-output",
                str(output_path),
                "--pending",
                str(pending),
            ]
        )
        return code, _github_outputs(output_path.read_text(encoding="utf-8"))

    code, _outputs = run()
    assert code != 2
    snap = pending.read_bytes()
    mode["name"] = "fail"
    code, outputs = run()
    assert code == 1
    assert outputs["scan_ok"] == "false"
    assert pending.read_bytes() == snap
    mode["name"] = "miss"
    code, outputs = run()
    assert code == 2
    assert outputs["dropped_slugs"] == "grok-retired"
    assert outputs["dropped_resolutions"] == "720p"
    assert outputs["has_dropped"] == "true"
    assert "reported_at" not in pending.read_text(encoding="utf-8")

    pending.unlink()
    mode["name"] = "miss"
    run()
    assert "grok-retired" in pending.read_text(encoding="utf-8")
    snap = pending.read_bytes()
    mode["name"] = "fail"
    run()
    assert pending.read_bytes() == snap
    mode["name"] = "present"
    code, outputs = run()
    assert code == 0
    assert outputs["has_dropped"] == "false"
    assert "grok-retired" not in pending.read_text(encoding="utf-8")
    assert pending.read_bytes() == b"{}\n"


def _bind_pages(watch, monkeypatch, pages: dict[str, str]) -> None:
    def fake_fetch(url, *, timeout=30.0):
        if url not in pages:
            raise OSError(url)
        return pages[url]

    monkeypatch.setattr(watch, "fetch_text", fake_fetch)


def _run_pages(watch, tmp_path, pages, baseline, pending: Path, extra=None):
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    output_path = tmp_path / "out.txt"
    argv = [
        "--baseline",
        str(baseline_path),
        "--github-output",
        str(output_path),
        "--pending",
        str(pending),
    ]
    if extra:
        argv.extend(extra)
    code = watch.main(argv)
    outputs = _github_outputs(output_path.read_text(encoding="utf-8"))
    return code, outputs


def test_xts_c4_3b_slug_parse_failure_keeps_slug_pending(tmp_path, monkeypatch) -> None:
    watch = _load()
    pending = tmp_path / "pending.json"
    seeded = {
        "slugs": {
            "grok-retired": {"first_miss": "2026-11-25T01:00:00Z"},
            "grok-reported": {
                "first_miss": "2026-11-25T01:00:00Z",
                "reported_at": "2026-11-25T01:05:00Z",
            },
        },
        "resolutions": {"720p": {"first_miss": "2026-11-25T01:00:00Z"}},
    }
    pending.write_text(watch.dump_pending(seeded), encoding="utf-8")
    pages = {
        watch.SLUG_URLS[0]: "no model sku here",
        watch.SLUG_URLS[1]: "still no model sku",
        watch.RESOLUTION_URLS[0]: "frame 1k",
        watch.RESOLUTION_URLS[1]: "frame 720p",
    }
    _bind_pages(watch, monkeypatch, pages)
    code, outputs = _run_pages(
        watch,
        tmp_path,
        pages,
        {"slugs": ["grok-4.6", "grok-retired"], "resolutions": ["1k", "720p", "1080p"]},
        pending,
    )
    state = _read_pending(pending)
    assert state["slugs"] == seeded["slugs"]
    assert "720p" not in state.get("resolutions", {})
    assert set(state["resolutions"]["1080p"]) == {"first_miss"}
    assert outputs["dropped_slugs"] == ""
    assert outputs["dropped_resolutions"] == ""
    assert outputs["has_dropped"] == "false"
    assert outputs["scan_ok"] == "true"
    assert code == 0


def test_xts_c4_3b_resolution_parse_failure_keeps_resolution_pending(tmp_path, monkeypatch) -> None:
    watch = _load()
    pending = tmp_path / "pending.json"
    seeded = {
        "slugs": {"grok-4.6": {"first_miss": "2026-11-25T01:00:00Z"}},
        "resolutions": {
            "1080p": {"first_miss": "2026-11-25T01:00:00Z"},
            "720p": {
                "first_miss": "2026-11-25T01:00:00Z",
                "reported_at": "2026-11-25T01:05:00Z",
            },
        },
    }
    pending.write_text(watch.dump_pending(seeded), encoding="utf-8")
    pages = {
        watch.SLUG_URLS[0]: "grok-4.6",
        watch.SLUG_URLS[1]: "grok-4.6",
        watch.RESOLUTION_URLS[0]: "no frame size",
        watch.RESOLUTION_URLS[1]: "still no frame size",
    }
    _bind_pages(watch, monkeypatch, pages)
    code, outputs = _run_pages(
        watch,
        tmp_path,
        pages,
        {"slugs": ["grok-4.6", "grok-retired"], "resolutions": ["1k", "1080p"]},
        pending,
    )
    state = _read_pending(pending)
    assert state["resolutions"] == seeded["resolutions"]
    assert "grok-4.6" not in state.get("slugs", {})
    assert set(state["slugs"]["grok-retired"]) == {"first_miss"}
    assert outputs["dropped_slugs"] == ""
    assert outputs["dropped_resolutions"] == ""
    assert outputs["scan_ok"] == "true"
    assert code == 0


def test_xts_c4_3b_extractor_exception_updates_other_side(tmp_path, monkeypatch) -> None:
    watch = _load()
    pending = tmp_path / "pending.json"
    seeded = {"slugs": {"grok-retired": {"first_miss": "2026-11-25T01:00:00Z"}}}
    pending.write_text(watch.dump_pending(seeded), encoding="utf-8")

    def boom(_text):
        raise RuntimeError("slug parse")

    monkeypatch.setattr(watch, "extract_slugs", boom)
    pages = {
        watch.SLUG_URLS[0]: "grok-4.6",
        watch.SLUG_URLS[1]: "grok-4.6",
        watch.RESOLUTION_URLS[0]: "frame 1k",
        watch.RESOLUTION_URLS[1]: "frame 1k",
    }
    _bind_pages(watch, monkeypatch, pages)
    code, outputs = _run_pages(
        watch,
        tmp_path,
        pages,
        {"slugs": ["grok-4.6", "grok-retired"], "resolutions": ["1k", "1080p"]},
        pending,
    )
    state = _read_pending(pending)
    assert state["slugs"] == seeded["slugs"]
    assert set(state["resolutions"]["1080p"]) == {"first_miss"}
    assert outputs["dropped_slugs"] == ""
    assert outputs["scan_ok"] == "true"
    assert code == 0


def test_xts_c4_3b_both_sides_fail_is_not_a_scan(tmp_path, monkeypatch) -> None:
    watch = _load()
    pending = tmp_path / "pending.json"
    body = watch.dump_pending(
        {"slugs": {"grok-retired": {"first_miss": "2026-11-25T01:00:00Z"}}}
    )
    pending.write_text(body, encoding="utf-8")
    before = pending.read_bytes()
    pages = {url: "nothing to parse" for url in watch.WATCH_URLS}
    _bind_pages(watch, monkeypatch, pages)
    code, outputs = _run_pages(
        watch,
        tmp_path,
        pages,
        {"slugs": ["grok-4.6", "grok-retired"], "resolutions": ["1k"]},
        pending,
    )
    assert code == 1
    assert outputs["scan_ok"] == "false"
    assert outputs["dropped_slugs"] == ""
    assert outputs["dropped_resolutions"] == ""
    assert outputs["has_dropped"] == "false"
    assert pending.read_bytes() == before
    assert hashlib.sha256(pending.read_bytes()).hexdigest() == hashlib.sha256(before).hexdigest()

    missing = tmp_path / "absent.json"
    code, outputs = _run_pages(
        watch,
        tmp_path,
        pages,
        {"slugs": ["grok-4.6"], "resolutions": ["1k"]},
        missing,
    )
    assert code == 1
    assert outputs["scan_ok"] == "false"
    assert not missing.exists()


def test_xts_c5_1_new_tokens_reported_and_not_pending(tmp_path, monkeypatch) -> None:
    watch = _load()
    pending = tmp_path / "pending.json"
    live = {
        "slugs": ["grok-4.6", "grok-imagine-image-3.0"],
        "resolutions": ["1k", "4k"],
    }
    baseline = {"slugs": ["grok-4.6"], "resolutions": ["1k"]}
    code, outputs = _run_offline_main(
        watch, tmp_path, monkeypatch, live, baseline, pending_path=pending
    )
    assert code == 2
    assert outputs["has_new"] == "true"
    assert outputs["new_slugs"] == "grok-imagine-image-3.0"
    assert outputs["new_resolutions"] == "4k"
    assert outputs["has_dropped"] == "false"
    assert pending.read_bytes() == b"{}\n"
    assert "grok-imagine-image-3.0" not in pending.read_text(encoding="utf-8")
    assert "4k" not in pending.read_text(encoding="utf-8")

    pending.write_text(
        watch.dump_pending(
            {
                "slugs": {
                    "grok-retired": {
                        "first_miss": "2026-11-25T01:00:00Z",
                        "reported_at": "2026-11-25T01:05:00Z",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    live_gap = {
        "slugs": ["grok-4.6", "grok-imagine-image-3.0"],
        "resolutions": ["1k", "4k"],
    }
    baseline_gap = {
        "slugs": ["grok-4.6", "grok-retired"],
        "resolutions": ["1k"],
    }
    code, outputs = _run_offline_main(
        watch, tmp_path, monkeypatch, live_gap, baseline_gap, pending_path=pending
    )
    assert code == 2
    assert outputs["new_slugs"] == "grok-imagine-image-3.0"
    assert outputs["new_resolutions"] == "4k"
    assert outputs["dropped_slugs"] == ""
    text = pending.read_text(encoding="utf-8")
    assert "grok-imagine-image-3.0" not in text
    assert "4k" not in text
    assert "grok-retired" in text


def test_xts_c9_prices_failed_still_updates_pending(tmp_path, monkeypatch) -> None:
    watch = _load()
    pending = tmp_path / "pending.json"
    pending.write_text(
        watch.dump_pending({"slugs": {"grok-kept": {"first_miss": "2026-11-25T01:00:00Z"}}}),
        encoding="utf-8",
    )
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps(
            {"slugs": ["grok-4.6", "grok-kept", "grok-retired"], "resolutions": ["1k"]}
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "out.txt"

    def fake_fetch(url, *, timeout=30.0):
        return "offline"

    def fake_scan(pages, **kwargs):
        return {"slugs": ["grok-4.6", "grok-kept"], "resolutions": ["1k"]}

    monkeypatch.setattr(watch, "fetch_text", fake_fetch)
    monkeypatch.setattr(watch, "scan_pages", fake_scan)
    monkeypatch.setattr(watch, "write_public_prices", lambda path, pages: None)
    code = watch.main(
        [
            "--baseline",
            str(baseline_path),
            "--pending",
            str(pending),
            "--github-output",
            str(output_path),
            "--write-prices",
            str(tmp_path / "prices.json"),
        ]
    )
    outputs = _github_outputs(output_path.read_text(encoding="utf-8"))
    assert code == 1
    assert outputs["scan_ok"] == "true"
    assert outputs["has_dropped"] == "false"
    assert outputs["dropped_slugs"] == ""
    state = _read_pending(pending)
    assert "grok-kept" not in state.get("slugs", {})
    assert set(state["slugs"]["grok-retired"]) == {"first_miss"}


def test_xts_c10_clean_scan_writes_empty_object(tmp_path, monkeypatch) -> None:
    watch = _load()
    pending = tmp_path / "pending.json"
    live = {"slugs": ["grok-4.6"], "resolutions": ["1k"]}
    code, outputs = _run_offline_main(
        watch, tmp_path, monkeypatch, live, dict(live), pending_path=pending
    )
    assert code == 0
    assert outputs["scan_ok"] == "true"
    assert pending.read_bytes() == b"{}\n"


def test_xts_c10_reappearance_rewrites_empty_object(tmp_path, monkeypatch) -> None:
    watch = _load()
    pending = tmp_path / "pending.json"
    pending.write_text(
        watch.dump_pending({"resolutions": {"720p": {"first_miss": "2026-11-25T01:00:00Z"}}}),
        encoding="utf-8",
    )
    live = {"slugs": ["grok-4.6"], "resolutions": ["1k", "720p"]}
    code, _outputs = _run_offline_main(
        watch, tmp_path, monkeypatch, live, dict(live), pending_path=pending
    )
    assert code == 0
    assert pending.exists()
    assert pending.read_bytes() == b"{}\n"


def test_xts_c11_second_miss_stays_pending_without_reported_at(tmp_path, monkeypatch) -> None:
    watch = _load()
    pending = tmp_path / "pending.json"
    pending.write_text(
        watch.dump_pending(
            {
                "slugs": {"grok-retired": {"first_miss": "2026-11-25T01:00:00Z"}},
                "resolutions": {"720p": {"first_miss": "2026-11-25T01:00:00Z"}},
            }
        ),
        encoding="utf-8",
    )
    live = {"slugs": ["grok-4.6"], "resolutions": ["1k"]}
    baseline = {
        "slugs": ["grok-4.6", "grok-retired"],
        "resolutions": ["1k", "720p"],
    }
    code, outputs = _run_offline_main(
        watch, tmp_path, monkeypatch, live, baseline, pending_path=pending
    )
    assert code == 2
    assert outputs["has_dropped"] == "true"
    state = _read_pending(pending)
    assert state["slugs"]["grok-retired"] == {"first_miss": "2026-11-25T01:00:00Z"}
    assert state["resolutions"]["720p"] == {"first_miss": "2026-11-25T01:00:00Z"}


def test_xts_c11_reported_token_omitted_from_dropped(tmp_path, monkeypatch) -> None:
    watch = _load()
    pending = tmp_path / "pending.json"
    pending.write_text(
        watch.dump_pending(
            {
                "slugs": {
                    "grok-retired": {
                        "first_miss": "2026-11-25T01:00:00Z",
                        "reported_at": "2026-11-25T01:05:00Z",
                    }
                },
                "resolutions": {
                    "720p": {
                        "first_miss": "2026-11-25T01:00:00Z",
                        "reported_at": "2026-11-25T01:05:00Z",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    before = pending.read_bytes()
    live = {"slugs": ["grok-4.6"], "resolutions": ["1k"]}
    baseline = {
        "slugs": ["grok-4.6", "grok-retired"],
        "resolutions": ["1k", "720p"],
    }
    code, outputs = _run_offline_main(
        watch, tmp_path, monkeypatch, live, baseline, pending_path=pending
    )
    assert code == 0
    assert outputs["dropped_slugs"] == ""
    assert outputs["dropped_resolutions"] == ""
    assert outputs["has_dropped"] == "false"
    assert pending.read_bytes() == before


def test_xts_c11_reported_reappearance_and_baseline_drop(tmp_path, monkeypatch) -> None:
    watch = _load()
    pending = tmp_path / "pending.json"
    pending.write_text(
        watch.dump_pending(
            {
                "slugs": {
                    "grok-retired": {
                        "first_miss": "2026-11-25T01:00:00Z",
                        "reported_at": "2026-11-25T01:05:00Z",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    live = {"slugs": ["grok-4.6", "grok-retired"], "resolutions": ["1k"]}
    code, outputs = _run_offline_main(
        watch, tmp_path, monkeypatch, live, dict(live), pending_path=pending
    )
    assert code == 0
    assert outputs["has_dropped"] == "false"
    assert pending.read_bytes() == b"{}\n"

    live_miss = {"slugs": ["grok-4.6"], "resolutions": ["1k"]}
    baseline_miss = {"slugs": ["grok-4.6", "grok-retired"], "resolutions": ["1k"]}
    code, outputs = _run_offline_main(
        watch, tmp_path, monkeypatch, live_miss, baseline_miss, pending_path=pending
    )
    assert code != 2
    assert outputs["dropped_slugs"] == ""
    assert set(_read_pending(pending)["slugs"]["grok-retired"]) == {"first_miss"}
    code, outputs = _run_offline_main(
        watch, tmp_path, monkeypatch, live_miss, baseline_miss, pending_path=pending
    )
    assert code == 2
    assert outputs["dropped_slugs"] == "grok-retired"
    assert outputs["has_dropped"] == "true"


def test_xts_c11_select_unlisted_still_filters_open_issue(tmp_path, capsys) -> None:
    watch = _load()
    issues = [
        {
            "number": 80,
            "title": "xAI public docs added models or resolutions",
            "body": "**Dropped slugs:** `grok-retired`\n**Dropped resolutions:** `none`\n",
            "comments": "",
        }
    ]
    path = tmp_path / "issues.json"
    path.write_text(json.dumps(issues), encoding="utf-8")
    code = watch.main(
        [
            "--select-unlisted",
            "--slugs",
            "none",
            "--resolutions",
            "none",
            "--dropped-slugs",
            "grok-retired",
            "--dropped-resolutions",
            "none",
            "--issues-json",
            str(path),
            "--pending",
            str(tmp_path / "pending.json"),
        ]
    )
    assert code == 0
    printed = _printed_outputs(capsys.readouterr().out)
    assert printed["dropped_slugs"] == ""
    assert printed["has_dropped"] == "false"


def test_xts_c13_partial_parse_counts_as_scan(tmp_path, monkeypatch) -> None:
    watch = _load()
    pending = tmp_path / "pending.json"
    pending.write_text(
        watch.dump_pending({"resolutions": {"1080p": {"first_miss": "2026-11-25T01:00:00Z"}}}),
        encoding="utf-8",
    )
    pages = {
        watch.SLUG_URLS[0]: "see grok-4.6 in the table",
        watch.SLUG_URLS[1]: "no sku on this page",
        watch.RESOLUTION_URLS[0]: "frame 1k",
        watch.RESOLUTION_URLS[1]: "caption only",
    }
    _bind_pages(watch, monkeypatch, pages)
    code, outputs = _run_pages(
        watch,
        tmp_path,
        pages,
        {"slugs": ["grok-4.6", "grok-retired"], "resolutions": ["1k", "1080p"]},
        pending,
    )
    assert code == 2
    assert outputs["scan_ok"] == "true"
    assert outputs["dropped_slugs"] == ""
    assert outputs["dropped_resolutions"] == "1080p"
    assert outputs["has_dropped"] == "true"
    state = _read_pending(pending)
    assert set(state["slugs"]["grok-retired"]) == {"first_miss"}
    assert state["resolutions"]["1080p"]["first_miss"] == "2026-11-25T01:00:00Z"
    assert "reported_at" not in state["resolutions"]["1080p"]


def test_xts_c14_mark_reported_sets_utc_reported_at(tmp_path, monkeypatch) -> None:
    watch = _load()
    pending = tmp_path / "pending.json"
    pending.write_text(
        watch.dump_pending(
            {
                "slugs": {"grok-retired": {"first_miss": "2026-11-25T01:00:00Z"}},
                "resolutions": {"720p": {"first_miss": "2026-11-25T01:00:00Z"}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(watch, "_utc_now_stamp", lambda: "2026-11-25T02:00:00Z")

    def fail_fetch(url, *, timeout=30.0):
        raise AssertionError("fetched")

    monkeypatch.setattr(watch, "fetch_text", fail_fetch)
    code = watch.main(
        [
            "--mark-reported",
            "--pending",
            str(pending),
            "--dropped-slugs",
            "grok-retired,grok-missing",
            "--dropped-resolutions",
            "720p",
        ]
    )
    assert code == 0
    state = _read_pending(pending)
    assert state["slugs"]["grok-retired"]["first_miss"] == "2026-11-25T01:00:00Z"
    assert state["slugs"]["grok-retired"]["reported_at"] == "2026-11-25T02:00:00Z"
    assert state["resolutions"]["720p"]["reported_at"] == "2026-11-25T02:00:00Z"
    assert "grok-missing" not in state["slugs"]
    assert _stamp_ok(state["slugs"]["grok-retired"]["reported_at"])
    assert state["slugs"]["grok-retired"]["reported_at"] >= state["slugs"]["grok-retired"]["first_miss"]
    text = pending.read_text(encoding="utf-8")
    assert "true" not in text
    assert "false" not in text
    again = text
    code = watch.main(
        [
            "--mark-reported",
            "--pending",
            str(pending),
            "--dropped-slugs",
            "grok-retired",
            "--dropped-resolutions",
            "720p",
        ]
    )
    assert code == 0
    assert pending.read_text(encoding="utf-8") == again


def test_xts_c15_slug_and_resolution_pending_stay_apart(tmp_path, monkeypatch) -> None:
    watch = _load()
    pending = tmp_path / "pending.json"
    live = {"slugs": ["grok-4.6"], "resolutions": ["1k"]}
    baseline = {"slugs": ["grok-4.6", "grok-retired"], "resolutions": ["1k", "720p"]}
    _run_offline_main(watch, tmp_path, monkeypatch, live, baseline, pending_path=pending)
    state = _read_pending(pending)
    assert set(state["slugs"]) == {"grok-retired"}
    assert set(state["resolutions"]) == {"720p"}
    assert "720p" not in state["slugs"]
    assert "grok-retired" not in state["resolutions"]


def test_xts_c16_mark_reported_does_not_fetch(tmp_path, monkeypatch) -> None:
    watch = _load()
    pending = tmp_path / "pending.json"
    pending.write_text(
        watch.dump_pending({"slugs": {"grok-retired": {"first_miss": "2026-11-25T01:00:00Z"}}}),
        encoding="utf-8",
    )

    def fail_fetch(url, *, timeout=30.0):
        raise AssertionError("fetched")

    monkeypatch.setattr(watch, "fetch_text", fail_fetch)
    monkeypatch.setattr(watch, "scan_pages", lambda pages, **kwargs: (_ for _ in ()).throw(AssertionError("scanned")))
    code = watch.main(
        [
            "--mark-reported",
            "--pending",
            str(pending),
            "--dropped-slugs",
            "grok-retired",
            "--dropped-resolutions",
            "",
        ]
    )
    assert code == 0
    assert "reported_at" in _read_pending(pending)["slugs"]["grok-retired"]


def test_xts_failed_filing_retries_next_scan(tmp_path, monkeypatch) -> None:
    """M26: reported_at set before filing, or without a successful filing, fails this test."""
    watch = _load()
    pending = tmp_path / "pending.json"
    live = {"slugs": ["grok-4.6"], "resolutions": ["1k"]}
    baseline = {"slugs": ["grok-4.6", "grok-retired"], "resolutions": ["1k"]}
    code, outputs = _run_offline_main(
        watch, tmp_path, monkeypatch, live, baseline, pending_path=pending
    )
    assert code != 2
    assert outputs["dropped_slugs"] == ""
    assert "reported_at" not in pending.read_text(encoding="utf-8")
    code, outputs = _run_offline_main(
        watch, tmp_path, monkeypatch, live, baseline, pending_path=pending
    )
    assert code == 2
    assert outputs["dropped_slugs"] == "grok-retired"
    assert outputs["has_dropped"] == "true"
    assert "reported_at" not in _read_pending(pending)["slugs"]["grok-retired"]
    code, outputs = _run_offline_main(
        watch, tmp_path, monkeypatch, live, baseline, pending_path=pending
    )
    assert code == 2
    assert outputs["dropped_slugs"] == "grok-retired"
    assert "reported_at" not in _read_pending(pending)["slugs"]["grok-retired"]
    marked = pending.read_text(encoding="utf-8")
    code = watch.main(
        [
            "--mark-reported",
            "--pending",
            str(pending),
            "--dropped-slugs",
            "grok-retired",
            "--dropped-resolutions",
            "",
        ]
    )
    assert code == 0
    reported_at = _read_pending(pending)["slugs"]["grok-retired"]["reported_at"]
    assert _stamp_ok(reported_at)
    assert reported_at >= _read_pending(pending)["slugs"]["grok-retired"]["first_miss"]
    assert pending.read_text(encoding="utf-8") != marked
    code, outputs = _run_offline_main(
        watch, tmp_path, monkeypatch, live, baseline, pending_path=pending
    )
    assert outputs["dropped_slugs"] == ""
    assert outputs["has_dropped"] == "false"
    assert code != 2
    assert _read_pending(pending)["slugs"]["grok-retired"]["reported_at"] == reported_at


def test_xts_malformed_pending_errors(tmp_path, monkeypatch) -> None:
    watch = _load()
    cases = {
        "invalid json": "{",
        "array": "[]\n",
        "null": "null\n",
        "unknown key": '{"extra": {}}\n',
        "side list": '{"slugs": []}\n',
        "token string": '{"slugs": {"grok-retired": "x"}}\n',
        "missing first_miss": '{"slugs": {"grok-retired": {}}}\n',
        "non-string first_miss": '{"slugs": {"grok-retired": {"first_miss": true}}}\n',
        "boolean marker": (
            '{"slugs": {"grok-retired": {"first_miss": "2026-11-25T01:00:00Z", '
            '"reported": true}}}\n'
        ),
    }

    def fail_fetch(url, *, timeout=30.0):
        raise AssertionError("fetched")

    monkeypatch.setattr(watch, "fetch_text", fail_fetch)
    for name, body in cases.items():
        pending = tmp_path / f"{name.replace(' ', '-')}.json"
        pending.write_text(body, encoding="utf-8")
        before = pending.read_bytes()
        baseline_path = tmp_path / f"{name.replace(' ', '-')}-baseline.json"
        baseline_path.write_bytes(b"KEEP\n")
        output_path = tmp_path / f"{name.replace(' ', '-')}-out.txt"
        code = watch.main(
            [
                "--baseline",
                str(baseline_path),
                "--pending",
                str(pending),
                "--github-output",
                str(output_path),
                "--write-baseline",
            ]
        )
        assert code == 1, name
        assert pending.read_bytes() == before, name
        assert baseline_path.read_bytes() == b"KEEP\n", name
        assert _github_outputs(output_path.read_text(encoding="utf-8"))["scan_ok"] == "false", name


def test_xts_mark_reported_empty_lists_noop(tmp_path, monkeypatch) -> None:
    watch = _load()
    pending = tmp_path / "pending.json"
    pending.write_text(
        watch.dump_pending({"slugs": {"grok-retired": {"first_miss": "2026-11-25T01:00:00Z"}}}),
        encoding="utf-8",
    )
    before = pending.read_bytes()

    def fail_fetch(url, *, timeout=30.0):
        raise AssertionError("fetched")

    monkeypatch.setattr(watch, "fetch_text", fail_fetch)
    code = watch.main(
        [
            "--mark-reported",
            "--pending",
            str(pending),
            "--dropped-slugs",
            "",
            "--dropped-resolutions",
            "",
        ]
    )
    assert code == 0
    assert pending.read_bytes() == before


def test_xts_c7_pending_dump_is_deterministic() -> None:
    watch = _load()
    state = {
        "slugs": {
            "grok-retired": {
                "reported_at": "2026-11-25T02:00:00Z",
                "first_miss": "2026-11-25T01:00:00Z",
            }
        },
        "resolutions": {"720p": {"first_miss": "2026-11-25T01:00:00Z"}},
    }
    first = watch.dump_pending(state)
    assert first == watch.dump_pending(state)
    assert first.endswith("\n")
    assert first != "{}\n"
    assert watch.dump_pending({}) == "{}\n"
    parsed = json.loads(first)
    assert list(parsed) == ["resolutions", "slugs"]
    assert list(parsed["slugs"]["grok-retired"]) == ["first_miss", "reported_at"]
    assert "true" not in first


def test_xnf_c1_new_slugs_line_does_not_file_a_drop() -> None:
    """A dropped id that appears only on a New slugs line is not already filed."""
    watch = _load()
    issues = [
        {
            "number": 11,
            "title": "xAI public docs added models or resolutions",
            "body": (
                "**New slugs:** `grok-retired`\n"
                "**New resolutions:** `none`\n"
                "**Dropped slugs:** `none`\n"
                "**Dropped resolutions:** `none`\n"
            ),
            "comments": "",
        }
    ]
    assert watch.unlisted_watch_tokens(["grok-retired"], issues, dropped=True) == [
        "grok-retired"
    ]


def test_xnf_c1_new_resolutions_line_does_not_file_a_drop() -> None:
    """A dropped id that appears only on a New resolutions line is not already filed."""
    watch = _load()
    issues = [
        {
            "number": 12,
            "title": "xAI public docs added models or resolutions",
            "body": (
                "**New slugs:** `none`\n"
                "**New resolutions:** `720p`\n"
                "**Dropped slugs:** `none`\n"
                "**Dropped resolutions:** `none`\n"
            ),
            "comments": "",
        }
    ]
    assert watch.unlisted_watch_tokens(["720p"], issues, dropped=True) == ["720p"]


def test_xnf_c1_title_comment_guard_do_not_file_a_drop() -> None:
    """A title, a comment, a guard issue, or a New line does not file a drop."""
    watch = _load()
    token = "grok-retired"
    title_only = {
        "number": 1,
        "title": f"flagship {token}",
        "body": "**New slugs:** `none`\n**Dropped slugs:** `none`\n",
        "comments": "",
    }
    comment_only = {
        "number": 2,
        "title": "xAI public docs added models or resolutions",
        "body": "**Dropped slugs:** `none`\n",
        "comments": f"still seeing {token}",
    }
    guard = {
        "number": 3,
        "title": f"xAI shipped image price guard failed: {token}",
        "body": (
            "The watcher extract is missing a shipped image id "
            f"or its per_call_usd does not match the shipped default.\n\n- {token}\n"
        ),
        "comments": f"ping {token}",
    }
    new_line = {
        "number": 4,
        "title": token,
        "body": f"**New slugs:** `{token}`\n",
        "comments": token,
    }
    assert watch.unlisted_watch_tokens([token], [title_only], dropped=True) == [token]
    assert watch.unlisted_watch_tokens([token], [comment_only], dropped=True) == [token]
    assert watch.unlisted_watch_tokens([token], [guard], dropped=True) == [token]
    assert watch.unlisted_watch_tokens(
        [token], [title_only, comment_only, guard, new_line], dropped=True
    ) == [token]


def test_xnf_c2_mark_reported_skips_unfiled_new_slugs_hit(tmp_path, monkeypatch, capsys) -> None:
    """A New slugs hit is not a Dropped-line filing, so reported_at stays unset."""
    watch = _load()
    pending = tmp_path / "pending.json"
    pending.write_text(
        watch.dump_pending(
            {"slugs": {"grok-retired": {"first_miss": "2026-11-25T01:00:00Z"}}}
        ),
        encoding="utf-8",
    )
    before = pending.read_bytes()
    issues = [
        {
            "number": 21,
            "title": "xAI public docs added models or resolutions",
            "body": (
                "**New slugs:** `grok-retired`\n"
                "**New resolutions:** `none`\n"
                "**Dropped slugs:** `none`\n"
                "**Dropped resolutions:** `none`\n"
            ),
            "comments": "",
        }
    ]
    path = tmp_path / "issues.json"
    path.write_text(json.dumps(issues), encoding="utf-8")

    def fail_fetch(url, *, timeout=30.0):
        raise AssertionError("fetched")

    monkeypatch.setattr(watch, "fetch_text", fail_fetch)
    code = watch.main(
        [
            "--select-unlisted",
            "--slugs",
            "none",
            "--resolutions",
            "none",
            "--dropped-slugs",
            "grok-retired",
            "--dropped-resolutions",
            "none",
            "--issues-json",
            str(path),
            "--pending",
            str(tmp_path / "pending.json"),
        ]
    )
    assert code == 0
    printed = _printed_outputs(capsys.readouterr().out)
    assert printed["dropped_slugs"] == "grok-retired"
    assert printed["has_dropped"] == "true"
    code = watch.main(
        [
            "--mark-reported",
            "--pending",
            str(pending),
            "--dropped-slugs",
            "",
            "--dropped-resolutions",
            "",
        ]
    )
    assert code == 0
    assert pending.read_bytes() == before
    assert "reported_at" not in pending.read_text(encoding="utf-8")


def test_xnf_c2_next_scan_retries_until_filed(tmp_path, monkeypatch, capsys) -> None:
    """Until a drop is filed, the next scan still reports the id."""
    watch = _load()
    pending = tmp_path / "pending.json"
    live = {"slugs": ["grok-4.6"], "resolutions": ["1k"]}
    baseline = {"slugs": ["grok-4.6", "grok-retired"], "resolutions": ["1k"]}
    code, outputs = _run_offline_main(
        watch, tmp_path, monkeypatch, live, baseline, pending_path=pending
    )
    assert code == 0
    assert outputs["dropped_slugs"] == ""
    assert "reported_at" not in pending.read_text(encoding="utf-8")
    capsys.readouterr()
    code, outputs = _run_offline_main(
        watch, tmp_path, monkeypatch, live, baseline, pending_path=pending
    )
    assert code == 2
    assert outputs["dropped_slugs"] == "grok-retired"
    assert "reported_at" not in _read_pending(pending)["slugs"]["grok-retired"]
    capsys.readouterr()

    issues = [
        {
            "number": 22,
            "title": "xAI public docs added models or resolutions",
            "body": "**New slugs:** `grok-retired`\n**Dropped slugs:** `none`\n",
            "comments": "",
        }
    ]
    path = tmp_path / "issues.json"
    path.write_text(json.dumps(issues), encoding="utf-8")
    code = watch.main(
        [
            "--select-unlisted",
            "--slugs",
            "none",
            "--resolutions",
            "none",
            "--dropped-slugs",
            "grok-retired",
            "--dropped-resolutions",
            "none",
            "--issues-json",
            str(path),
            "--pending",
            str(tmp_path / "pending.json"),
        ]
    )
    assert code == 0
    printed = _printed_outputs(capsys.readouterr().out)
    assert printed["dropped_slugs"] == "grok-retired"
    assert "reported_at" not in _read_pending(pending)["slugs"]["grok-retired"]

    code, outputs = _run_offline_main(
        watch, tmp_path, monkeypatch, live, baseline, pending_path=pending
    )
    assert code == 2
    assert outputs["dropped_slugs"] == "grok-retired"
    assert "reported_at" not in _read_pending(pending)["slugs"]["grok-retired"]
    capsys.readouterr()

    code = watch.main(
        [
            "--mark-reported",
            "--pending",
            str(pending),
            "--dropped-slugs",
            "grok-retired",
            "--dropped-resolutions",
            "",
        ]
    )
    assert code == 0
    assert "reported_at" in _read_pending(pending)["slugs"]["grok-retired"]
    code, outputs = _run_offline_main(
        watch, tmp_path, monkeypatch, live, baseline, pending_path=pending
    )
    assert outputs["dropped_slugs"] == ""
    assert outputs["has_dropped"] == "false"
    assert code != 2


def test_xnf_c3_first_miss_log_names_pending_ids(tmp_path, monkeypatch, capsys) -> None:
    """Row: baseline grok-4.6, grok-a, grok-b. Scan 1 omits grok-a. Scan 2 restores it and omits grok-b."""
    watch = _load()
    pending = tmp_path / "pending.json"
    baseline = {
        "slugs": ["grok-4.6", "grok-a", "grok-b"],
        "resolutions": ["1k"],
    }
    code, outputs = _run_offline_main(
        watch,
        tmp_path,
        monkeypatch,
        {"slugs": ["grok-4.6", "grok-b"], "resolutions": ["1k"]},
        baseline,
        pending_path=pending,
    )
    stdout = capsys.readouterr().out
    assert code == 0
    assert outputs["has_dropped"] == "false"
    assert outputs["dropped_slugs"] == ""
    assert "xAI public docs match the committed watch baseline" not in stdout
    assert (
        "xAI public docs watch pending: first-miss grok-a; still-absent none" in stdout
    )
    assert set(_read_pending(pending)["slugs"]) == {"grok-a"}

    code, outputs = _run_offline_main(
        watch,
        tmp_path,
        monkeypatch,
        {"slugs": ["grok-4.6", "grok-a"], "resolutions": ["1k"]},
        baseline,
        pending_path=pending,
    )
    stdout = capsys.readouterr().out
    assert code == 0
    assert outputs["has_dropped"] == "false"
    assert outputs["dropped_slugs"] == ""
    assert "xAI public docs match the committed watch baseline" not in stdout
    assert (
        "xAI public docs watch pending: first-miss grok-b; still-absent none" in stdout
    )
    assert "grok-a" not in stdout
    assert set(_read_pending(pending)["slugs"]) == {"grok-b"}


def test_xnf_c3_mixed_and_still_absent_log(tmp_path, monkeypatch, capsys) -> None:
    """A second-miss id emitted in dropped_* is still-absent, not first-miss."""
    watch = _load()
    pending = tmp_path / "pending.json"
    pending.write_text(
        watch.dump_pending(
            {
                "resolutions": {
                    "720p": {
                        "first_miss": "2026-11-25T01:00:00Z",
                        "reported_at": "2026-11-25T01:05:00Z",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    baseline = {
        "slugs": ["grok-4.6", "grok-a", "grok-b"],
        "resolutions": ["1k", "720p"],
    }
    code, outputs = _run_offline_main(
        watch,
        tmp_path,
        monkeypatch,
        {"slugs": ["grok-4.6", "grok-b"], "resolutions": ["1k"]},
        baseline,
        pending_path=pending,
    )
    stdout = capsys.readouterr().out
    assert code == 0
    assert outputs["has_dropped"] == "false"
    assert outputs["dropped_slugs"] == ""
    assert "xAI public docs match the committed watch baseline" not in stdout
    assert (
        "xAI public docs watch pending: first-miss grok-a; still-absent 720p" in stdout
    )

    code, outputs = _run_offline_main(
        watch,
        tmp_path,
        monkeypatch,
        {"slugs": ["grok-4.6"], "resolutions": ["1k"]},
        baseline,
        pending_path=pending,
    )
    stdout = capsys.readouterr().out
    assert code == 2
    assert outputs["dropped_slugs"] == "grok-a"
    assert "grok-b" not in outputs["dropped_slugs"].split(",")
    assert outputs["dropped_resolutions"] == ""
    assert outputs["has_dropped"] == "true"
    assert "xAI public docs match the committed watch baseline" not in stdout
    logged = next(
        line
        for line in stdout.splitlines()
        if line.startswith("xAI public docs watch pending:")
    )
    assert logged == (
        "xAI public docs watch pending: first-miss grok-b; still-absent 720p,grok-a"
    )
    first_part, still_part = logged.split("; still-absent ", 1)
    assert "grok-a" not in first_part
    assert "grok-a" in still_part
    assert outputs["dropped_slugs"] == "grok-a"
    assert "Dropped xAI public-docs tokens" in stdout
    assert "dropped slugs:" in stdout


def _watch_pages(watch, slug_text: str, resolution_text: str) -> dict[str, str]:
    return {
        watch.SLUG_URLS[0]: slug_text,
        watch.SLUG_URLS[1]: slug_text,
        watch.RESOLUTION_URLS[0]: resolution_text,
        watch.RESOLUTION_URLS[1]: resolution_text,
    }


def _pending_lines(stdout: str) -> list[str]:
    return [
        line
        for line in stdout.splitlines()
        if line.startswith("xAI public docs watch pending:")
    ]


def test_xnu_c1_c3_failed_slug_side_pending_is_unscanned_not_still_absent(
    tmp_path, monkeypatch, capsys
) -> None:
    """C1 and C3: a slug-only pending id is unscanned when slug pages do not parse."""
    watch = _load()
    pending = tmp_path / "pending.json"
    seeded = {"slugs": {"grok-retired": {"first_miss": "2026-11-25T01:00:00Z"}}}
    pending.write_text(watch.dump_pending(seeded), encoding="utf-8")
    before = pending.read_bytes()
    pages = _watch_pages(watch, "no model sku here", "frame 1k")
    _bind_pages(watch, monkeypatch, pages)
    code, _outputs = _run_pages(
        watch,
        tmp_path,
        pages,
        {"slugs": ["grok-4.6", "grok-retired"], "resolutions": ["1k"]},
        pending,
    )
    stdout = capsys.readouterr().out
    assert "still-absent grok-retired" not in stdout
    assert "first-miss grok-retired" not in stdout
    assert _pending_lines(stdout) == []
    assert "first-miss none; still-absent none" not in stdout
    assert "xAI public docs match the committed watch baseline" in stdout
    assert "xAI public docs watch unscanned: slugs skipped" in stdout
    assert code == 0
    assert pending.read_bytes() == before


def test_xnu_c1_failed_resolution_side_pending_is_unscanned_not_still_absent(
    tmp_path, monkeypatch, capsys
) -> None:
    """A resolution-only pending id is unscanned when resolution pages do not parse."""
    watch = _load()
    pending = tmp_path / "pending.json"
    seeded = {"resolutions": {"720p": {"first_miss": "2026-11-25T01:00:00Z"}}}
    pending.write_text(watch.dump_pending(seeded), encoding="utf-8")
    before = pending.read_bytes()
    pages = _watch_pages(watch, "grok-4.6", "no frame size")
    _bind_pages(watch, monkeypatch, pages)
    code, _outputs = _run_pages(
        watch,
        tmp_path,
        pages,
        {"slugs": ["grok-4.6"], "resolutions": ["1k", "720p"]},
        pending,
    )
    stdout = capsys.readouterr().out
    assert "still-absent 720p" not in stdout
    assert "first-miss 720p" not in stdout
    assert _pending_lines(stdout) == []
    assert "first-miss none; still-absent none" not in stdout
    assert "xAI public docs match the committed watch baseline" in stdout
    assert "xAI public docs watch unscanned: resolutions skipped" in stdout
    assert code == 0
    assert pending.read_bytes() == before


def test_xnu_c1_scanned_pending_line_omits_unscanned_side_id(
    tmp_path, monkeypatch, capsys
) -> None:
    """A scanned-side first miss stays on the pending line; the failed-side id does not."""
    watch = _load()
    pending = tmp_path / "pending.json"
    seeded = {"slugs": {"grok-retired": {"first_miss": "2026-11-25T01:00:00Z"}}}
    pending.write_text(watch.dump_pending(seeded), encoding="utf-8")
    before = pending.read_text(encoding="utf-8")
    pages = _watch_pages(watch, "no model sku here", "frame 1k")
    _bind_pages(watch, monkeypatch, pages)
    code, _outputs = _run_pages(
        watch,
        tmp_path,
        pages,
        {"slugs": ["grok-4.6", "grok-retired"], "resolutions": ["1k", "720p"]},
        pending,
    )
    stdout = capsys.readouterr().out
    pending_lines = _pending_lines(stdout)
    assert len(pending_lines) == 1
    logged = pending_lines[0]
    first_part, still_part = logged.split("; still-absent ", 1)
    assert "grok-retired" not in first_part
    assert "grok-retired" not in still_part
    assert logged == (
        "xAI public docs watch pending: first-miss 720p; still-absent none"
    )
    assert "xAI public docs watch unscanned: slugs skipped" in stdout
    assert "xAI public docs match the committed watch baseline" not in stdout
    assert code == 0
    after = pending.read_text(encoding="utf-8")
    assert json.dumps(json.loads(after)["slugs"], sort_keys=True) == json.dumps(
        json.loads(before)["slugs"], sort_keys=True
    )
    slug_entry = '"grok-retired": {\n      "first_miss": "2026-11-25T01:00:00Z"\n    }'
    assert slug_entry in before
    assert slug_entry in after


_XDR_SEEDED = "2026-11-25T01:00:00Z"


def _xdr_seed(pending: Path, slugs=(), resolutions=()) -> None:
    state: dict = {}
    if slugs:
        state["slugs"] = {token: {"first_miss": _XDR_SEEDED} for token in slugs}
    if resolutions:
        state["resolutions"] = {token: {"first_miss": _XDR_SEEDED} for token in resolutions}
    pending.write_text(json.dumps(state), encoding="utf-8")


def _xdr_select_unlisted(watch, tmp_path, capsys, outputs: dict, issues: list, pending=None) -> dict:
    """The issue step's --select-unlisted call. pending=None uses the default path, as the workflow does."""
    issues_path = tmp_path / "xdr_issues.json"
    issues_path.write_text(json.dumps(issues), encoding="utf-8")
    argv = [
        "--select-unlisted",
        "--slugs", outputs.get("new_slugs", ""),
        "--resolutions", outputs.get("new_resolutions", ""),
        "--dropped-slugs", outputs.get("dropped_slugs", ""),
        "--dropped-resolutions", outputs.get("dropped_resolutions", ""),
        "--issues-json", str(issues_path),
    ]
    if pending is not None:
        argv.extend(["--pending", str(pending)])
    capsys.readouterr()
    code = watch.main(argv)
    assert code == 0
    return _printed_outputs(capsys.readouterr().out)


def _xdr_mark(watch, pending: Path, printed: dict) -> None:
    """The mark step: --mark-reported with the issue step's filtered outputs."""
    code = watch.main(
        [
            "--mark-reported",
            "--pending", str(pending),
            "--dropped-slugs", printed["dropped_slugs"],
            "--dropped-resolutions", printed["dropped_resolutions"],
        ]
    )
    assert code == 0


_XDR_LISTED_ISSUE = {
    "number": 80,
    "title": "xAI public docs added models or resolutions",
    "body": (
        "**New slugs:** `none`\n"
        "**New resolutions:** `none`\n"
        "**Dropped slugs:** `grok-retired`\n"
        "**Dropped resolutions:** `none`\n"
    ),
    "comments": "",
}


def test_xdr_c1_already_listed_dropped_slug_is_stamped_and_next_scan_quiet(
    tmp_path, monkeypatch, capsys
) -> None:
    """Nightly digest repro: an open issue already lists the drop on a Dropped line."""
    watch = _load()
    pending = tmp_path / "pending.json"
    _xdr_seed(pending, slugs=["grok-retired"])
    baseline = {"slugs": ["grok-4.6", "grok-retired"], "resolutions": ["1k"]}
    live = {"slugs": ["grok-4.6"], "resolutions": ["1k"]}
    code, outputs = _run_offline_main(
        watch, tmp_path, monkeypatch, live, baseline, pending_path=pending
    )
    assert code == 2
    assert outputs["dropped_slugs"] == "grok-retired"
    printed = _xdr_select_unlisted(
        watch, tmp_path, capsys, outputs, [_XDR_LISTED_ISSUE], pending=pending
    )
    assert printed["dropped_slugs"] == ""
    assert printed["has_dropped"] == "false"
    _xdr_mark(watch, pending, printed)
    entry = _read_pending(pending)["slugs"]["grok-retired"]
    assert entry["first_miss"] == _XDR_SEEDED
    assert "reported_at" in entry
    assert _stamp_ok(entry["reported_at"])
    capsys.readouterr()
    code, outputs = _run_offline_main(
        watch, tmp_path, monkeypatch, live, baseline, pending_path=pending
    )
    out = capsys.readouterr().out
    assert code == 0
    assert outputs["has_dropped"] == "false"
    assert outputs["dropped_slugs"] == ""
    assert "Dropped xAI public-docs tokens" not in out


def test_xdr_c1_listed_resolution_and_fresh_slug_drop_both_stamped(
    tmp_path, monkeypatch, capsys
) -> None:
    """A listed resolution drop is stamped next to a fresh slug drop filed this run."""
    watch = _load()
    pending = tmp_path / "pending.json"
    _xdr_seed(pending, slugs=["grok-legacy"], resolutions=["720p"])
    baseline = {"slugs": ["grok-4.6", "grok-legacy"], "resolutions": ["1k", "720p"]}
    live = {"slugs": ["grok-4.6"], "resolutions": ["1k"]}
    code, outputs = _run_offline_main(
        watch, tmp_path, monkeypatch, live, baseline, pending_path=pending
    )
    assert code == 2
    assert outputs["dropped_slugs"] == "grok-legacy"
    assert outputs["dropped_resolutions"] == "720p"
    issues = [
        {
            "number": 81,
            "title": "xAI public docs added models or resolutions",
            "body": "**Dropped slugs:** `none`\n**Dropped resolutions:** `720p`\n",
            "comments": "",
        }
    ]
    printed = _xdr_select_unlisted(watch, tmp_path, capsys, outputs, issues, pending=pending)
    assert printed["dropped_slugs"] == "grok-legacy"
    assert printed["dropped_resolutions"] == ""
    assert printed["has_dropped"] == "true"
    _xdr_mark(watch, pending, printed)
    state = _read_pending(pending)
    assert "reported_at" in state["slugs"]["grok-legacy"]
    assert "reported_at" in state["resolutions"]["720p"]
    capsys.readouterr()
    code, outputs = _run_offline_main(
        watch, tmp_path, monkeypatch, live, baseline, pending_path=pending
    )
    out = capsys.readouterr().out
    assert code == 0
    assert outputs["has_dropped"] == "false"
    assert "Dropped xAI public-docs tokens" not in out


def test_xdr_c1_workflow_select_unlisted_stamps_default_pending_file(
    tmp_path, monkeypatch, capsys
) -> None:
    """Production path: the issue step runs --select-unlisted without --pending, and the mark step commits that file."""
    watch = _load()
    assert watch.PENDING_PATH == ROOT / "scripts" / "data" / "xai_models_watch_pending.json"
    workflow = (ROOT / ".github" / "workflows" / "watch-xai-models.yml").read_text(encoding="utf-8")
    issue_step = workflow.split("- name: Open issue for tokens not already listed", 1)[1]
    issue_step, mark_step = issue_step.split("- name: Mark reported watch tokens", 1)
    mark_step = mark_step.split("\n      - name: ", 1)[0]
    select_call = issue_step.split("--select-unlisted", 1)[1].split(")\"", 1)[0]
    assert "--pending" not in select_call
    assert "if: ${{ !cancelled() && steps.issue.outcome == 'success' }}" in mark_step
    assert "git add scripts/data/xai_models_watch_pending.json" in mark_step
    assert "git commit" in mark_step

    pending = tmp_path / "default_pending.json"
    _xdr_seed(pending, slugs=["grok-retired"])
    monkeypatch.setattr(watch, "PENDING_PATH", pending)
    outputs = {
        "new_slugs": "",
        "new_resolutions": "",
        "dropped_slugs": "grok-retired",
        "dropped_resolutions": "",
    }
    printed = _xdr_select_unlisted(watch, tmp_path, capsys, outputs, [_XDR_LISTED_ISSUE])
    assert printed["has_dropped"] == "false"
    _xdr_mark(watch, pending, printed)
    entry = _read_pending(pending)["slugs"]["grok-retired"]
    assert entry["first_miss"] == _XDR_SEEDED
    assert "reported_at" in entry


def test_xdr_c2_new_line_title_or_comment_only_drop_is_not_stamped(
    tmp_path, monkeypatch, capsys
) -> None:
    """Only a Dropped line lists a drop. New line, title, and comment mentions stay unstamped."""
    watch = _load()
    pending = tmp_path / "pending.json"
    _xdr_seed(pending, slugs=["grok-retired"])
    baseline = {"slugs": ["grok-4.6", "grok-retired"], "resolutions": ["1k"]}
    live = {"slugs": ["grok-4.6"], "resolutions": ["1k"]}
    code, outputs = _run_offline_main(
        watch, tmp_path, monkeypatch, live, baseline, pending_path=pending
    )
    assert code == 2
    issues = [
        {
            "number": 82,
            "title": "xAI public docs: grok-retired",
            "body": "**New slugs:** `grok-retired`\n**Dropped slugs:** `none`\n",
            "comments": "grok-retired looks gone",
        }
    ]
    printed = _xdr_select_unlisted(watch, tmp_path, capsys, outputs, issues, pending=pending)
    assert printed["dropped_slugs"] == "grok-retired"
    assert printed["has_dropped"] == "true"
    # --select-unlisted must not stamp it; only a new issue filed for it may.
    assert _read_pending(pending)["slugs"]["grok-retired"] == {"first_miss": _XDR_SEEDED}
    # No new issue filed (for example the issue create failed, so the mark step is skipped).
    code, outputs = _run_offline_main(
        watch, tmp_path, monkeypatch, live, baseline, pending_path=pending
    )
    assert code == 2
    assert outputs["has_dropped"] == "true"
    assert outputs["dropped_slugs"] == "grok-retired"


def test_xdr_c4_select_unlisted_malformed_pending_keeps_outputs(tmp_path, capsys) -> None:
    """A malformed pending file never blocks issue filing: same stdout, exit 0, file untouched."""
    watch = _load()
    pending = tmp_path / "pending.json"
    pending.write_text("{", encoding="utf-8")
    printed = _xdr_select_unlisted(
        watch,
        tmp_path,
        capsys,
        {"dropped_slugs": "grok-retired,grok-legacy"},
        [_XDR_LISTED_ISSUE],
        pending=pending,
    )
    assert printed == {
        "slugs": "",
        "resolutions": "",
        "dropped_slugs": "grok-legacy",
        "dropped_resolutions": "",
        "has_dropped": "true",
    }
    assert pending.read_text(encoding="utf-8") == "{"


def test_b6_select_unlisted_leaves_committed_pending_file(tmp_path, capsys) -> None:
    """B6: the existing select-unlisted calls stamp a tmp pending file.

    The committed scripts/data/xai_models_watch_pending.json stays byte-identical.
    """
    watch = _load()
    committed = ROOT / "scripts" / "data" / "xai_models_watch_pending.json"
    assert committed == watch.PENDING_PATH
    before = committed.read_bytes()
    pending = tmp_path / "pending.json"
    pending.write_text(
        json.dumps(
            {
                "resolutions": {"720p": {"first_miss": "2026-11-25T01:00:00Z"}},
                "slugs": {
                    "grok-imagine-image-2.0": {"first_miss": "2026-11-25T01:00:00Z"},
                    "grok-retired": {"first_miss": "2026-11-25T01:00:00Z"},
                },
            }
        ),
        encoding="utf-8",
    )
    issues_path = tmp_path / "issues.json"

    def run(issues: list, extra: list[str]) -> None:
        issues_path.write_text(json.dumps(issues), encoding="utf-8")
        code = watch.main(
            [
                "--select-unlisted",
                "--pending",
                str(pending),
                "--issues-json",
                str(issues_path),
                *extra,
            ]
        )
        assert code == 0
        capsys.readouterr()

    listed_body = (
        "**New slugs:** `none`\n"
        "**New resolutions:** `none`\n"
        "**Dropped slugs:** `grok-retired`\n"
        "**Dropped resolutions:** `720p`\n"
    )
    listed = [
        {
            "number": 80,
            "title": "xAI public docs added models or resolutions",
            "body": listed_body,
            "comments": "",
        }
    ]
    run(
        listed,
        [
            "--slugs", "none",
            "--resolutions", "none",
            "--dropped-slugs", "grok-retired",
            "--dropped-resolutions", "720p",
        ],
    )
    run(
        listed,
        [
            "--slugs", "none",
            "--resolutions", "none",
            "--dropped-slugs", "grok-legacy",
            "--dropped-resolutions", "4k",
        ],
    )
    dropped = "grok-imagine-image-2.0"
    guard = {
        "number": 90,
        "title": f"xAI shipped image price guard failed: {dropped}",
        "body": f"- {dropped}\n",
        "comments": f"ping {dropped}",
    }
    run(
        [guard],
        [
            "--slugs", "none",
            "--resolutions", "none",
            "--dropped-slugs", dropped,
            "--dropped-resolutions", "none",
        ],
    )
    reported = {
        "number": 80,
        "title": f"xAI public docs added models or resolutions {dropped}",
        "body": (
            f"**Dropped slugs:** `{dropped}`\n"
            "**Dropped resolutions:** `none`\n"
        ),
        "comments": "",
    }
    run(
        [guard, reported],
        [
            "--slugs", "none",
            "--resolutions", "none",
            "--dropped-slugs", dropped,
            "--dropped-resolutions", "none",
        ],
    )
    run(
        [
            {
                "number": 57,
                "title": "watch",
                "body": "**New slugs:** `grok-4.6`",
                "comments": "",
            }
        ],
        ["--slugs", "grok-4.6,grok-4.7,none", "--resolutions", "4k"],
    )
    dropped_line = [
        {
            "number": 80,
            "title": "xAI public docs added models or resolutions",
            "body": "**Dropped slugs:** `grok-retired`\n**Dropped resolutions:** `none`\n",
            "comments": "",
        }
    ]
    run(
        dropped_line,
        [
            "--slugs", "none",
            "--resolutions", "none",
            "--dropped-slugs", "grok-retired",
            "--dropped-resolutions", "none",
        ],
    )
    new_line = [
        {
            "number": 21,
            "title": "xAI public docs added models or resolutions",
            "body": "**New slugs:** `grok-retired`\n**Dropped slugs:** `none`\n",
            "comments": "",
        }
    ]
    new_args = [
        "--slugs", "none",
        "--resolutions", "none",
        "--dropped-slugs", "grok-retired",
        "--dropped-resolutions", "none",
    ]
    run(new_line, new_args)
    run(new_line, new_args)

    assert committed.read_bytes() == before
    state = _read_pending(pending)
    assert "reported_at" in state["slugs"]["grok-retired"]
    assert "reported_at" in state["resolutions"]["720p"]
    assert "reported_at" in state["slugs"]["grok-imagine-image-2.0"]
