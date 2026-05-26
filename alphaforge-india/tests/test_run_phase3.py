"""Tests for research.run_phase3 — the Phase 3 gauntlet orchestrator."""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research import run_phase3 as RP
from signals import delivery_pct as DP


# ---------------------------------------------------------------------------
# parse_deliv_pct_trial_name
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,expected_lb,expected_bucket,expected_h", [
    ("deliv_pct_L10_Q5_H5", 10, "quintile", 5),
    ("deliv_pct_L20_Q10_H21", 20, "decile", 21),
    ("deliv_pct_L60_Q5_H10", 60, "quintile", 10),
])
def test_parse_deliv_pct_trial_name_roundtrip(
    name, expected_lb, expected_bucket, expected_h
):
    trial = RP.parse_deliv_pct_trial_name(name)
    assert trial is not None
    assert trial.lookback == expected_lb
    assert trial.bucket == expected_bucket
    assert trial.holding_period == expected_h
    # Round-trip: name → trial → name
    assert trial.trial_name == name


def test_parse_deliv_pct_trial_name_returns_none_on_malformed():
    for bad in ("not_a_trial", "deliv_pct_LX_Q5_H5", "deliv_pct_L20", ""):
        assert RP.parse_deliv_pct_trial_name(bad) is None


# ---------------------------------------------------------------------------
# load_phase1_survivors
# ---------------------------------------------------------------------------

def test_load_phase1_survivors_reads_json(tmp_path: Path):
    p = tmp_path / "phase1.json"
    p.write_text(json.dumps({
        "survivors_deliv_pct": ["deliv_pct_L20_Q5_H5"],
        "survivors_foe": ["foe_3x3", "foe_5x5"],
    }))
    deliv, foe = RP.load_phase1_survivors(p)
    assert deliv == ["deliv_pct_L20_Q5_H5"]
    assert foe == ["foe_3x3", "foe_5x5"]


def test_load_phase1_survivors_empty_lists(tmp_path: Path):
    p = tmp_path / "phase1.json"
    p.write_text(json.dumps({
        "survivors_deliv_pct": [],
        "survivors_foe": [],
    }))
    deliv, foe = RP.load_phase1_survivors(p)
    assert deliv == []
    assert foe == []


def test_load_phase1_survivors_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        RP.load_phase1_survivors(tmp_path / "nowhere.json")


# ---------------------------------------------------------------------------
# Synthetic data builders
# ---------------------------------------------------------------------------

