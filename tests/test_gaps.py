"""Unit tests for optional gap log companion (scrub, sinks, review helpers)."""

from __future__ import annotations

from pathlib import Path

import pytest

from xaikit.gaps import (
    GapLog,
    InMemoryGapSink,
    JsonlGapSink,
    NullGapSink,
    build_gap_log,
    dump_gaps_jsonl,
    get_gap_log,
    main,
    reset_gap_log,
    scrub_gap_text,
    set_gap_log,
)


def test_scrub_redacts_secretish_and_caps() -> None:
    raw = 'leak api_key=sk-abc123456789 and xai-deadbeef01 here'
    out = scrub_gap_text(raw)
    assert "sk-abc" not in out
    assert "xai-deadbeef" not in out
    assert "[REDACTED]" in out
    assert "leak" in out

    long = "x" * 5000
    capped = scrub_gap_text(long, max_len=100)
    assert len(capped) <= 100
    assert capped.endswith("...")


def test_default_gap_log_is_null_off() -> None:
    log = GapLog()
    assert isinstance(log.sink, NullGapSink)
    ev = log.record(feature="demo.chat", note="missing tool")
    assert ev.feature == "demo.chat"
    assert list(log.sink.iter_events()) == []


def test_record_scrubs_note_and_requires_feature() -> None:
    sink = InMemoryGapSink()
    log = GapLog(sink=sink)
    ev = log.record(
        kind="capability_gap",
        feature="demo.feature",
        note="need api_key=SECRETVALUE99 in response",
        code="missing_schema",
        model="grok-4.5",
    )
    assert ev.kind == "capability_gap"
    assert "SECRETVALUE" not in ev.note
    assert "[REDACTED]" in ev.note
    assert ev.code == "missing_schema"
    assert len(list(sink.iter_events())) == 1

    with pytest.raises(ValueError, match="feature"):
        log.record(feature="  ", note="x")


def test_jsonl_sink_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "gaps.jsonl"
    log = GapLog(sink=JsonlGapSink(path))
    log.record(feature="demo", note="first", code="a")
    log.record(
        kind="capability_gap",
        feature="demo",
        note="second",
        code="b",
    )
    loaded = GapLog(sink=JsonlGapSink(path))
    events = loaded.events(feature="demo")
    assert len(events) == 2
    assert loaded.count_by_code() == {"a": 1, "b": 1}
    recent = loaded.recent(limit=1)
    assert len(recent) == 1
    assert recent[0].code == "b"


def test_record_from_payload_and_dump() -> None:
    sink = InMemoryGapSink()
    log = GapLog(sink=sink)
    events = log.record_from_payload(
        {
            "gaps": [
                {"kind": "output_gap", "note": "schema miss", "code": "s1"},
                {"kind": "capability_gap", "text": "no tool", "code": "t1"},
            ]
        },
        feature="demo.chat",
        model="grok-3-mini",
    )
    assert len(events) == 2
    blob = dump_gaps_jsonl(events)
    assert "schema miss" in blob
    assert "capability_gap" in blob


def test_build_gap_log_paths_and_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert isinstance(build_gap_log().sink, NullGapSink)
    assert isinstance(build_gap_log(in_memory=True).sink, InMemoryGapSink)

    path = tmp_path / "g.jsonl"
    j = build_gap_log(gaps_path=path)
    assert isinstance(j.sink, JsonlGapSink)

    monkeypatch.setenv("XAIKIT_GAPS_PATH", str(path))
    from_env = build_gap_log(from_env=True)
    assert isinstance(from_env.sink, JsonlGapSink)

    monkeypatch.delenv("XAIKIT_GAPS_PATH", raising=False)
    assert isinstance(build_gap_log(from_env=True).sink, NullGapSink)


def test_cli_review_jsonl(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "gaps.jsonl"
    log = GapLog(sink=JsonlGapSink(path))
    log.record(feature="demo.chat", note="hole", code="h1")

    reset_gap_log()
    rc = main(["--path", str(path), "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "demo.chat" in out
    assert "h1" in out

    rc2 = main([])
    assert rc2 == 2


def test_process_get_set() -> None:
    reset_gap_log()
    assert get_gap_log() is None
    injected = GapLog(sink=InMemoryGapSink())
    set_gap_log(injected)
    assert get_gap_log() is injected
    reset_gap_log()
    assert get_gap_log() is None
