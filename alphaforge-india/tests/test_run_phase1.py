"""Tests for research.run_phase1 — the Phase 1 orchestrator."""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research import run_phase1 as RP  # noqa: E402
from signals import delivery_pct as DP  # noqa: E402
from signals import fo_expiry as FOE    # noqa: E402


# ---------------------------------------------------------------------------
# _aggregate_ic
# ---------------------------------------------------------------------------

def test_aggregate_ic_returns_mean_and_count():
    s = pd.Series([0.05, 0.10, 0.02], index=pd.date_range("2010-01-01", periods=3))
    mean, n = RP._aggregate_ic(s)
    assert mean == pytest.approx((0.05 + 0.10 + 0.02) / 3)
    assert n == 3


def test_aggregate_ic_empty_returns_none():
    s = pd.Series([], dtype=float)
    mean, n = RP._aggregate_ic(s)
    assert mean is None and n == 0


def test_aggregate_ic_drops_nan():
    s = pd.Series([0.1, np.nan, 0.2])
    mean, n = RP._aggregate_ic(s)
    assert mean == pytest.approx(0.15)
    assert n == 2


# ---------------------------------------------------------------------------
# _rolling_ic_pos_frac
# ---------------------------------------------------------------------------

def test_rolling_ic_pos_frac_all_positive():
    """A purely positive IC series → 100% positive rolling fraction."""
    idx = pd.date_range("2010-01-01", periods=300, freq="B")
    s = pd.Series(0.05, index=idx)
    frac, n = RP._rolling_ic_pos_frac(s, window_days=252)
    assert frac == 1.0
    assert n > 0


def test_rolling_ic_pos_frac_all_negative():
    idx = pd.date_range("2010-01-01", periods=300, freq="B")
    s = pd.Series(-0.05, index=idx)
    frac, n = RP._rolling_ic_pos_frac(s, window_days=252)
    assert frac == 0.0


def test_rolling_ic_pos_frac_too_few_returns_none():
    s = pd.Series([0.1, 0.2], index=pd.date_range("2010-01-01", periods=2))
    frac, n = RP._rolling_ic_pos_frac(s)
    assert frac is None and n == 0


# ---------------------------------------------------------------------------
# analyze_deliv_pct_trial — fixture builders
# ---------------------------------------------------------------------------