def _build_oos_panels(
    n_days: int = 1200,        # ~ 4.5 years of trading days
    n_symbols: int = 40,
    deliv_to_return_beta: float = 0.005,
    noise_std: float = 0.001,
    lookback: int = 20,
    seed: int = 7,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """OOS-window synthetic data — starts in 2015 to fall inside OOS_A."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2015-01-05", periods=n_days, freq="B")
    symbols = [f"SYM{i:02d}" for i in range(n_symbols)]

    deliv_pct = pd.DataFrame(
        rng.uniform(20, 80, size=(n_days, n_symbols)),
        index=dates, columns=symbols,
    )
    min_obs = max(1, lookback // 2)
    rm = deliv_pct.rolling(lookback, min_periods=min_obs).mean()
    cs_mean = rm.mean(axis=1)
    cs_std = rm.std(axis=1).replace(0.0, np.nan)
    signal = rm.sub(cs_mean, axis=0).div(cs_std, axis=0).fillna(0.0)
    daily_ret = signal * deliv_to_return_beta + rng.normal(
        0.0, noise_std, size=(n_days, n_symbols)
    )
    close = (1.0 + daily_ret).cumprod() * 100.0
    return close, deliv_pct


def _make_processed_parquet(tmp_path: Path, close: pd.DataFrame,
                             deliv_pct: pd.DataFrame) -> Path:
    """Stage the synthetic panels as a `processed/bhavcopy/*.parquet` tree."""
    processed = tmp_path / "processed" / "bhavcopy"
    processed.mkdir(parents=True)
    rows = []
    for d in close.index:
        for sym in close.columns:
            c = close.loc[d, sym]
            dp = deliv_pct.loc[d, sym]
            if not np.isfinite(c):
                continue
            rows.append({
                "date": d, "symbol": sym, "series": "EQ",
                "open": c, "high": c * 1.005, "low": c * 0.995,
                "close": c, "last": c, "prev_close": c,
                "volume": 10_000, "value": c * 10_000, "num_trades": 50,
                "deliv_qty": int(0.5 * 10_000),
                "deliv_pct": dp, "source_era": "unified",
            })
    pd.DataFrame(rows).to_parquet(processed / "bhavcopy_oos.parquet", index=False)
    return processed


# ---------------------------------------------------------------------------
# load_oos_panel
# ---------------------------------------------------------------------------

def test_load_oos_panel_pivots_correctly(tmp_path: Path):
    close, deliv = _build_oos_panels(n_days=20, n_symbols=3)
    processed = _make_processed_parquet(tmp_path, close, deliv)
    out_close, out_deliv = RP.load_oos_panel(processed)
    assert set(out_close.columns) == set(close.columns)
    assert len(out_close) > 0


def test_load_oos_panel_filters_to_oos_range(tmp_path: Path):
    # Build with dates from 2010 (pre-OOS) and 2015 (in OOS).
    dates_2010 = pd.date_range("2010-01-04", periods=5, freq="B")
    dates_2015 = pd.date_range("2015-01-05", periods=5, freq="B")
    rows = []
    for d in list(dates_2010) + list(dates_2015):
        rows.append({
            "date": d, "symbol": "X", "series": "EQ",
            "open": 100, "high": 101, "low": 99, "close": 100,
            "last": 100, "prev_close": 100, "volume": 1, "value": 100,
            "num_trades": 1, "deliv_qty": 0, "deliv_pct": 50.0,
            "source_era": "unified",
        })
    p = tmp_path / "processed" / "bhavcopy"
    p.mkdir(parents=True)
    pd.DataFrame(rows).to_parquet(p / "bhavcopy.parquet")

    close, _ = RP.load_oos_panel(p)
    # Only 2015 rows survive the OOS filter.
    assert (close.index >= pd.Timestamp(RP.OOS_DATA_START)).all()


def test_load_oos_panel_raises_on_no_files(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        RP.load_oos_panel(tmp_path / "missing")


# ---------------------------------------------------------------------------
# compute_long_short_returns
# ---------------------------------------------------------------------------

def test_compute_long_short_returns_returns_series_with_correct_name():
    close, deliv = _build_oos_panels(n_days=200, n_symbols=20)
    trial = DP.DeliveryPctSignal(lookback=10, bucket="quintile", holding_period=5)
    out = RP.compute_long_short_returns(close, deliv, trial)
    assert isinstance(out, pd.Series)
    assert out.name == trial.trial_name
    assert not out.empty


def test_compute_long_short_returns_handles_empty_input():
    out = RP.compute_long_short_returns(
        pd.DataFrame(), pd.DataFrame(),
        DP.DeliveryPctSignal(lookback=10, bucket="quintile", holding_period=5),
    )
    assert out.empty


def test_compute_long_short_returns_charges_cost_on_rebalance_days():
    """A pure-noise return panel + nonzero rebalance cost: portfolio return on
    rebalance dates should be ≤ portfolio return on non-rebalance dates on
    average (cost subtracts)."""
    rng = np.random.default_rng(99)
    n_days, n_symbols = 200, 20
    dates = pd.date_range("2015-01-05", periods=n_days, freq="B")
    close = pd.DataFrame(
        100.0 * (1.0 + rng.normal(0.0, 0.001, (n_days, n_symbols))).cumprod(axis=0),
        index=dates, columns=[f"S{i}" for i in range(n_symbols)],
    )
    deliv = pd.DataFrame(
        rng.uniform(20, 80, (n_days, n_symbols)),
        index=dates, columns=close.columns,
    )
    trial = DP.DeliveryPctSignal(lookback=10, bucket="quintile", holding_period=5)
    ret = RP.compute_long_short_returns(
        close, deliv, trial,
        rebalance_cost_bps=100.0,         # exaggerated cost so mean is visible
        rebalance_impact_bps=0.0,
    )
    rebal_idx = ret.index[::trial.holding_period]
    rebal_mean = ret.loc[ret.index.isin(rebal_idx)].mean()
    nonrebal_mean = ret.loc[~ret.index.isin(rebal_idx)].mean()
    assert rebal_mean < nonrebal_mean, (
        f"rebal_mean={rebal_mean} not lower than nonrebal_mean={nonrebal_mean}"
    )


# ---------------------------------------------------------------------------
# evaluate_trial_deliv_pct
# ---------------------------------------------------------------------------

def test_evaluate_trial_deliv_pct_returns_all_five_gates():
    close, deliv = _build_oos_panels(n_days=1500, n_symbols=30)
    result = RP.evaluate_trial_deliv_pct(
        "deliv_pct_L20_Q5_H5", close, deliv, n_trials=22,
    )
    assert not result.skipped
    assert len(result.per_gate) == 5
    # Each gate has the expected keys.
    for g in result.per_gate:
        assert "gate_name" in g
        assert "passed" in g
        assert "summary" in g


def test_evaluate_trial_deliv_pct_skips_on_malformed_name():
    close, deliv = _build_oos_panels(n_days=200, n_symbols=10)
    result = RP.evaluate_trial_deliv_pct("not_a_real_trial", close, deliv)
    assert result.skipped
    assert "parse" in result.skip_reason.lower()


def test_evaluate_trial_deliv_pct_skips_on_empty_returns():
    result = RP.evaluate_trial_deliv_pct(
        "deliv_pct_L10_Q5_H5", pd.DataFrame(), pd.DataFrame(),
    )
    assert result.skipped


# ---------------------------------------------------------------------------
# evaluate_trial_fo_expiry — always SKIP
# ---------------------------------------------------------------------------

def test_evaluate_trial_fo_expiry_emits_skip():
    r = RP.evaluate_trial_fo_expiry("foe_3x3")
    assert r.skipped
    assert "F&O" in r.skip_reason or "OI" in r.skip_reason


# ---------------------------------------------------------------------------
# classify_phase3 — §12 decision matrix
# ---------------------------------------------------------------------------

def _make_trial_verdict(name: str, all_pass: bool = False,
                          gates_14_pass: bool = False,
                          gate5_pass: bool = False,
                          skipped: bool = False) -> RP.TrialVerdict:
    return RP.TrialVerdict(
        trial_name=name, family="delivery_pct",
        gauntlet_passed=all_pass,
        gates_1_to_4_passed=gates_14_pass or all_pass,
        gate5_passed=gate5_pass or all_pass,
        per_gate=[],
        skipped=skipped, skip_reason="" if not skipped else "stub",
    )


def test_classify_phase3_deploy_ready_when_any_trial_passes_all_5():
    verdicts = [
        _make_trial_verdict("t1", all_pass=True),
        _make_trial_verdict("t2"),
    ]
    label, surv, cond, fail = RP.classify_phase3(verdicts)
    assert label == "DEPLOY-READY"
    assert surv == ["t1"]


def test_classify_phase3_conditional_when_gates_14_pass_only():
    verdicts = [
        _make_trial_verdict("t1", gates_14_pass=True, gate5_pass=False),
        _make_trial_verdict("t2"),
    ]
    label, surv, cond, fail = RP.classify_phase3(verdicts)
    assert label == "CONDITIONAL"
    assert surv == []
    assert cond == ["t1"]


def test_classify_phase3_closed_failed_when_no_passes():
    verdicts = [
        _make_trial_verdict("t1"),
        _make_trial_verdict("t2"),
    ]
    label, surv, cond, fail = RP.classify_phase3(verdicts)
    assert label == "CLOSED FAILED"
    assert surv == [] and cond == []
    assert fail == ["t1", "t2"]


def test_classify_phase3_ignores_skipped_for_pass_tally():
    verdicts = [
        _make_trial_verdict("t1", skipped=True),
        _make_trial_verdict("t2", all_pass=True),
    ]
    label, surv, cond, fail = RP.classify_phase3(verdicts)
    assert label == "DEPLOY-READY"
    assert surv == ["t2"]


# ---------------------------------------------------------------------------
# build_phase3_verdict + render_markdown_verdict
# ---------------------------------------------------------------------------

def test_build_phase3_verdict_records_residualization_state():
    v_with = RP.build_phase3_verdict([], factor_residualization_applied=True)
    v_without = RP.build_phase3_verdict([], factor_residualization_applied=False)
    assert v_with.factor_residualization_applied is True
    assert v_without.factor_residualization_applied is False


def test_render_markdown_closed_failed_section():
    v = RP.build_phase3_verdict(
        [_make_trial_verdict("t1")], factor_residualization_applied=True,
    )
    md = RP.render_markdown_verdict(v)
    assert "CLOSED FAILED" in md
    assert "Substrate #6" in md


def test_render_markdown_conditional_section():
    v = RP.build_phase3_verdict(
        [_make_trial_verdict("t_cond", gates_14_pass=True, gate5_pass=False)],
        factor_residualization_applied=True,
    )
    md = RP.render_markdown_verdict(v)
    assert "CONDITIONAL" in md
    assert "regime stress" in md.lower()


def test_render_markdown_deploy_ready_section():
    v = RP.build_phase3_verdict(
        [_make_trial_verdict("t_pass", all_pass=True)],
        factor_residualization_applied=True,
    )
    md = RP.render_markdown_verdict(v)
    assert "DEPLOY-READY" in md
    assert "Phase 4" in md


def test_render_markdown_warns_when_residualization_skipped():
    v = RP.build_phase3_verdict(
        [_make_trial_verdict("t_pass", all_pass=True)],
        factor_residualization_applied=False,
    )
    md = RP.render_markdown_verdict(v)
    assert "Residualization NOT applied" in md
    assert "§7" in md


def test_render_markdown_table_lists_all_trials():
    v = RP.build_phase3_verdict(
        [
            _make_trial_verdict("t_pass", all_pass=True),
            _make_trial_verdict("t_skip", skipped=True),
            _make_trial_verdict("t_fail"),
        ],
        factor_residualization_applied=True,
    )
    md = RP.render_markdown_verdict(v)
    assert "t_pass" in md
    assert "t_skip" in md
    assert "t_fail" in md


# ---------------------------------------------------------------------------
# Integration: end-to-end via main()
# ---------------------------------------------------------------------------

def test_main_short_circuits_when_zero_survivors(tmp_path: Path):
    p1 = tmp_path / "phase1.json"
    p1.write_text(json.dumps({
        "survivors_deliv_pct": [],
        "survivors_foe": [],
    }))
    results = tmp_path / "phase3_results.json"
    verdict_md = tmp_path / "verdict.md"
    rc = RP.main([
        "--phase1-results", str(p1),
        "--processed-dir", str(tmp_path / "nodata"),  # doesn't exist
        "--results-json", str(results),
        "--verdict-md", str(verdict_md),
        "--design-doc", str(tmp_path / "noexist"),
    ])
    assert rc == 1  # CLOSED FAILED → nonzero exit
    assert results.exists()
    assert verdict_md.exists()
    j = json.loads(results.read_text())
    assert j["verdict"] == "CLOSED FAILED"
    assert j["total_trials_evaluated"] == 0


def test_main_runs_full_pipeline_with_survivor(tmp_path: Path):
    # Stage synthetic OOS data + a Phase 1 results JSON with one survivor.
    close, deliv = _build_oos_panels(n_days=1500, n_symbols=30,
                                       deliv_to_return_beta=0.005)
    processed = _make_processed_parquet(tmp_path, close, deliv)
    survivor_name = "deliv_pct_L20_Q5_H5"
    p1 = tmp_path / "phase1.json"
    p1.write_text(json.dumps({
        "survivors_deliv_pct": [survivor_name],
        "survivors_foe": [],
    }))
    results = tmp_path / "phase3_results.json"
    verdict_md = tmp_path / "verdict.md"
    rc = RP.main([
        "--phase1-results", str(p1),
        "--processed-dir", str(processed),
        "--results-json", str(results),
        "--verdict-md", str(verdict_md),
        "--design-doc", str(tmp_path / "noexist"),
    ])
    # rc == 0 (DEPLOY-READY) or 1 (CONDITIONAL/CLOSED). Either is valid
    # — the assertion is just that the pipeline runs to completion.
    assert rc in (0, 1)
    j = json.loads(results.read_text())
    assert j["total_trials_evaluated"] == 1
    assert j["trial_verdicts"][0]["trial_name"] == survivor_name
    assert "Gauntlet Verdict" in verdict_md.read_text()
