"""Offline extract/diff tests for scripts/watch_xai_models.py (no network)."""

from __future__ import annotations

import importlib.util
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


def test_committed_baseline_has_current_public_table() -> None:
    watch = _load()
    baseline = watch.load_baseline(watch.BASELINE_PATH)
    slugs = set(baseline["slugs"])
    assert "grok-4.6" in slugs
    assert "grok-imagine-image-2.0" in slugs
    assert "1k" in baseline["resolutions"]
    assert "4k" not in baseline["resolutions"]
