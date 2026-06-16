"""Unit tests for validation.validator — all three Phase 0 gates."""
from __future__ import annotations

import json

import pandas as pd
import pytest

from ingest import schema as S
from validation import validator as V


def _row(ticker="A", category="Crypto", result="yes", settlement_value=1.0,
         close_time=200, entry_snapshot_ts=100, volume_fp=10.0):
    return {
        "ticker": ticker, "event_ticker": "E", "series_ticker": "S",
        "category": category, "market_type": "binary",
        "open_time": 1, "close_time": close_time, "settlement_ts": close_time + 10,
        "result": result, "settlement_value": settlement_value,
        "entry_price": 0.5, "implied_prob": 0.5,
        "entry_snapshot_ts": entry_snapshot_ts,
        "yes_bid": 0.49, "yes_ask": 0.51, "volume_fp": volume_fp,
    }


def _frame(rows):
    return pd.DataFrame(rows)[list(S.COLUMNS)].astype(S.DTYPES)


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------

def test_coverage_skips_on_empty():
    r = V.check_coverage(S.empty_frame())
    assert r.status == V.Status.SKIP.value


def test_coverage_fail_below_floor():
    df = _frame([_row(f"T{i}") for i in range(5)])
    r = V.check_coverage(df)
    assert r.status == V.Status.FAIL.value
    assert r.metrics["n_volume_bearing"] == 5


def test_coverage_pass_and_category_breakdown():
    rows = ([_row(f"C{i}", category="Crypto") for i in range(150)]
            + [_row(f"S{i}", category="Sports") for i in range(60)])
    df = _frame(rows)
    r = V.check_coverage(df)
    assert r.status == V.Status.PASS.value
    assert r.metrics["by_category"]["Crypto"] == 150
    assert r.metrics["by_category"]["Sports"] == 60


def test_coverage_uncategorized_label():
    rows = [_row(f"U{i}", category="") for i in range(V.MIN_RESOLVED_CONTRACTS)]
    df = _frame(rows)
    r = V.check_coverage(df)
    assert "(uncategorized)" in r.metrics["by_category"]


# ---------------------------------------------------------------------------
# Resolution integrity
# ---------------------------------------------------------------------------

def test_resolution_integrity_all_consistent():
    rows = ([_row(f"Y{i}", result="yes", settlement_value=1.0) for i in range(50)]
            + [_row(f"N{i}", result="no", settlement_value=0.0) for i in range(50)])
    r = V.check_resolution_integrity(_frame(rows))
    assert r.status == V.Status.PASS.value
    assert r.metrics["fraction_ok"] == pytest.approx(1.0)


def test_resolution_integrity_flags_inconsistent_settlement():
    # YES but settlement 0.0 -> inconsistent. 1 bad in 100 = 99% < 99.9% -> FAIL.
    rows = [_row(f"Y{i}", result="yes", settlement_value=1.0) for i in range(99)]
    rows.append(_row("BAD", result="yes", settlement_value=0.0))
    r = V.check_resolution_integrity(_frame(rows))
    assert r.status == V.Status.FAIL.value
    assert r.metrics["n_bad_settlement"] == 1


def test_resolution_integrity_flags_bad_result():
    rows = [_row(f"Y{i}", result="yes", settlement_value=1.0) for i in range(2000)]
    rows.append(_row("BADRES", result="maybe", settlement_value=1.0))
    r = V.check_resolution_integrity(_frame(rows))
    # 2000/2001 = 99.95% >= 99.9% -> PASS, but the bad result is counted.
    assert r.metrics["n_bad_result"] == 1
    assert r.status == V.Status.PASS.value


def test_resolution_integrity_threshold_boundary_fail():
    # Exactly 99.8% consistent -> below 99.9% -> FAIL.
    rows = [_row(f"Y{i}", result="yes", settlement_value=1.0) for i in range(998)]
    rows += [_row(f"B{i}", result="yes", settlement_value=0.0) for i in range(2)]
    r = V.check_resolution_integrity(_frame(rows))
    assert r.status == V.Status.FAIL.value


# ---------------------------------------------------------------------------
# No-look-ahead
# ---------------------------------------------------------------------------

def test_no_lookahead_all_before_close():
    rows = [_row(f"T{i}", close_time=200, entry_snapshot_ts=100) for i in range(50)]
    r = V.check_no_lookahead(_frame(rows))
    assert r.status == V.Status.PASS.value
    assert r.metrics["fraction_ok"] == pytest.approx(1.0)


def test_no_lookahead_fails_on_any_violation():
    rows = [_row(f"T{i}", close_time=200, entry_snapshot_ts=100) for i in range(99)]
    rows.append(_row("PEEK", close_time=200, entry_snapshot_ts=250))  # after close!
    r = V.check_no_lookahead(_frame(rows))
    assert r.status == V.Status.FAIL.value
    assert "PEEK" in r.errors[0]


def test_no_lookahead_fails_on_snapshot_equal_close():
    rows = [_row("EQ", close_time=200, entry_snapshot_ts=200)]
    r = V.check_no_lookahead(_frame(rows))
    assert r.status == V.Status.FAIL.value


def test_no_lookahead_fails_on_missing_snapshot():
    rows = [_row("MISS", close_time=200, entry_snapshot_ts=0)]
    r = V.check_no_lookahead(_frame(rows))
    assert r.status == V.Status.FAIL.value


# ---------------------------------------------------------------------------
# Orchestration + reporting
# ---------------------------------------------------------------------------

def test_run_all_and_render(tmp_path):
    rows = ([_row(f"C{i}", category="Crypto") for i in range(150)]
            + [_row(f"S{i}", category="Sports") for i in range(60)])
    df = _frame(rows)
    results = V.run_all_checks(df)
    assert all(r.status == V.Status.PASS.value for r in results)
    md = V.render_markdown(results)
    assert "Category coverage" in md
    js = V.results_to_json(results)
    assert js["overall"] == "PASS"
    assert not V.has_blocking_failure(results)


def test_load_resolved_reads_and_dedups(tmp_path):
    from ingest.downloader import write_rows_parquet
    rdir = tmp_path / "processed" / "resolved"
    write_rows_parquet([_row("A"), _row("B")], rdir / "part-00000.parquet")
    write_rows_parquet([_row("B"), _row("C")], rdir / "part-00001.parquet")  # B dup
    df = V.load_resolved(tmp_path)
    assert sorted(df["ticker"].tolist()) == ["A", "B", "C"]


def test_cli_exit_nonzero_on_failure(tmp_path):
    from ingest.downloader import write_rows_parquet
    rdir = tmp_path / "processed" / "resolved"
    # 1 row only -> coverage FAIL -> CLI returns 1.
    write_rows_parquet([_row("A")], rdir / "part-00000.parquet")
    rc = V.main(["--data-root", str(tmp_path),
                 "--report-md", str(tmp_path / "r.md"),
                 "--report-json", str(tmp_path / "r.json")])
    assert rc == 1
    assert (tmp_path / "r.md").exists()
    assert json.loads((tmp_path / "r.json").read_text())["overall"] == "FAIL"