def _build_synthetic_panels(
    n_days: int = 600,
    n_symbols: int = 30,
    deliv_to_return_beta: float = 0.005,
    noise_std: float = 0.001,
    lookback: int = 20,
    seed: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Synthetic panel where the ROLLING-MEAN z-score of deliv_pct drives
    forward returns (matching what `DeliveryPctSignal` actually computes).

    beta > 0 → high IC at the trial's horizon. beta == 0 → pure noise.
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2004-01-05", periods=n_days, freq="B")
    symbols = [f"SYM{i:02d}" for i in range(n_symbols)]

    deliv_pct = pd.DataFrame(
        rng.uniform(20, 80, size=(n_days, n_symbols)),
        index=dates, columns=symbols,
    )

    # Mimic DeliveryPctSignal.compute_signal exactly so daily_ret ~ signal.
    min_obs = max(1, lookback // 2)
    rolling_mean = deliv_pct.rolling(window=lookback, min_periods=min_obs).mean()
    cs_mean = rolling_mean.mean(axis=1)
    cs_std = rolling_mean.std(axis=1).replace(0.0, np.nan)
    signal_z = rolling_mean.sub(cs_mean, axis=0).div(cs_std, axis=0).fillna(0.0)

    # daily_ret[t, sym] = beta * signal[t, sym] + noise. The signal is
    # autocorrelated (rolling mean → slow drift), so multi-day forward
    # returns inherit positive IC with the same-day signal.
    daily_ret = signal_z * deliv_to_return_beta + rng.normal(
        0.0, noise_std, size=(n_days, n_symbols)
    )
    close = (1.0 + daily_ret).cumprod() * 100.0
    return close, deliv_pct


def test_analyze_deliv_pct_trial_strong_signal_passes():
    close, deliv_pct = _build_synthetic_panels(
        n_days=700, deliv_to_return_beta=0.15, noise_std=0.002,
    )
    trial = DP.DeliveryPctSignal(lookback=20, bucket="quintile", holding_period=5)
    # Use sub-window split before any data so both windows are populated.
    result = RP.analyze_deliv_pct_trial(
        trial, close, deliv_pct,
        sub_window_start=close.index[len(close) // 3].date(),
    )
    assert result.ic_full_is is not None
    assert result.ic_subwindow is not None
    # Strong synthetic signal → IC > 0.03.
    assert abs(result.ic_full_is) > 0.03, f"got IC {result.ic_full_is}"
    assert result.passes_ic_threshold


def test_analyze_deliv_pct_trial_no_signal_fails_threshold():
    close, deliv_pct = _build_synthetic_panels(
        n_days=700, deliv_to_return_beta=0.0, noise_std=0.02,
    )
    trial = DP.DeliveryPctSignal(lookback=20, bucket="quintile", holding_period=5)
    result = RP.analyze_deliv_pct_trial(
        trial, close, deliv_pct,
        sub_window_start=close.index[len(close) // 3].date(),
    )
    # No real signal → IC near zero → threshold fails.
    assert not result.passes_phase1
    # The reason text should mention the IC threshold or the sign disagreement.
    assert ("0.03" in result.reason
            or "sign" in result.reason.lower()
            or "rolling" in result.reason.lower())


def test_analyze_deliv_pct_trial_handles_empty_data():
    empty_close = pd.DataFrame()
    empty_deliv = pd.DataFrame()
    trial = DP.DeliveryPctSignal(lookback=20, bucket="quintile", holding_period=5)
    result = RP.analyze_deliv_pct_trial(trial, empty_close, empty_deliv)
    assert result.ic_full_is is None
    assert not result.passes_phase1


# ---------------------------------------------------------------------------
# apply_membership_mask
# ---------------------------------------------------------------------------

def test_apply_membership_mask_none_returns_panel_unchanged():
    panel = pd.DataFrame({"A": [1, 2], "B": [3, 4]},
                         index=pd.date_range("2010-01-01", periods=2))
    out = RP.apply_membership_mask(panel, None)
    pd.testing.assert_frame_equal(out, panel)


def test_apply_membership_mask_masks_non_members():
    idx = pd.date_range("2010-01-01", periods=2)
    panel = pd.DataFrame({"A": [1.0, 2.0], "B": [3.0, 4.0]}, index=idx)
    mask = pd.DataFrame({"A": [True, False], "B": [True, True]}, index=idx)
    out = RP.apply_membership_mask(panel, mask)
    assert pd.isna(out.loc[idx[1], "A"])
    assert out.loc[idx[0], "A"] == 1.0
    assert out.loc[idx[1], "B"] == 4.0


# ---------------------------------------------------------------------------
# load_bhavcopy_panel
# ---------------------------------------------------------------------------

def test_load_bhavcopy_panel_pivots_correctly(tmp_path: Path):
    rows = []
    for d in pd.date_range("2010-01-04", periods=5, freq="B"):
        for sym, deliv in [("X", 50.0), ("Y", 75.0)]:
            rows.append({
                "date": d, "symbol": sym, "series": "EQ",
                "open": 100.0, "high": 105.0, "low": 99.0,
                "close": 100.0 + (5.0 if sym == "Y" else 0.0),
                "last": 100.0, "prev_close": 100.0,
                "volume": 1000, "value": 100000.0, "num_trades": 10,
                "deliv_qty": 500, "deliv_pct": deliv, "source_era": "unified",
            })
    df = pd.DataFrame(rows)
    processed = tmp_path / "processed" / "bhavcopy"
    processed.mkdir(parents=True)
    df.to_parquet(processed / "bhavcopy_2010.parquet")

    close, deliv = RP.load_bhavcopy_panel(
        processed, date(2010, 1, 1), date(2010, 12, 31)
    )
    assert set(close.columns) == {"X", "Y"}
    assert close.loc[pd.Timestamp("2010-01-04"), "X"] == 100.0
    assert close.loc[pd.Timestamp("2010-01-04"), "Y"] == 105.0
    assert deliv.loc[pd.Timestamp("2010-01-04"), "Y"] == 75.0


def test_load_bhavcopy_panel_filters_to_is_window(tmp_path: Path):
    rows = []
    for d in pd.date_range("2003-01-01", periods=5, freq="B"):
        rows.append({
            "date": d, "symbol": "A", "series": "EQ",
            "open": 1, "high": 1, "low": 1, "close": 1, "last": 1, "prev_close": 1,
            "volume": 1, "value": 1, "num_trades": 1, "deliv_qty": 1,
            "deliv_pct": 50, "source_era": "legacy+mto",
        })
    for d in pd.date_range("2010-01-04", periods=5, freq="B"):
        rows.append({
            "date": d, "symbol": "A", "series": "EQ",
            "open": 1, "high": 1, "low": 1, "close": 1, "last": 1, "prev_close": 1,
            "volume": 1, "value": 1, "num_trades": 1, "deliv_qty": 1,
            "deliv_pct": 50, "source_era": "legacy+mto",
        })
    pd_dir = tmp_path / "processed" / "bhavcopy"
    pd_dir.mkdir(parents=True)
    pd.DataFrame(rows).to_parquet(pd_dir / "bhavcopy.parquet")

    close, _ = RP.load_bhavcopy_panel(pd_dir, date(2004, 1, 1), date(2014, 12, 31))
    # Only the 2010 rows fall in [2004, 2014].
    assert len(close) == 5
    assert close.index.min() >= pd.Timestamp("2010-01-01")


def test_load_bhavcopy_panel_raises_on_no_files(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        RP.load_bhavcopy_panel(tmp_path / "nowhere", date(2010, 1, 1), date(2010, 1, 5))


# ---------------------------------------------------------------------------
# build_verdict + render
# ---------------------------------------------------------------------------

def _mock_deliv_result(name: str, passes: bool) -> RP.DeliveryPctPhase1Result:
    return RP.DeliveryPctPhase1Result(
        trial_name=name, lookback=20, bucket="quintile", holding_period=5,
        ic_full_is=0.05 if passes else 0.001, ic_full_is_n=100,
        rolling_ic_full_pos_frac=0.8 if passes else 0.4,
        rolling_ic_full_n=50,
        ic_subwindow=0.04 if passes else -0.02, ic_subwindow_n=60,
        rolling_ic_sub_pos_frac=0.75 if passes else 0.5,
        rolling_ic_sub_n=30,
        passes_ic_threshold=passes,
        passes_sign_agreement=passes,
        passes_rolling_positivity=passes,
        passes_phase1=passes,
        reason="ok" if passes else "IC below 0.03",
    )


def test_build_verdict_no_survivors_marks_closed_failed():
    deliv = [_mock_deliv_result(f"t{i}", False) for i in range(3)]
    v = RP.build_verdict(deliv, [], date(2004, 1, 1), date(2014, 12, 31))
    assert v.closed_failed_at_phase1 is True
    assert v.n_survivors == 0
    assert v.total_trials == 3


def test_build_verdict_with_survivors_not_closed_failed():
    deliv = [
        _mock_deliv_result("t0", True),
        _mock_deliv_result("t1", False),
    ]
    v = RP.build_verdict(deliv, [], date(2004, 1, 1), date(2014, 12, 31))
    assert v.closed_failed_at_phase1 is False
    assert v.n_survivors == 1
    assert "t0" in v.survivors_deliv_pct


def test_render_markdown_verdict_closed_failed_has_headline():
    deliv = [_mock_deliv_result(f"t{i}", False) for i in range(2)]
    v = RP.build_verdict(deliv, [], date(2004, 1, 1), date(2014, 12, 31))
    md = RP.render_markdown_verdict(v)
    assert "CLOSED FAILED" in md
    assert "Substrate #6" in md
    # Failure-reasons table emitted only when there are failures.
    assert "failure reasons" in md.lower()


def test_render_markdown_verdict_survivors_section():
    deliv = [_mock_deliv_result("t0", True), _mock_deliv_result("t1", False)]
    v = RP.build_verdict(deliv, [], date(2004, 1, 1), date(2014, 12, 31))
    md = RP.render_markdown_verdict(v)
    assert "Survivors" in md
    assert "t0" in md
    assert "✓ PASS" in md
    assert "✗ FAIL" in md


def test_render_markdown_verdict_includes_foe_table_when_present():
    foe = [FOE.EventStudyResult(
        trial_name="foe_3x5",
        n_events=120,
        pre_return_mean=-0.003, pre_return_t_stat=-2.5,
        pre_return_p_value=0.02, pre_sign_consistency=0.72,
        post_return_mean=0.001, post_return_t_stat=0.4,
        post_return_p_value=0.6, post_sign_consistency=0.55,
        passed_phase1=True,
    )]
    v = RP.build_verdict([_mock_deliv_result("d0", False)], foe,
                          date(2004, 1, 1), date(2014, 12, 31))
    md = RP.render_markdown_verdict(v)
    assert "F&O Expiry" in md
    assert "foe_3x5" in md


def test_render_markdown_verdict_design_doc_sha_included():
    v = RP.build_verdict([_mock_deliv_result("d", False)], [],
                          date(2004, 1, 1), date(2014, 12, 31),
                          design_doc_sha="3b397262")
    md = RP.render_markdown_verdict(v)
    assert "3b397262" in md


# ---------------------------------------------------------------------------
# Integration: full orchestration with synthetic data
# ---------------------------------------------------------------------------

def test_integration_strong_signal_produces_passes(tmp_path: Path):
    """End-to-end with synthetic data that has a strong embedded signal."""
    close, deliv_pct = _build_synthetic_panels(
        n_days=800, n_symbols=40,
        deliv_to_return_beta=0.20, noise_std=0.001,
    )
    # Run a couple of trials directly to confirm at least one passes.
    trials = DP.enumerate_trials()
    passing = []
    sub_start = close.index[len(close) // 3].date()
    for trial in trials[:6]:  # subset for speed
        r = RP.analyze_deliv_pct_trial(trial, close, deliv_pct,
                                         sub_window_start=sub_start)
        if r.passes_phase1:
            passing.append(r.trial_name)
    assert passing, "synthetic strong-signal data produced 0 passing trials"


def test_integration_zero_signal_produces_zero_survivors():
    """End-to-end with pure-noise data — should produce 0 survivors."""
    close, deliv_pct = _build_synthetic_panels(
        n_days=600, n_symbols=40,
        deliv_to_return_beta=0.0, noise_std=0.02,
        seed=99,
    )
    deliv_results = []
    sub_start = close.index[len(close) // 3].date()
    for trial in DP.enumerate_trials()[:6]:  # subset for speed
        deliv_results.append(
            RP.analyze_deliv_pct_trial(trial, close, deliv_pct,
                                         sub_window_start=sub_start)
        )
    n_pass = sum(1 for r in deliv_results if r.passes_phase1)
    # Under pure noise, no trial should pass all three criteria.
    assert n_pass == 0, f"pure noise produced {n_pass} false survivors"
