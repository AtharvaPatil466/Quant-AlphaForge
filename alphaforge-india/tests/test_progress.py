"""Tests for ingest.progress — checkpoint-reading download monitor."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from ingest import progress as P


def _write_checkpoint(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


# ---------------------------------------------------------------------------
# read_checkpoint
# ---------------------------------------------------------------------------

def test_read_checkpoint_missing_returns_empty(tmp_path: Path):
    assert P.read_checkpoint(tmp_path / "nowhere.jsonl") == []


def test_read_checkpoint_parses_jsonl(tmp_path: Path):
    p = tmp_path / "cp.jsonl"
    _write_checkpoint(p, [
        {"date": "2024-01-08", "source": "unified", "result": "ok",
         "status": 200, "bytes": 1234, "attempts": 1,
         "completed_at": "2026-05-20T10:00:00Z"},
        {"date": "2024-01-09", "source": "unified", "result": "ok",
         "status": 200, "bytes": 5678, "attempts": 1,
         "completed_at": "2026-05-20T10:00:05Z"},
    ])
    rows = P.read_checkpoint(p)
    assert len(rows) == 2
    assert rows[0]["date"] == "2024-01-08"


def test_read_checkpoint_skips_malformed_lines(tmp_path: Path):
    p = tmp_path / "cp.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"date": "2024-01-08", "source": "unified",
                    "result": "ok", "status": 200, "bytes": 1,
                    "attempts": 1, "completed_at": "t"}) + "\n"
        "not-a-json-line\n"
        + json.dumps({"date": "2024-01-09", "source": "unified",
                      "result": "ok", "status": 200, "bytes": 1,
                      "attempts": 1, "completed_at": "t"}) + "\n"
    )
    assert len(P.read_checkpoint(p)) == 2


# ---------------------------------------------------------------------------
# summarize
# ---------------------------------------------------------------------------

def _ok(d: str, source: str = "unified", completed_at: str = "2026-05-20T10:00:00Z") -> dict:
    return {"date": d, "source": source, "result": "ok", "status": 200,
            "bytes": 100, "attempts": 1, "completed_at": completed_at}


def _nf(d: str, source: str = "unified") -> dict:
    return {"date": d, "source": source, "result": "not_found", "status": 404,
            "bytes": 0, "attempts": 1, "completed_at": "2026-05-20T10:00:00Z"}


def _failed(d: str, error: str = "timeout", source: str = "unified") -> dict:
    return {"date": d, "source": source, "result": "failed", "status": 500,
            "bytes": 0, "attempts": 3, "completed_at": "2026-05-20T10:00:00Z",
            "error": error}


def _halted(d: str, status: int = 403, source: str = "unified") -> dict:
    return {"date": d, "source": source, "result": "halted", "status": status,
            "bytes": 0, "attempts": 1, "completed_at": "2026-05-20T10:00:00Z",
            "error": f"halt status {status}"}


def test_summarize_counts_per_result_type():
    rows = [_ok("2024-01-08"), _ok("2024-01-09"), _nf("2024-01-10"),
            _failed("2024-01-11"), _halted("2024-01-12")]
    s = P.summarize(rows)
    assert s.total_attempts == 5
    assert s.ok == 2
    assert s.not_found == 1
    assert s.failed == 1
    assert s.halted == 1


def test_summarize_per_year_ok_counts():
    rows = [_ok("2010-01-04"), _ok("2010-06-15"), _ok("2024-01-08"),
            _nf("2010-08-15")]
    s = P.summarize(rows)
    assert s.per_year_ok == {2010: 2, 2024: 1}
    assert s.per_year_not_found == {2010: 1}


def test_summarize_first_and_last_attempt():
    rows = [
        _ok("2024-01-08", completed_at="2026-05-20T10:00:00Z"),
        _ok("2024-01-09", completed_at="2026-05-20T10:00:30Z"),
        _ok("2024-01-10", completed_at="2026-05-20T10:01:00Z"),
    ]
    s = P.summarize(rows)
    assert s.first_attempt_at.isoformat().startswith("2026-05-20T10:00:00")
    assert s.last_attempt_at.isoformat().startswith("2026-05-20T10:01:00")


def test_summarize_since_filter_excludes_older_rows():
    rows = [_ok("2010-01-04"), _ok("2024-01-08")]
    s = P.summarize(rows, since=date(2020, 1, 1))
    assert s.total_attempts == 1


def test_summarize_recent_failures_capped_at_10():
    rows = [_failed(f"2024-01-{i:02d}") for i in range(1, 25)]
    s = P.summarize(rows)
    assert len(s.recent_failures) == 10
    # Should be the LAST 10, not the first.
    assert s.recent_failures[-1]["date"] == "2024-01-24"


def test_summarize_recent_halts_surfaces_403():
    rows = [_ok("2024-01-08"), _halted("2024-01-09", status=403)]
    s = P.summarize(rows)
    assert len(s.recent_halts) == 1
    assert s.recent_halts[0]["status"] == 403


# ---------------------------------------------------------------------------
# estimate_eta
# ---------------------------------------------------------------------------

def test_estimate_eta_no_data():
    s = P.ProgressSnapshot(
        total_attempts=0, ok=0, not_found=0, failed=0, halted=0,
        first_attempt_at=None, last_attempt_at=None,
        per_year_ok={}, per_year_not_found={},
        recent_failures=[], recent_halts=[],
    )
    assert "no" in P.estimate_eta(s).lower()


def test_estimate_eta_emits_string_when_data_present():
    rows = [_ok("2024-01-08", completed_at="2026-05-20T10:00:00Z"),
            _ok("2024-01-09", completed_at="2026-05-20T11:00:00Z")]
    s = P.summarize(rows)
    eta = P.estimate_eta(s)
    # We don't assert a specific number — just that the function returns
    # a non-empty string and doesn't blow up.
    assert isinstance(eta, str)
    assert len(eta) > 0


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------

def test_render_contains_all_section_headers():
    rows = [_ok("2024-01-08"), _nf("2024-01-09"), _failed("2024-01-10")]
    s = P.summarize(rows)
    text = P.render(s)
    assert "Total attempts" in text
    assert "Per-year coverage" in text
    assert "ETA estimate" in text


def test_render_surfaces_halt_warning():
    rows = [_halted("2024-01-08", status=403)]
    s = P.summarize(rows)
    text = P.render(s)
    assert "HALT" in text or "halt" in text
    assert "403" in text


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def test_main_nonzero_when_no_checkpoint(tmp_path: Path, capsys):
    rc = P.main(["--data-root", str(tmp_path / "nowhere")])
    assert rc == 1
    captured = capsys.readouterr()
    assert "No checkpoint" in captured.out


def test_main_prints_summary_when_checkpoint_exists(tmp_path: Path, capsys):
    cp = tmp_path / "processed" / "_download_checkpoint.jsonl"
    _write_checkpoint(cp, [_ok("2024-01-08"), _ok("2024-01-09")])
    rc = P.main(["--data-root", str(tmp_path)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "Total attempts logged: 2" in captured.out
