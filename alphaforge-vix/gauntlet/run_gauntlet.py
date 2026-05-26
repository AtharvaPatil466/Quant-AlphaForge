"""Master runner — orchestrates the Phase 3 gauntlet.

Per VIX_DESIGN.md §10 + PHASE2_STRATEGY_SPEC.md §1. Iterates every
(trial, variant) combination, runs the backtest, evaluates the six gates
(DSR, bootstrap CI, sign agreement, cost survival, max-DD, CF-Sharpe)
plus the §7 four-factor residualization.

Refuses to run if `VIX_DESIGN.md` SHA does not match the Phase 0 cert
anchor (mirrors `research/phase1_run.py`). Likewise refuses to run if the
Phase 2 spec hash on disk does not match the spec file's current hash.

Output:
    research/GAUNTLET_RESULTS.json    — machine, per (trial, variant) × gate
    research/GAUNTLET_VERDICT.md      — human-readable verdict
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# Repo-importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingest.cboe import build_term_structure_panel  # noqa: E402
from ingest.realized_vol import build_spy_panel  # noqa: E402
from ingest.yfinance_loader import load_ticker  # noqa: E402
from gauntlet import backtest as bt  # noqa: E402
from gauntlet import costs as costs_mod  # noqa: E402
from gauntlet import residualization as resid_mod  # noqa: E402
from gauntlet import stats as stats_mod  # noqa: E402
from gauntlet import strategy as strat  # noqa: E402
from gauntlet import tail_risk as tr  # noqa: E402

log = logging.getLogger("vix.gauntlet")

ROOT = Path(__file__).resolve().parents[1]
DESIGN_DOC = ROOT / "research" / "VIX_DESIGN.md"
PHASE2_SPEC = ROOT / "research" / "PHASE2_STRATEGY_SPEC.md"
PHASE2_SPEC_JSON = ROOT / "research" / "vix_phase2_spec.json"
CERT_JSON = ROOT / "research" / "vix_phase0_certified.json"
RESULTS_JSON = ROOT / "research" / "GAUNTLET_RESULTS.json"
VERDICT_MD = ROOT / "research" / "GAUNTLET_VERDICT.md"

# Pre-committed splits per VIX_DESIGN.md §3.
IS_START = pd.Timestamp("2004-03-26")
IS_END = pd.Timestamp("2014-12-31")
OOS_A_START = pd.Timestamp("2015-01-01")
OOS_A_END = pd.Timestamp("2019-12-31")
OOS_B_START = pd.Timestamp("2020-01-01")

EMBARGO_DAYS = 21  # §3 — 21 trading days at each boundary

DSR_THRESHOLD = 0.95  # §5.1
N_TRIALS_DSR_DENOMINATOR = 28  # §4 — fixed regardless of how many trials run

CF_THRESHOLD = 0.50  # §5.6 (mirrored from tail_risk.py)


# ---------------------------------------------------------------------------
# Anchor verification
# ---------------------------------------------------------------------------

class AnchorError(RuntimeError):
    pass


def verify_anchors() -> tuple[str, str]:
    """Verify (1) VIX_DESIGN.md SHA matches Phase 0 cert, (2) PHASE2_STRATEGY_SPEC.md
    SHA matches vix_phase2_spec.json. Returns the two SHAs."""
    design_sha = hashlib.sha256(DESIGN_DOC.read_bytes()).hexdigest()
    with CERT_JSON.open() as f:
        cert = json.load(f)
    if cert.get("design_doc_sha") != design_sha:
        raise AnchorError(
            f"VIX_DESIGN.md SHA mismatch — design doc edited after Phase 0 cert.\n"
            f"  Cert anchor:  {cert.get('design_doc_sha')}\n"
            f"  Current SHA:  {design_sha}"
        )
    spec_sha = hashlib.sha256(PHASE2_SPEC.read_bytes()).hexdigest()
    with PHASE2_SPEC_JSON.open() as f:
        spec_pin = json.load(f)
    if spec_pin.get("phase2_spec_sha") != spec_sha:
        raise AnchorError(
            f"PHASE2_STRATEGY_SPEC.md SHA mismatch — spec doc edited after pin.\n"
            f"  Pinned SHA:   {spec_pin.get('phase2_spec_sha')}\n"
            f"  Current SHA:  {spec_sha}"
        )
    return design_sha, spec_sha


# ---------------------------------------------------------------------------
# Data loading + market frame assembly
# ---------------------------------------------------------------------------

def load_market_frame(data_root: Path) -> pd.DataFrame:
    """Load all Phase 0 products and assemble the aligned market frame
    consumed by the backtest.

    Schema:
        vix_close, vix_high, svxy_open, svxy_close, vxx_open, vxx_close,
        realized_vol_10, realized_vol_21, realized_vol_63,
        ma63 (VIX MA63), sigma63 (VIX σ63),
        spy_log_return, delta_vix_log (for residualization)
    """
    term_panel = build_term_structure_panel(data_root)
    vix = term_panel["VIX"].dropna()
    # VIX high — re-parse from the CBOE CSV to get the HIGH column.
    vix_csv = pd.read_csv(data_root / "vix_indices" / "VIX.csv")
    vix_csv.columns = [c.strip().lower() for c in vix_csv.columns]
    vix_csv["date"] = pd.to_datetime(vix_csv["date"], format="mixed")
    vix_csv = vix_csv.dropna(subset=["date"]).sort_values("date")
    vix_csv = vix_csv.set_index("date")
    vix_high = vix_csv["high"].astype(float)

    spy_df = load_ticker("SPY", data_root)
    spy_panel = build_spy_panel(spy_df["close"])

    svxy_df = load_ticker("SVXY", data_root)
    vxx_df = load_ticker("VXX", data_root)

    # Build a master index = union of VIX + SPY trading dates.
    master_idx = vix.index.union(spy_panel.index).sort_values()
    frame = pd.DataFrame(index=master_idx)
    frame["vix_close"] = vix.reindex(master_idx)
    frame["vix_high"] = vix_high.reindex(master_idx)
    frame["svxy_open"] = svxy_df["open"].reindex(master_idx)
    frame["svxy_close"] = svxy_df["close"].reindex(master_idx)
    frame["vxx_open"] = vxx_df["open"].reindex(master_idx)
    frame["vxx_close"] = vxx_df["close"].reindex(master_idx)
    for L in (10, 21, 63):
        col = f"realized_vol_{L}"
        if col in spy_panel.columns:
            frame[col] = spy_panel[col].reindex(master_idx)
    frame["spy_log_return"] = spy_panel["log_return"].reindex(master_idx)
    # VIX MA63 and σ63 for mean-reversion trials.
    frame["ma63"] = vix.rolling(63, min_periods=63).mean().reindex(master_idx)
    frame["sigma63"] = vix.rolling(63, min_periods=63).std().reindex(master_idx)
    # ΔlogVIX for residualization.
    frame["delta_vix_log"] = np.log(vix / vix.shift(1)).reindex(master_idx)
    # Drop rows where vix_close is NaN — those carry no signal info anyway.
    frame = frame[frame["vix_close"].notna()]
    return frame


# ---------------------------------------------------------------------------
# Trial enumeration — 10 VRP survivors + 4 mean-reversion = 14 base × 2 variants
# ---------------------------------------------------------------------------

VRP_SURVIVORS: tuple[tuple[int, float, int], ...] = (
    (10, 2.0, 5),  (10, 2.0, 21),
    (10, 4.0, 5),  (10, 4.0, 21),
    (21, 4.0, 5),  (21, 4.0, 21),
    (63, 2.0, 5),  (63, 2.0, 21),
    (63, 4.0, 5),  (63, 4.0, 21),
)

# (spike_k, exit_threshold_k) per §4.3 + PHASE2_STRATEGY_SPEC.md §1.
MR_TRIALS: tuple[tuple[float, float, str], ...] = (
    (1.5, 1.0, "mr_k1.5_to_MA+1sigma"),
    (1.5, 0.0, "mr_k1.5_to_MA"),
    (2.0, 1.0, "mr_k2.0_to_MA+1sigma"),
    (2.0, 0.0, "mr_k2.0_to_MA"),
)


def enumerate_trial_variants() -> list[bt.TrialSpec]:
    """Yield all 28 (trial × variant) specs. VRP trials get holding_period
    plumbed as minimum-hold per Phase 2 §5.6."""
    out: list[bt.TrialSpec] = []
    for L, thr, hold in VRP_SURVIVORS:
        name_base = f"vrp_L{L}_thr{thr:g}_hold{hold}"
        for variant in (strat.HedgeVariant.A, strat.HedgeVariant.B):
            out.append(bt.TrialSpec(
                name=f"{name_base}_{variant.value}",
                variant=variant,
                direction=strat.TradeDirection.SHORT_VOL,
                realized_vol_lookback=L,
                vrp_threshold=thr,
                holding_period=hold,
                signal_class="vrp",
            ))
    for k_spike, k_exit, base in MR_TRIALS:
        for variant in (strat.HedgeVariant.A, strat.HedgeVariant.B):
            out.append(bt.TrialSpec(
                name=f"{base}_{variant.value}",
                variant=variant,
                direction=strat.TradeDirection.LONG_VOL,
                realized_vol_lookback=21,  # not used by mean-reversion
                vrp_threshold=0.0,
                holding_period=0,
                spike_k=k_spike,
                exit_threshold_k=k_exit,
                signal_class="mean_reversion",
            ))
    return out


# ---------------------------------------------------------------------------
# Per-trial gate evaluation
# ---------------------------------------------------------------------------

def _slice_returns(returns: pd.Series, start, end) -> pd.Series:
    return returns[(returns.index >= start) & (returns.index <= end)]


@dataclass
class GateResults:
    trial_name: str
    variant: str
    direction: str
    n_obs_oos_a: int
    n_obs_oos_b: int
    sharpe_oos_a: float
    sharpe_oos_b: float
    # Gate 1
    dsr_oos_a: float
    dsr_oos_b: float
    gate1_passes_a: bool
    gate1_passes_b: bool
    gate1_passes: bool
    # Gate 2
    boot_ci_oos_a: tuple[float, float]
    boot_ci_oos_b: tuple[float, float]
    gate2_passes_a: bool
    gate2_passes_b: bool
    gate2_passes: bool
    # Gate 3
    gate3_passes: bool
    # Gate 4
    sharpe_oos_a_gate4: float
    sharpe_oos_b_gate4: float
    gate4_passes_a: bool
    gate4_passes_b: bool
    gate4_passes: bool
    # Gate 5
    gate5_result: dict
    gate5_passes: bool
    # Gate 6
    gate6_result: dict
    gate6_passes: bool
    # Residualization
    resid_result: dict
    resid_passes: bool
    # Aggregate
    all_six_gates_pass: bool
    deploy_ready: bool   # all six gates + residualization

    def to_dict(self) -> dict:
        return {
            "trial_name": self.trial_name,
            "variant": self.variant,
            "direction": self.direction,
            "n_obs_oos_a": self.n_obs_oos_a,
            "n_obs_oos_b": self.n_obs_oos_b,
            "sharpe_oos_a": self.sharpe_oos_a,
            "sharpe_oos_b": self.sharpe_oos_b,
            "gate1_dsr_oos_a": self.dsr_oos_a,
            "gate1_dsr_oos_b": self.dsr_oos_b,
            "gate1_passes_a": self.gate1_passes_a,
            "gate1_passes_b": self.gate1_passes_b,
            "gate1_passes": self.gate1_passes,
            "gate2_boot_ci_oos_a": list(self.boot_ci_oos_a),
            "gate2_boot_ci_oos_b": list(self.boot_ci_oos_b),
            "gate2_passes_a": self.gate2_passes_a,
            "gate2_passes_b": self.gate2_passes_b,
            "gate2_passes": self.gate2_passes,
            "gate3_passes": self.gate3_passes,
            "gate4_sharpe_oos_a": self.sharpe_oos_a_gate4,
            "gate4_sharpe_oos_b": self.sharpe_oos_b_gate4,
            "gate4_passes_a": self.gate4_passes_a,
            "gate4_passes_b": self.gate4_passes_b,
            "gate4_passes": self.gate4_passes,
            "gate5": self.gate5_result,
            "gate5_passes": self.gate5_passes,
            "gate6": self.gate6_result,
            "gate6_passes": self.gate6_passes,
            "residualization": self.resid_result,
            "residualization_passes": self.resid_passes,
            "all_six_gates_pass": self.all_six_gates_pass,
            "deploy_ready": self.deploy_ready,
        }


def _zero_carry_table() -> costs_mod.CarryTable:
    """Per §17.8 ADDENDUM — gauntlet runs with carry on cash = 0.

    The CarryTable accepts a pd.Series of percent-annualized rates; a single
    row of 0 anchored before any trading date forward-fills to 0 for every
    backtest day. The §14.7 fallback table is bypassed because we supply
    an explicit series.
    """
    z = pd.Series([0.0], index=[pd.Timestamp("1990-01-01")])
    return costs_mod.CarryTable(fred_series=z)


def evaluate_trial(
    trial: bt.TrialSpec,
    market: bt.MarketData,
    factor_panel: pd.DataFrame,
    boot_seed: int,
) -> GateResults:
    """Run baseline + gate4 backtests, evaluate all six gates."""
    # Baseline backtest — full window (IS + OOS-A + OOS-B). Per §17.8 ADDENDUM,
    # carry on free cash is zeroed; only signal PnL net of fill costs counts.
    bk = bt.Backtest(market, trial, costs_mod.baseline_costs(),
                     carry_table=_zero_carry_table())
    res = bk.run()
    rets = res.daily_returns
    nav = res.daily_nav

    # OOS slicing with 21-day embargo.
    embargo_a = pd.Timedelta(days=EMBARGO_DAYS * 7 / 5)  # cal-days conservative
    oos_a_returns = _slice_returns(rets,
                                    OOS_A_START + embargo_a,
                                    OOS_A_END)
    oos_b_returns = _slice_returns(rets,
                                    OOS_B_START + embargo_a,
                                    rets.index.max() if not rets.empty
                                    else OOS_B_START)
    s_a = stats_mod.annualized_sharpe(oos_a_returns)
    s_b = stats_mod.annualized_sharpe(oos_b_returns)

    # Gate 1 — DSR.
    a_arr = oos_a_returns.dropna().to_numpy()
    b_arr = oos_b_returns.dropna().to_numpy()
    skew_a = stats_mod.sample_skewness(a_arr) if a_arr.size > 3 else 0.0
    kurt_a = stats_mod.sample_excess_kurtosis(a_arr) if a_arr.size > 3 else 0.0
    skew_b = stats_mod.sample_skewness(b_arr) if b_arr.size > 3 else 0.0
    kurt_b = stats_mod.sample_excess_kurtosis(b_arr) if b_arr.size > 3 else 0.0
    dsr_a = stats_mod.deflated_sharpe_ratio(
        s_a, N_TRIALS_DSR_DENOMINATOR, n_obs=len(a_arr),
        skewness=skew_a, excess_kurtosis=kurt_a,
    ) if a_arr.size > 10 else 0.0
    dsr_b = stats_mod.deflated_sharpe_ratio(
        s_b, N_TRIALS_DSR_DENOMINATOR, n_obs=len(b_arr),
        skewness=skew_b, excess_kurtosis=kurt_b,
    ) if b_arr.size > 10 else 0.0
    g1_a = dsr_a > DSR_THRESHOLD
    g1_b = dsr_b > DSR_THRESHOLD
    g1 = g1_a and g1_b

    # Gate 2 — bootstrap CI.
    ci_a = stats_mod.stationary_bootstrap_sharpe_ci(
        a_arr, n_replications=2000,
        expected_block_size=21, seed=boot_seed,
    )
    ci_b = stats_mod.stationary_bootstrap_sharpe_ci(
        b_arr, n_replications=2000,
        expected_block_size=21, seed=boot_seed + 1,
    )
    g2_a = np.isfinite(ci_a.lower) and ci_a.lower > 0
    g2_b = np.isfinite(ci_b.lower) and ci_b.lower > 0
    g2 = g2_a and g2_b

    # Gate 3 — sign agreement.
    g3 = stats_mod.sign_agreement(oos_a_returns, oos_b_returns)

    # Gate 4 — cost survival. Also zero-carry per §17.8.
    bk4 = bt.Backtest(market, trial, costs_mod.gate4_stress_costs(),
                      carry_table=_zero_carry_table())
    res4 = bk4.run()
    rets4 = res4.daily_returns
    oos_a_r4 = _slice_returns(rets4, OOS_A_START + embargo_a, OOS_A_END)
    oos_b_r4 = _slice_returns(rets4, OOS_B_START + embargo_a,
                              rets4.index.max() if not rets4.empty else OOS_B_START)
    s_a_g4 = stats_mod.annualized_sharpe(oos_a_r4)
    s_b_g4 = stats_mod.annualized_sharpe(oos_b_r4)
    g4_a = np.isfinite(s_a_g4) and s_a_g4 > 0
    g4_b = np.isfinite(s_b_g4) and s_b_g4 > 0
    g4 = g4_a and g4_b

    # Gate 5 — max-drawdown per stress period.
    g5_res = tr.evaluate_gate5(nav)

    # Gate 6 — CF-Sharpe.
    g6_res = tr.evaluate_gate6(oos_a_returns, oos_b_returns)

    # Residualization (§7).
    # Align factor panel to the strategy returns' index (OOS-A + OOS-B union).
    oos_idx = oos_a_returns.index.union(oos_b_returns.index)
    strat_oos = rets.reindex(oos_idx).dropna()
    panel_oos = factor_panel.reindex(strat_oos.index)
    resid = resid_mod.residualize(strat_oos, panel_oos)

    all_six = g1 and g2 and g3 and g4 and g5_res.passes and g6_res.passes
    deploy = all_six and resid.alpha_passes_gate

    return GateResults(
        trial_name=trial.name, variant=trial.variant.value,
        direction=trial.direction.value,
        n_obs_oos_a=len(a_arr), n_obs_oos_b=len(b_arr),
        sharpe_oos_a=float(s_a), sharpe_oos_b=float(s_b),
        dsr_oos_a=float(dsr_a), dsr_oos_b=float(dsr_b),
        gate1_passes_a=bool(g1_a), gate1_passes_b=bool(g1_b),
        gate1_passes=bool(g1),
        boot_ci_oos_a=(float(ci_a.lower), float(ci_a.upper)),
        boot_ci_oos_b=(float(ci_b.lower), float(ci_b.upper)),
        gate2_passes_a=bool(g2_a), gate2_passes_b=bool(g2_b),
        gate2_passes=bool(g2),
        gate3_passes=bool(g3),
        sharpe_oos_a_gate4=float(s_a_g4), sharpe_oos_b_gate4=float(s_b_g4),
        gate4_passes_a=bool(g4_a), gate4_passes_b=bool(g4_b),
        gate4_passes=bool(g4),
        gate5_result=g5_res.to_dict(),
        gate5_passes=bool(g5_res.passes),
        gate6_result=g6_res.to_dict(),
        gate6_passes=bool(g6_res.passes),
        resid_result=resid.to_dict(),
        resid_passes=bool(resid.alpha_passes_gate),
        all_six_gates_pass=bool(all_six),
        deploy_ready=bool(deploy),
    )


# ---------------------------------------------------------------------------
# Master runner
# ---------------------------------------------------------------------------

@dataclass
class GauntletResults:
    design_doc_sha: str
    phase2_spec_sha: str
    timestamp_utc: str
    market_frame_summary: dict
    per_trial: list[GateResults]

    @property
    def n_deploy_ready(self) -> int:
        return sum(1 for r in self.per_trial if r.deploy_ready)

    @property
    def n_all_six_gates(self) -> int:
        return sum(1 for r in self.per_trial if r.all_six_gates_pass)

    def to_dict(self) -> dict:
        return {
            "design_doc_sha": self.design_doc_sha,
            "phase2_spec_sha": self.phase2_spec_sha,
            "timestamp_utc": self.timestamp_utc,
            "market_frame_summary": self.market_frame_summary,
            "summary": {
                "n_trials_evaluated": len(self.per_trial),
                "n_all_six_gates_pass": self.n_all_six_gates,
                "n_deploy_ready": self.n_deploy_ready,
            },
            "per_trial": [r.to_dict() for r in self.per_trial],
        }


def run_gauntlet(data_root: Path, boot_seed: int = 42) -> GauntletResults:
    design_sha, spec_sha = verify_anchors()
    log.info("Anchors OK. design=%s spec=%s", design_sha[:8], spec_sha[:8])

    frame = load_market_frame(data_root)
    market = bt.MarketData(df=frame)
    log.info("Market frame: %d rows %s → %s",
             len(frame), frame.index.min().date(), frame.index.max().date())

    factor_panel = resid_mod.build_factor_panel(
        spy_returns=frame["spy_log_return"],
        delta_vix=frame["delta_vix_log"],
        # ST-Reversal and Carry are not in the substrate. §7 falloff applies.
        st_reversal=None,
        carry_change=None,
    )

    trials = enumerate_trial_variants()
    log.info("Evaluating %d trial × variant combinations", len(trials))
    results: list[GateResults] = []
    for i, trial in enumerate(trials):
        log.info("[%d/%d] %s", i + 1, len(trials), trial.name)
        try:
            r = evaluate_trial(trial, market, factor_panel,
                               boot_seed=boot_seed + i)
        except Exception as e:
            log.warning("trial %s errored: %s", trial.name, e)
            r = GateResults(
                trial_name=trial.name, variant=trial.variant.value,
                direction=trial.direction.value,
                n_obs_oos_a=0, n_obs_oos_b=0,
                sharpe_oos_a=float("nan"), sharpe_oos_b=float("nan"),
                dsr_oos_a=0.0, dsr_oos_b=0.0,
                gate1_passes_a=False, gate1_passes_b=False, gate1_passes=False,
                boot_ci_oos_a=(float("nan"), float("nan")),
                boot_ci_oos_b=(float("nan"), float("nan")),
                gate2_passes_a=False, gate2_passes_b=False, gate2_passes=False,
                gate3_passes=False,
                sharpe_oos_a_gate4=float("nan"), sharpe_oos_b_gate4=float("nan"),
                gate4_passes_a=False, gate4_passes_b=False, gate4_passes=False,
                gate5_result={"error": str(e)}, gate5_passes=False,
                gate6_result={"error": str(e)}, gate6_passes=False,
                resid_result={"error": str(e)}, resid_passes=False,
                all_six_gates_pass=False, deploy_ready=False,
            )
        results.append(r)

    return GauntletResults(
        design_doc_sha=design_sha,
        phase2_spec_sha=spec_sha,
        timestamp_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        market_frame_summary={
            "n_rows": int(len(frame)),
            "first_date": str(frame.index.min().date()),
            "last_date": str(frame.index.max().date()),
        },
        per_trial=results,
    )


# ---------------------------------------------------------------------------
# Verdict writer
# ---------------------------------------------------------------------------

def write_verdict_md(results: GauntletResults, path: Path) -> None:
    lines: list[str] = []
    lines.append("# VIX — Phase 3 Gauntlet Verdict")
    lines.append("")
    lines.append(f"_Generated {results.timestamp_utc}_  ")
    lines.append(f"_VIX_DESIGN.md SHA-256: `{results.design_doc_sha}`_  ")
    lines.append(f"_PHASE2_STRATEGY_SPEC.md SHA-256: `{results.phase2_spec_sha}`_")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    n_total = len(results.per_trial)
    lines.append(f"- Trial × variant combos evaluated: **{n_total}**")
    lines.append(f"- Combos passing all 6 gates: **{results.n_all_six_gates}**")
    lines.append(f"- Combos passing all 6 gates + §7 residualization (DEPLOY-READY): "
                 f"**{results.n_deploy_ready}**")
    lines.append("")
    if results.n_deploy_ready == 0:
        if results.n_all_six_gates == 0:
            lines.append("**Outcome: CLOSED FAILED at Phase 3.** Per §12 decision "
                         "matrix row 2 — no trial × variant pair clears all six gates.")
        else:
            lines.append(f"**Outcome: CONDITIONAL.** {results.n_all_six_gates} "
                         "combo(s) clear Gates 1-6 but fail §7 four-factor "
                         "residualization. Per §12 decision matrix row 3 — "
                         "documented but not deployable.")
    else:
        lines.append(f"**Outcome: DEPLOY-READY.** {results.n_deploy_ready} "
                     "trial × variant combo(s) cleared all six gates AND the §7 "
                     "residualization. Per §12 decision matrix row 4 — proceed "
                     "to Phase 4 (live paper trading), pending founder approval.")
    lines.append("")
    lines.append(f"Market frame: {results.market_frame_summary['n_rows']} rows "
                 f"{results.market_frame_summary['first_date']} → "
                 f"{results.market_frame_summary['last_date']}")
    lines.append("")
    lines.append("## Per-trial × variant gate breakdown")
    lines.append("")
    lines.append("Legend: G1 = DSR > 0.95 (both OOS), G2 = bootstrap CI > 0 (both OOS), "
                 "G3 = sign agreement, G4 = cost-double survival, G5 = max-DD per stress "
                 "period, G6 = CF-Sharpe > 0.5, R = §7 residualization alpha t > 1.96.")
    lines.append("")
    lines.append("| Trial × variant | OOS-A Sharpe | OOS-B Sharpe | DSR-A | DSR-B | G1 | G2 | G3 | G4 | G5 | G6 | R | DEPLOY |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in results.per_trial:
        def yn(b: bool) -> str: return "✓" if b else "·"
        lines.append(
            f"| `{r.trial_name}` | {r.sharpe_oos_a:+.2f} | {r.sharpe_oos_b:+.2f} | "
            f"{r.dsr_oos_a:.3f} | {r.dsr_oos_b:.3f} | "
            f"{yn(r.gate1_passes)} | {yn(r.gate2_passes)} | {yn(r.gate3_passes)} | "
            f"{yn(r.gate4_passes)} | {yn(r.gate5_passes)} | {yn(r.gate6_passes)} | "
            f"{yn(r.resid_passes)} | {yn(r.deploy_ready)} |"
        )
    lines.append("")
    # §7 falloff note
    lines.append("## §7 residualization note")
    lines.append("")
    lines.append("Per §7 falloff — ST-Reversal (Kenneth French daily) and Carry "
                 "(FRED 3M change) factors are NOT included in this substrate's "
                 "residualization (data not staged). The OLS is run on SPY + ΔVIX "
                 "only (2/4 factors), and per-trial `provisional=True` is set "
                 "in the machine output. The verdict is provisional pending the "
                 "full 4-factor set; a passing alpha t-stat is necessary but "
                 "not sufficient. The §14.6 / §14.10 limitations also apply.")
    lines.append("")
    lines.append("## §15 hard-rule reminder")
    lines.append("")
    lines.append("This verdict is reported on the *pre-committed* trial set frozen "
                 f"in `VIX_DESIGN.md` (SHA `{results.design_doc_sha}`) and per the "
                 f"`PHASE2_STRATEGY_SPEC.md` (SHA `{results.phase2_spec_sha}`). The "
                 "master runner refuses to execute if either SHA mismatches its "
                 "anchor. The DSR denominator is fixed at 28 regardless of how "
                 "many trial × variant combos errored out. Errors count as fails.")
    path.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _json_default(o):
    if isinstance(o, (np.integer, np.bool_)):
        return o.item()
    if isinstance(o, np.floating):
        v = float(o)
        if np.isnan(v):
            return None
        return v
    if isinstance(o, (pd.Timestamp, datetime)):
        return str(o)
    if isinstance(o, tuple):
        return list(o)
    raise TypeError(f"unserializable {type(o)!r}: {o!r}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run the Phase 3 VIX gauntlet.")
    p.add_argument("--data-root", type=Path, default=ROOT / "data")
    p.add_argument("--results-json", type=Path, default=RESULTS_JSON)
    p.add_argument("--verdict-md", type=Path, default=VERDICT_MD)
    p.add_argument("--boot-seed", type=int, default=42)
    p.add_argument("-v", "--verbose", action="count", default=1)
    args = p.parse_args(argv)

    logging.basicConfig(
        level=max(logging.WARNING - 10 * args.verbose, logging.DEBUG),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        results = run_gauntlet(args.data_root, boot_seed=args.boot_seed)
    except AnchorError as e:
        log.error("Anchor refusal: %s", e)
        return 2

    args.results_json.write_text(
        json.dumps(results.to_dict(), indent=2, default=_json_default) + "\n"
    )
    write_verdict_md(results, args.verdict_md)
    print(f"Gauntlet complete:")
    print(f"  Combos evaluated:    {len(results.per_trial)}")
    print(f"  6-gate pass:         {results.n_all_six_gates}")
    print(f"  Deploy-ready:        {results.n_deploy_ready}")
    print(f"  Results: {args.results_json}")
    print(f"  Verdict: {args.verdict_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
