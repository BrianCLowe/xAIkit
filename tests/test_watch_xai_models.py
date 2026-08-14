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
    """
    slugs = watch.extract_slugs(html)
    assert "grok-4.6" in slugs
    assert "grok-imagine-image-2.0" in slugs
    assert "grok-4.5" in slugs
    assert "grok-api" not in slugs
    assert watch.extract_resolutions(html) == ["1080p", "2k"]
    assert "grok-4-is-released" not in watch.extract_slugs(
        "heading grok-4-is-released and grok-voice-agent-api-is-released"
    )


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


def test_committed_baseline_has_current_public_table() -> None:
    watch = _load()
    baseline = watch.load_baseline(watch.BASELINE_PATH)
    slugs = set(baseline["slugs"])
    assert "grok-4.6" in slugs
    assert "grok-imagine-image-2.0" in slugs
    assert "1k" in baseline["resolutions"]
    assert "4k" not in baseline["resolutions"]
