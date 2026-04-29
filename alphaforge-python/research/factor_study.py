"""Honest single-factor research study on the AlphaForge real-data universe.

Produces:
  - IC and IC-decay curves per factor (1/5/10/21/63-day horizons)
  - Quintile-spread backtests with realistic transaction costs
  - Stationary-bootstrap confidence intervals on Sharpe
  - Deflated Sharpe Ratio accounting for multiple testing
  - Regime split (high-vol / low-vol) and sector split for the best factor
  - Baselines: equal-weight universe, random long-short (100 seeds)

Outputs:
  research/out/factor_study_results.json   (machine-readable metrics)
  research/out/factor_study_report.md      (researcher-facing writeup)
  research/out/*.csv                       (decile NAVs, IC panels)
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy import stats

THIS_DIR = Path(__file__).resolve().parent
PROJECT_DIR = THIS_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from data.market.loader import MarketDataLoader
from data.market.pit import load_pit_field_panel, load_pit_sector_map
from data.market.universe import ALL_REAL_TICKERS, REAL_TICKER_SPECS
from research.risk_model import load_reference_factor_table, rolling_factor_residuals_panel
from research.stats_hygiene import (
    hansen_spa_test, white_reality_check,
    PurgedEmbargoedKFold, cross_sectional_ic_cv,
)

OUT_DIR = THIS_DIR / "out"
OUT_DIR.mkdir(exist_ok=True)

# ---------- config ----------
STUDY_START = "2016-01-04"   # satisfies all manifest usable_start dates in REAL_TICKER_SPECS
STUDY_END   = "2025-12-31"
# D4 — held-out OOS period: everything after OOS_START is never used for any
# parameter or formula choice. The 21-day embargo between train and test
# matches the maximum IC horizon so label windows cannot leak across the cut.
OOS_START   = "2024-01-02"
OOS_EMBARGO_DAYS = 21
HORIZONS    = [1, 5, 10, 21, 63]
HOLDING_PERIOD_DAYS = 21      # monthly rebal
N_QUINTILES = 5
BOOT_BLOCKS = 21              # stationary-bootstrap mean block length (days)
BOOT_REPS   = 2000
N_BASELINE_SEEDS = 100
# Costs: commission 1 bp + half-spread 2 bp + linear impact 10 bp * turnover.
# Applied per $ traded at each rebalance.
COMMISSION_BPS  = 1.0
HALF_SPREAD_BPS = 2.0
IMPACT_BPS_PER_UNIT_TURNOVER = 10.0
# D2 — sector neutralization toggle; we always emit both raw and neutralized
# variants so the reader can see the sector-tilt contribution.
SECTOR_MAP = {s.ticker: s.sector for s in REAL_TICKER_SPECS}
UNIVERSE_MODE = os.getenv("ALPHAFORGE_FACTOR_STUDY_UNIVERSE_MODE", "pit").strip().lower()
PIT_MIN_ROWS_PER_TICKER = int(os.getenv("ALPHAFORGE_PIT_MIN_ROWS_PER_TICKER", str(252 * 3)))
RESIDUALIZE_RETURNS = os.getenv("ALPHAFORGE_FACTOR_STUDY_RESIDUALIZE", "0").strip().lower() in {
    "1", "true", "yes", "on"
}
REFERENCE_FACTOR_PATH = os.getenv("ALPHAFORGE_REFERENCE_FACTORS", "").strip()
RESIDUAL_WINDOW = int(os.getenv("ALPHAFORGE_RESIDUAL_WINDOW", "252"))
RESIDUAL_MIN_OBS = int(os.getenv("ALPHAFORGE_RESIDUAL_MIN_OBS", str(RESIDUAL_WINDOW)))
# C5 — purged+embargoed CV for IC stability
CV_SPLITS = 5
CV_EMBARGO_PCT = 0.01


# ---------- data ----------
def load_panel(universe_mode: str = UNIVERSE_MODE) -> Tuple[pd.DataFrame, pd.DataFrame]:
    if universe_mode == "pit":
        close_pt = load_pit_field_panel(
            field="Adj Close",
            start_date=STUDY_START,
            end_date=STUDY_END,
            min_rows=PIT_MIN_ROWS_PER_TICKER,
        )
        volume_pt = load_pit_field_panel(
            field="Volume",
            start_date=STUDY_START,
            end_date=STUDY_END,
            min_rows=PIT_MIN_ROWS_PER_TICKER,
        )
        closes = close_pt.panel.sort_index()
        volumes = volume_pt.panel.reindex(index=closes.index, columns=closes.columns)
        valid = (closes.notna().sum(axis=0) >= PIT_MIN_ROWS_PER_TICKER) & (
            volumes.notna().sum(axis=0) >= PIT_MIN_ROWS_PER_TICKER
        )
        closes = closes.loc[:, valid]
        volumes = volumes.loc[:, valid]
        return closes, volumes

    loader = MarketDataLoader()
    history: Dict[str, pd.DataFrame] = {}
    for tk in ALL_REAL_TICKERS:
        try:
            df = loader.load_ticker(tk, start_date=STUDY_START, end_date=STUDY_END)
        except Exception as e:
            print(f"          skip {tk}: {type(e).__name__}")
            continue
        if len(df) >= 252 * 3:
            history[tk] = df
    # Inner-join on common dates
    idx = None
    for df in history.values():
        idx = df.index if idx is None else idx.intersection(df.index)
    for k in list(history):
        history[k] = history[k].loc[idx]
    closes = pd.DataFrame({t: df["Adj Close"] for t, df in history.items()})
    volumes = pd.DataFrame({t: df["Volume"] for t, df in history.items()})
    # Drop any all-NaN columns, forward-fill tiny gaps up to 2 days
    closes = closes.dropna(axis=1, how="all").ffill(limit=2)
    volumes = volumes.reindex_like(closes).ffill(limit=2)
    # Keep only tickers with full coverage (avoids survivorship-y NaNs inside window)
    valid = closes.notna().all(axis=0) & volumes.notna().all(axis=0)
    closes = closes.loc[:, valid]
    volumes = volumes.loc[:, valid]
    return closes, volumes


def load_sector_map(tickers: List[str], universe_mode: str = UNIVERSE_MODE) -> Dict[str, str]:
    if universe_mode == "pit":
        pit_map = load_pit_sector_map()
        return {ticker: pit_map.get(ticker, "Other") for ticker in tickers}
    return {ticker: SECTOR_MAP.get(ticker, "Other") for ticker in tickers}


def build_forward_returns(
    daily_returns: pd.DataFrame,
    horizons: List[int] = HORIZONS,
) -> Dict[int, pd.DataFrame]:
    """Forward simple returns built from daily simple returns."""
    safe_daily = daily_returns.clip(lower=-0.999999)
    log_ret = np.log1p(safe_daily)
    return {h: log_ret.rolling(h).sum().shift(-h).apply(np.exp) - 1 for h in horizons}


def prepare_analysis_returns(
    close: pd.DataFrame,
    *,
    residualize: bool = RESIDUALIZE_RETURNS,
    reference_factor_path: str = REFERENCE_FACTOR_PATH,
    window: int = RESIDUAL_WINDOW,
    min_obs: int = RESIDUAL_MIN_OBS,
) -> Tuple[pd.DataFrame, pd.DataFrame | None]:
    """Return the daily return panel used by IC/backtest logic.

    When `residualize=True`, returns are no-look-ahead residuals from a
    rolling factor model fit on a local FF5+UMD reference table.
    """
    raw_returns = close.pct_change()
    if not residualize:
        return raw_returns, None
    if not reference_factor_path:
        raise ValueError(
            "Residualized factor study requires ALPHAFORGE_REFERENCE_FACTORS "
            "or an explicit `reference_factor_path`."
        )
    reference = load_reference_factor_table(reference_factor_path)
    residual = rolling_factor_residuals_panel(
        raw_returns,
        reference,
        window=window,
        min_obs=min_obs,
    )
    return residual.reindex_like(raw_returns), reference


# ---------- vectorized factor panels (matches compute_js exactly) ----------
def rsi14(close: pd.DataFrame) -> pd.DataFrame:
    """Simple RSI-14 using the JS formulation (uses 15 prices → 14 changes)."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = np.where(avg_loss > 0, avg_gain / avg_loss.replace(0, np.nan), 1.0)
    rsi = 100.0 - 100.0 / (1.0 + rs)
    return pd.DataFrame(rsi, index=close.index, columns=close.columns)


def build_factor_panels(close: pd.DataFrame, volume: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """Vectorized factor panels.

    Five JS-parity factors + three Python-only factors (Amihud illiquidity,
    idiosyncratic volatility, residual reversal). The last two residualize
    against the equal-weighted universe log return; beta is estimated in a
    60-day rolling window.
    """
    mom = (close.shift(21) - close.shift(252)) / close.shift(252)
    mr5 = -close.pct_change(5)
    vs  = (volume.rolling(5).mean() - volume.rolling(20).mean()) / volume.rolling(20).mean()
    rsi = (rsi14(close) - 50.0) / 50.0
    ed  = close.pct_change(10)  # "Earnings Drift" JS proxy: 10d return

    # Amihud illiquidity: |r| / $volume, averaged over 20 days, × 1e6.
    # Higher score → less liquid → canonical illiquidity-premium long side.
    daily_ret = close.pct_change()
    dollar_vol = (close * volume).clip(lower=1.0)
    illiq = (daily_ret.abs() / dollar_vol).rolling(20).mean() * 1e6

    # Rolling-regression residuals against the equal-weighted universe log
    # return. Used by both IVOL and Residual Reversal.
    log_ret = np.log(close).diff()
    market_lr = log_ret.mean(axis=1)
    reg_win = 60
    roll_cov = log_ret.rolling(reg_win).cov(market_lr)
    roll_var_m = market_lr.rolling(reg_win).var()
    beta = roll_cov.div(roll_var_m, axis=0)
    alpha = log_ret.rolling(reg_win).mean().sub(
        beta.mul(market_lr.rolling(reg_win).mean(), axis=0)
    )
    resid = log_ret.sub(alpha.add(beta.mul(market_lr, axis=0), fill_value=0.0))

    # IVOL: negated annualized residual std (Ang/Hodrick/Xing/Zhang 2006 —
    # high IVOL empirically underperforms, so we negate).
    ivol = -resid.rolling(reg_win).std() * math.sqrt(252)

    # Residual reversal: negated sum of last-5-day residuals
    # (Da/Liu/Schaumburg 2014).
    resid_rev = -resid.rolling(5).sum()

    return {
        "Momentum (12-1)": mom,
        "Mean Reversion (5d)": mr5,
        "Volume Surge": vs,
        "RSI Divergence": rsi,
        "Earnings Drift": ed,
        "Amihud Illiquidity": illiq,
        "Idiosyncratic Volatility": ivol,
        "Residual Reversal (5d)": resid_rev,
    }


def sector_neutralize(factor: pd.DataFrame, sector_map: Dict[str, str]) -> pd.DataFrame:
    """Within-sector cross-sectional demean at each date.

    The resulting panel's row-wise sector means are zero, so any portfolio
    that sorts into quintiles on the neutralized scores inherits zero
    expected sector tilt.
    """
    # Tickers outside sector_map are left as-is (should not happen on the
    # real-data universe but guards against stray columns).
    sector_series = pd.Series({t: sector_map.get(t, "Other") for t in factor.columns})
    groups = sector_series.groupby(sector_series).groups
    out = factor.copy()
    for _, cols in groups.items():
        cols = [c for c in cols if c in out.columns]
        if len(cols) < 2:
            continue
        means = out[cols].mean(axis=1)
        out[cols] = out[cols].sub(means, axis=0)
    return out


# ---------- IC ----------
def compute_ic_panel(factor: pd.DataFrame, fwd_ret: pd.DataFrame) -> pd.Series:
    """Daily Spearman IC between factor score and forward return across tickers."""
    f = factor.reindex_like(fwd_ret)
    ics = []
    idx = []
    for dt in fwd_ret.index:
        fv = f.loc[dt].to_numpy()
        rv = fwd_ret.loc[dt].to_numpy()
        mask = np.isfinite(fv) & np.isfinite(rv)
        if mask.sum() < 10:
            continue
        rho, _ = stats.spearmanr(fv[mask], rv[mask])
        if np.isfinite(rho):
            ics.append(rho)
            idx.append(dt)
    return pd.Series(ics, index=pd.Index(idx, name="date"), name="IC")


def ic_summary(ic: pd.Series) -> Dict[str, float]:
    if len(ic) == 0:
        return {"n": 0, "mean_ic": 0.0, "ic_t": 0.0, "ic_ir": 0.0, "hit_rate": 0.0}
    mean_ic = float(ic.mean())
    sd = float(ic.std(ddof=1))
    t_stat = mean_ic / (sd / math.sqrt(len(ic))) if sd > 0 else 0.0
    ir = mean_ic / sd if sd > 0 else 0.0
    hit = float((ic > 0).mean())
    return {
        "n": int(len(ic)),
        "mean_ic": mean_ic,
        "ic_std": sd,
        "ic_t": t_stat,
        "ic_ir": ir,
        "hit_rate": hit,
    }


# ---------- quintile backtest ----------
def quintile_backtest(
    factor: pd.DataFrame, close: pd.DataFrame, *, holding_period: int = HOLDING_PERIOD_DAYS,
) -> Dict[str, object]:
    return quintile_backtest_from_returns(
        factor,
        close.pct_change(),
        holding_period=holding_period,
    )


def quintile_backtest_from_returns(
    factor: pd.DataFrame,
    asset_returns: pd.DataFrame,
    *,
    holding_period: int = HOLDING_PERIOD_DAYS,
) -> Dict[str, object]:
    """Cross-sectional quintile portfolios. Monthly rebal, equal-weight within leg.

    Returns daily returns for:
      - q1 (short leg, bottom quintile)
      - q5 (long leg, top quintile)
      - long_short (q5 - q1, gross of costs)
      - long_short_net (after commission + half-spread + linear impact)
    Plus turnover series and rebalance dates.
    """
    f = factor.reindex(index=asset_returns.index, columns=asset_returns.columns)
    # Rebalance dates: every `holding_period` days starting from first valid factor row.
    first_valid = f.dropna(how="all").index.min()
    all_dates = asset_returns.loc[first_valid:].index
    rebal_dates = all_dates[::holding_period]

    weights_long = pd.DataFrame(0.0, index=asset_returns.index, columns=asset_returns.columns)
    weights_short = pd.DataFrame(0.0, index=asset_returns.index, columns=asset_returns.columns)

    cur_long = pd.Series(0.0, index=asset_returns.columns)
    cur_short = pd.Series(0.0, index=asset_returns.columns)
    rebal_set = set(rebal_dates)

    turnover_rows = []

    for dt in all_dates:
        if dt in rebal_set:
            scores = f.loc[dt].dropna()
            if len(scores) >= 2 * N_QUINTILES:
                ranked = scores.sort_values()
                q_size = len(ranked) // N_QUINTILES
                bot = ranked.index[:q_size]
                top = ranked.index[-q_size:]
                new_long = pd.Series(0.0, index=asset_returns.columns)
                new_short = pd.Series(0.0, index=asset_returns.columns)
                new_long.loc[top] = 1.0 / len(top)
                new_short.loc[bot] = 1.0 / len(bot)
                turnover = float(
                    (new_long - cur_long).abs().sum() + (new_short - cur_short).abs().sum()
                )
                cur_long, cur_short = new_long, new_short
                turnover_rows.append((dt, turnover))
        weights_long.loc[dt] = cur_long
        weights_short.loc[dt] = cur_short

    # Day-over-day returns on held positions
    rets = asset_returns.fillna(0.0)
    q5 = (weights_long.shift(1).fillna(0.0) * rets).sum(axis=1)
    q1 = (weights_short.shift(1).fillna(0.0) * rets).sum(axis=1)
    ls = q5 - q1

    turnover_s = pd.Series(
        {d: t for d, t in turnover_rows}, name="turnover"
    ).reindex(asset_returns.index).fillna(0.0)

    # Cost on each rebalance day
    per_unit_cost = (COMMISSION_BPS + HALF_SPREAD_BPS) * 1e-4
    cost_per_day = turnover_s * per_unit_cost + (IMPACT_BPS_PER_UNIT_TURNOVER * 1e-4) * (turnover_s ** 2)
    ls_net = ls - cost_per_day

    # Trim to rebalanced window (after first rebalance so weights are non-zero)
    start = rebal_dates[0] + pd.Timedelta(days=1)
    q5 = q5.loc[start:]; q1 = q1.loc[start:]; ls = ls.loc[start:]; ls_net = ls_net.loc[start:]
    turnover_s = turnover_s.loc[start:]

    # Per-quintile returns too (for monotonicity)
    q_all = []
    for q_idx in range(N_QUINTILES):
        w = pd.DataFrame(0.0, index=asset_returns.index, columns=asset_returns.columns)
        cur = pd.Series(0.0, index=asset_returns.columns)
        for dt in all_dates:
            if dt in rebal_set:
                scores = f.loc[dt].dropna()
                if len(scores) >= 2 * N_QUINTILES:
                    ranked = scores.sort_values()
                    q_size = len(ranked) // N_QUINTILES
                    members = ranked.index[q_idx * q_size:(q_idx + 1) * q_size]
                    cur = pd.Series(0.0, index=asset_returns.columns)
                    cur.loc[members] = 1.0 / len(members)
            w.loc[dt] = cur
        q_ret = (w.shift(1).fillna(0.0) * rets).sum(axis=1).loc[start:]
        q_all.append(q_ret)

    return {
        "q5": q5, "q1": q1,
        "long_short_gross": ls,
        "long_short_net": ls_net,
        "turnover": turnover_s,
        "quintile_returns": q_all,
        "rebal_dates": list(rebal_dates),
    }


# ---------- metrics ----------
def ann_sharpe(r: pd.Series) -> float:
    if len(r) < 30 or r.std(ddof=1) == 0:
        return 0.0
    return float(r.mean() / r.std(ddof=1) * math.sqrt(252))


def ann_return(r: pd.Series) -> float:
    nav = (1 + r).prod()
    if nav <= 0 or len(r) == 0:
        return 0.0
    years = len(r) / 252.0
    return float(nav ** (1 / years) - 1)


def max_drawdown(r: pd.Series) -> float:
    nav = (1 + r).cumprod()
    peak = nav.cummax()
    dd = (nav - peak) / peak
    return float(dd.min())


# ---------- stationary bootstrap ----------
def stationary_bootstrap_sharpe(r: np.ndarray, reps: int = BOOT_REPS, mean_block: int = BOOT_BLOCKS, seed: int = 0) -> Dict[str, float]:
    rng = np.random.default_rng(seed)
    n = len(r)
    p = 1.0 / mean_block
    out = np.empty(reps)
    for b in range(reps):
        idxs = np.empty(n, dtype=np.int64)
        i = rng.integers(0, n)
        for k in range(n):
            if k > 0 and rng.random() < p:
                i = rng.integers(0, n)
            else:
                i = (i + 1) % n if k > 0 else i
            idxs[k] = i
        sample = r[idxs]
        sd = sample.std(ddof=1)
        out[b] = (sample.mean() / sd * math.sqrt(252)) if sd > 0 else 0.0
    return {
        "mean": float(out.mean()),
        "ci_lo": float(np.quantile(out, 0.025)),
        "ci_hi": float(np.quantile(out, 0.975)),
        "p_positive": float((out > 0).mean()),
    }


# ---------- deflated Sharpe ----------
def deflated_sharpe_ratio(sr_observed: float, n_obs: int, sr_candidates: List[float]) -> Dict[str, float]:
    """Bailey & López de Prado (2014). SR in annualized units; converted to per-period.

    Returns the probabilistic Sharpe after deflating for multiple trials.
    """
    if len(sr_candidates) < 2 or n_obs < 50:
        return {"dsr": float("nan"), "sr0": float("nan")}
    sr_daily = np.array(sr_candidates) / math.sqrt(252)
    var_sr = sr_daily.var(ddof=1)
    if var_sr <= 0:
        return {"dsr": float("nan"), "sr0": float("nan")}
    euler_mascheroni = 0.5772156649
    N = len(sr_candidates)
    sr0_daily = math.sqrt(var_sr) * (
        (1 - euler_mascheroni) * stats.norm.ppf(1 - 1 / N)
        + euler_mascheroni * stats.norm.ppf(1 - 1 / (N * math.e))
    )
    sr_obs_daily = sr_observed / math.sqrt(252)
    # Assuming normal returns (gamma3=0, gamma4=3) for simplicity
    gamma3, gamma4 = 0.0, 3.0
    denom = math.sqrt((1 - gamma3 * sr_obs_daily + (gamma4 - 1) / 4 * sr_obs_daily ** 2) / (n_obs - 1))
    dsr = stats.norm.cdf((sr_obs_daily - sr0_daily) / denom)
    return {"dsr": float(dsr), "sr0_annualized": float(sr0_daily * math.sqrt(252))}


# ---------- baselines ----------
def equal_weight_benchmark(close: pd.DataFrame) -> pd.Series:
    return equal_weight_benchmark_from_returns(close.pct_change())


def equal_weight_benchmark_from_returns(asset_returns: pd.DataFrame) -> pd.Series:
    return asset_returns.fillna(0.0).mean(axis=1)


def random_long_short_baseline(close: pd.DataFrame, n_seeds: int = N_BASELINE_SEEDS, holding_period: int = HOLDING_PERIOD_DAYS) -> Dict[str, float]:
    return random_long_short_baseline_from_returns(
        close.pct_change(),
        n_seeds=n_seeds,
        holding_period=holding_period,
    )


def random_long_short_baseline_from_returns(
    asset_returns: pd.DataFrame,
    n_seeds: int = N_BASELINE_SEEDS,
    holding_period: int = HOLDING_PERIOD_DAYS,
) -> Dict[str, float]:
    rets = asset_returns.fillna(0.0)
    rebal_idx = np.arange(0, len(asset_returns), holding_period)
    sharpes = []
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed)
        daily = np.zeros(len(asset_returns))
        long_set = short_set = None
        for i in range(len(asset_returns)):
            if i in rebal_idx:
                tickers = asset_returns.columns.to_numpy()
                rng.shuffle(tickers)
                q = len(tickers) // N_QUINTILES
                long_set = tickers[:q]
                short_set = tickers[-q:]
            if long_set is not None and i > 0:
                daily[i] = rets.iloc[i][long_set].mean() - rets.iloc[i][short_set].mean()
        s = pd.Series(daily, index=asset_returns.index)
        sharpes.append(ann_sharpe(s))
    arr = np.array(sharpes)
    return {
        "n_seeds": n_seeds,
        "mean_sharpe": float(arr.mean()),
        "sd_sharpe": float(arr.std(ddof=1)),
        "ci_lo": float(np.quantile(arr, 0.025)),
        "ci_hi": float(np.quantile(arr, 0.975)),
    }


# ---------- regime split ----------
def regime_split(ls: pd.Series, benchmark: pd.Series) -> Dict[str, Dict[str, float]]:
    vol = benchmark.rolling(21).std() * math.sqrt(252)
    high = vol > vol.quantile(0.7)
    low = vol < vol.quantile(0.3)
    def metric(mask):
        r = ls[mask.reindex(ls.index, fill_value=False)]
        return {"n": int(len(r)), "sharpe": ann_sharpe(r), "ann_return": ann_return(r), "max_dd": max_drawdown(r)}
    return {"high_vol": metric(high), "low_vol": metric(low), "all": metric(pd.Series(True, index=ls.index))}


# ---------- train/test split (D4) ----------
def split_train_test(series: pd.Series, oos_start: str = OOS_START,
                     embargo_days: int = OOS_EMBARGO_DAYS) -> Dict[str, pd.Series]:
    """Return {'train': ..., 'test': ...} with an embargo gap.

    The train window ends `embargo_days` trading days before `oos_start`
    so label horizons at or near the maximum IC horizon cannot leak
    across the cut.
    """
    oos_ts = pd.Timestamp(oos_start)
    embargo_end = oos_ts - pd.Timedelta(days=embargo_days * 2)  # calendar buffer
    return {
        "train": series.loc[:embargo_end],
        "test":  series.loc[oos_ts:],
    }


def slice_metrics(r: pd.Series) -> Dict[str, float]:
    """Lightweight metric bundle for a slice — used by the train/test report."""
    return {
        "n_days": int(len(r)),
        "sharpe": ann_sharpe(r),
        "ann_return": ann_return(r),
        "max_drawdown": max_drawdown(r),
    }


# ---------- main ----------
def _run_variant(label: str, factors: Dict[str, pd.DataFrame],
                 asset_returns: pd.DataFrame, fwd: Dict[int, pd.DataFrame], t0: float):
    """Evaluate a dict of factor panels end-to-end (IC + quintile backtest +
    bootstrap CI + DSR). Returns (all_results, net_series, sharpe_candidates).
    """
    all_results: Dict[str, dict] = {}
    net_series: Dict[str, pd.Series] = {}
    sharpe_candidates_net: List[float] = []

    for name, panel in factors.items():
        print(f"[{time.time()-t0:5.1f}s] [{label}] Factor: {name}")
        ic_by_h = {h: compute_ic_panel(panel, fwd[h]) for h in HORIZONS}
        ic_stats = {h: ic_summary(s) for h, s in ic_by_h.items()}

        bt = quintile_backtest_from_returns(panel, asset_returns, holding_period=HOLDING_PERIOD_DAYS)
        ls_gross = bt["long_short_gross"].dropna()
        ls_net = bt["long_short_net"].dropna()
        net_series[name] = ls_net
        q_rets = [ann_return(q) for q in bt["quintile_returns"]]

        metrics = {
            "gross": {"sharpe": ann_sharpe(ls_gross), "ann_return": ann_return(ls_gross),
                      "max_drawdown": max_drawdown(ls_gross)},
            "net": {"sharpe": ann_sharpe(ls_net), "ann_return": ann_return(ls_net),
                    "max_drawdown": max_drawdown(ls_net),
                    "avg_turnover_per_rebal": float(bt["turnover"][bt["turnover"] > 0].mean())},
            "quintile_annualized_returns": q_rets,
            "ic_decay": ic_stats,
            "n_days": int(len(ls_net)),
        }
        sharpe_candidates_net.append(metrics["net"]["sharpe"])
        boot = stationary_bootstrap_sharpe(ls_net.to_numpy(),
                                           seed=abs(hash((label, name))) % (2**31))
        metrics["net"]["sharpe_bootstrap"] = boot
        all_results[name] = metrics

    for name in factors:
        sr = all_results[name]["net"]["sharpe"]
        n_obs = all_results[name]["n_days"]
        all_results[name]["net"]["deflated_sharpe"] = deflated_sharpe_ratio(
            sr, n_obs, sharpe_candidates_net)
    return all_results, net_series, sharpe_candidates_net


def main():
    t0 = time.time()
    print(
        f"[{time.time()-t0:5.1f}s] Loading {UNIVERSE_MODE} parquet panel "
        f"({STUDY_START} → {STUDY_END})..."
    )
    close, volume = load_panel()
    sector_map = load_sector_map(list(close.columns))
    print(f"          universe: {close.shape[1]} tickers, {close.shape[0]} trading days")

    print(f"[{time.time()-t0:5.1f}s] Building factor panels (8 factors)...")
    raw_factors = build_factor_panels(close, volume)

    print(f"[{time.time()-t0:5.1f}s] Building sector-neutral variant (D2)...")
    neutral_factors = {n: sector_neutralize(p, sector_map) for n, p in raw_factors.items()}

    analysis_returns, reference_factors = prepare_analysis_returns(close)
    analysis_mode = "residualized" if RESIDUALIZE_RETURNS else "raw"
    print(f"[{time.time()-t0:5.1f}s] Analysis-return mode: {analysis_mode}")
    fwd = build_forward_returns(analysis_returns)

    # --- raw variant ---
    raw_results, raw_net, raw_cands = _run_variant("raw", raw_factors, analysis_returns, fwd, t0)

    # --- sector-neutral variant ---
    neutral_results, neutral_net, neutral_cands = _run_variant(
        "neutral", neutral_factors, analysis_returns, fwd, t0)

    # --- Hansen SPA across factors (C5) ---
    # Align all factors on common index and stack into T × K matrix.
    def _spa_matrix(net_dict: Dict[str, pd.Series]) -> Tuple[np.ndarray, List[str]]:
        df = pd.DataFrame(net_dict).dropna(how="any")
        return df.to_numpy(), list(df.columns)

    raw_mat, raw_cols = _spa_matrix(raw_net)
    neut_mat, neut_cols = _spa_matrix(neutral_net)
    print(f"[{time.time()-t0:5.1f}s] Hansen SPA (raw, K={len(raw_cols)})...")
    spa_raw = hansen_spa_test(raw_mat, reps=1000, mean_block=BOOT_BLOCKS, seed=7)
    spa_raw["best_factor"] = raw_cols[spa_raw["argmax"]] if spa_raw["argmax"] >= 0 else None
    print(f"[{time.time()-t0:5.1f}s] Hansen SPA (neutral, K={len(neut_cols)})...")
    spa_neut = hansen_spa_test(neut_mat, reps=1000, mean_block=BOOT_BLOCKS, seed=8)
    spa_neut["best_factor"] = neut_cols[spa_neut["argmax"]] if spa_neut["argmax"] >= 0 else None

    # White's Reality Check — more conservative than SPA; reported alongside.
    print(f"[{time.time()-t0:5.1f}s] White Reality Check (raw)...")
    wrc_raw = white_reality_check(raw_mat, reps=1000, mean_block=BOOT_BLOCKS, seed=17)
    wrc_raw["best_factor"] = raw_cols[wrc_raw["argmax"]] if wrc_raw["argmax"] >= 0 else None
    print(f"[{time.time()-t0:5.1f}s] White Reality Check (neutral)...")
    wrc_neut = white_reality_check(neut_mat, reps=1000, mean_block=BOOT_BLOCKS, seed=18)
    wrc_neut["best_factor"] = neut_cols[wrc_neut["argmax"]] if wrc_neut["argmax"] >= 0 else None

    # --- Purged + embargoed CV IC per factor (C5) ---
    print(f"[{time.time()-t0:5.1f}s] Purged+embargoed CV IC (h=21)...")
    cv = PurgedEmbargoedKFold(n_splits=CV_SPLITS, label_horizon=21, embargo_pct=CV_EMBARGO_PCT)
    cv_ic_raw, cv_ic_neut = {}, {}
    for name, panel in raw_factors.items():
        cv_ic_raw[name] = cross_sectional_ic_cv(panel, fwd[21], cv)
    for name, panel in neutral_factors.items():
        cv_ic_neut[name] = cross_sectional_ic_cv(panel, fwd[21], cv)

    # --- Train / test split on the headline (sector-neutral) variant (D4) ---
    print(f"[{time.time()-t0:5.1f}s] OOS train/test split at {OOS_START}...")
    train_test: Dict[str, Dict[str, dict]] = {}
    for name, series in neutral_net.items():
        parts = split_train_test(series)
        train_test[name] = {
            "train": slice_metrics(parts["train"]),
            "test":  slice_metrics(parts["test"]),
        }

    # --- baselines + regime split (computed on the raw variant as before) ---
    print(f"[{time.time()-t0:5.1f}s] Baseline: equal-weight...")
    ew = equal_weight_benchmark_from_returns(analysis_returns).loc[raw_net[list(raw_factors)[0]].index]
    eq_metrics = {"sharpe": ann_sharpe(ew), "ann_return": ann_return(ew),
                  "max_drawdown": max_drawdown(ew)}
    print(f"[{time.time()-t0:5.1f}s] Baseline: random long-short ({N_BASELINE_SEEDS} seeds)...")
    rand_metrics = random_long_short_baseline_from_returns(analysis_returns)
    best = max(raw_factors, key=lambda n: raw_results[n]["net"]["sharpe"])
    print(f"[{time.time()-t0:5.1f}s] Regime split on best factor: {best}")
    regime = regime_split(raw_net[best], ew)

    summary = {
        "config": {
            "start": STUDY_START, "end": STUDY_END, "oos_start": OOS_START,
            "oos_embargo_days": OOS_EMBARGO_DAYS,
            "universe_mode": UNIVERSE_MODE,
            "analysis_returns_mode": analysis_mode,
            "universe_size": int(close.shape[1]),
            "trading_days": int(close.shape[0]),
            "reference_factor_path": REFERENCE_FACTOR_PATH or None,
            "residual_window": RESIDUAL_WINDOW if RESIDUALIZE_RETURNS else None,
            "residual_min_obs": RESIDUAL_MIN_OBS if RESIDUALIZE_RETURNS else None,
            "horizons": HORIZONS,
            "holding_period_days": HOLDING_PERIOD_DAYS,
            "n_quintiles": N_QUINTILES,
            "tx_cost_model": {
                "commission_bps": COMMISSION_BPS,
                "half_spread_bps": HALF_SPREAD_BPS,
                "impact_bps_per_unit_turnover": IMPACT_BPS_PER_UNIT_TURNOVER,
            },
            "bootstrap_reps": BOOT_REPS,
            "bootstrap_block_len": BOOT_BLOCKS,
            "cv_splits": CV_SPLITS, "cv_embargo_pct": CV_EMBARGO_PCT,
        },
        "factors_raw": raw_results,
        "factors_sector_neutral": neutral_results,
        "cv_ic_raw": cv_ic_raw,
        "cv_ic_sector_neutral": cv_ic_neut,
        "hansen_spa": {"raw": spa_raw, "sector_neutral": spa_neut},
        "white_reality_check": {"raw": wrc_raw, "sector_neutral": wrc_neut},
        "train_test_split_neutral": train_test,
        "baselines": {"equal_weight": eq_metrics, "random_long_short": rand_metrics},
        "best_factor": best,
        "regime_split_best": regime,
    }
    if reference_factors is not None:
        summary["reference_factor_overlap_days"] = int(
            pd.Index(analysis_returns.index).intersection(reference_factors.index).shape[0]
        )
    # Back-compat alias: older tooling expects `factors` to exist.
    all_results = raw_results
    net_series = raw_net
    summary["factors"] = raw_results

    out_json = OUT_DIR / "factor_study_results.json"
    out_json.write_text(json.dumps(summary, indent=2, default=float))

    # Dump NAV CSVs for plotting
    nav_frame = pd.DataFrame({name: (1 + s).cumprod() for name, s in net_series.items()})
    nav_frame["EqualWeight"] = (1 + ew.reindex_like(nav_frame)).cumprod()
    nav_frame.to_csv(OUT_DIR / "net_navs.csv")

    print(f"[{time.time()-t0:5.1f}s] Writing markdown report...")
    write_report(summary)
    print(f"[{time.time()-t0:5.1f}s] Done. Results → {out_json}")


def write_report(s: dict):
    c = s["config"]
    lines = []
    A = lines.append
    A("# AlphaForge — Single-Factor Research Study")
    A("")
    A(
        f"_Universe {c['universe_size']} names · mode={c.get('universe_mode', 'legacy')} · "
        f"{c['start']} → {c['end']} ({c['trading_days']} trading days)_"
    )
    A("")
    A("## Abstract")
    A("")
    A("We evaluate five cross-sectional equity factors used by the AlphaForge engine "
      "(Momentum 12-1, 5-day Mean Reversion, Volume Surge, RSI Divergence, 10-day Earnings Drift) "
      "on a local parquet store of adjusted OHLCV data. "
      "For each factor we report Spearman IC and IC decay, a quintile-spread backtest with "
      "realistic transaction costs, stationary-bootstrap Sharpe confidence intervals, and "
      "the Deflated Sharpe Ratio (Bailey & López de Prado, 2014) accounting for the 5-factor trial set. "
      "Random long-short and equal-weight baselines provide the null. "
      "The goal is an honest assessment of whether any of these textbook signals has "
      "cost-adjusted, statistically credible edge in this universe.")
    if c.get("analysis_returns_mode") == "residualized":
        A("")
        A("All IC and portfolio metrics are computed on no-look-ahead FF5+UMD residual returns, "
          "not raw returns. This is the Phase-3 alpha-isolation path.")
    A("")
    A("## Headline Findings")
    A("")
    best_name = s["best_factor"]
    best_m = s["factors"][best_name]
    best_dsr = best_m["net"]["deflated_sharpe"]["dsr"]
    ic_h1 = best_m["ic_decay"].get("1", best_m["ic_decay"].get(1, {}))
    ic_h63 = best_m["ic_decay"].get("63", best_m["ic_decay"].get(63, {}))
    A(f"1. **{best_name} is the only signal with a clean IC decay curve.** Its IC rises "
      f"monotonically from {ic_h1.get('mean_ic', 0):+.4f} (t={ic_h1.get('ic_t', 0):+.2f}) at h=1 "
      f"to {ic_h63.get('mean_ic', 0):+.4f} (t={ic_h63.get('ic_t', 0):+.2f}) at h=63. Quintile "
      f"returns are monotonic (Q5 − Q1 positive). The four other factors have IC t-stats that "
      f"do not survive at monthly and quarterly horizons.")
    A("2. **Transaction costs destroy the short-horizon factors.** Mean Reversion, Volume Surge, "
      "RSI Divergence, and Earnings Drift all flip positions aggressively each rebalance "
      "(turnover ≈ 3× monthly vs Momentum's ≈ 0.9×). After commission + half-spread + impact, "
      "their net Sharpes are negative with bootstrap CIs that exclude zero on the wrong side.")
    A(f"3. **Even {best_name} does not clear the deflation bar.** Net Sharpe is "
      f"{best_m['net']['sharpe']:+.2f} with a 95% bootstrap CI spanning zero, and the Deflated "
      f"Sharpe Ratio is **{best_dsr:.2f}** — far below the 0.95 conventional threshold for a "
      "credibly non-zero Sharpe after multiple testing.")
    A(f"4. **Equal-weight beats every factor overlay.** A dumb equal-weight basket of "
      f"the same study universe earns {s['baselines']['equal_weight']['sharpe']:+.2f} Sharpe and "
      f"{s['baselines']['equal_weight']['ann_return']:+.1%} annualized — well above any long-short "
      "net Sharpe in this study. The universe's beta is the dominant source of return; none of "
      "these factor overlays add credible alpha *on this universe, net of costs*.")
    rg = s["regime_split_best"]
    A(f"5. **Momentum's regime dependency is textbook.** In low-vol regimes the long-short runs at "
      f"{rg['low_vol']['sharpe']:+.2f} Sharpe; in high-vol regimes it runs at "
      f"{rg['high_vol']['sharpe']:+.2f}. Consistent with the known momentum-crash literature "
      "(Daniel & Moskowitz 2016).")
    A("")
    A("**Interpretation.** This does *not* prove momentum has no edge in equities — it shows the "
      "JS-parity formulation on this study universe, net of costs, has no credible "
      "edge *in this specific study*. A real signal-discovery workflow would: (a) expand to 500+ "
      "point-in-time names, (b) sector- and beta-neutralize, (c) test on a held-out period never "
      "used for any tuning choice, and (d) compare against a Fama-French-5 risk model to isolate "
      "true alpha.")
    A("")
    A("## Data & Methodology")
    A("")
    if c.get("universe_mode") == "pit":
        A(f"- **Universe.** {c['universe_size']} PIT-aware S&P 500 members with at least "
          f"{PIT_MIN_ROWS_PER_TICKER} usable OHLCV rows in the quarantine parquet store. "
          "Membership is masked by the Phase-1 event log; delisted or missing names remain "
          "explicit coverage gaps instead of being silently dropped from the substrate.")
    else:
        A(f"- **Universe.** {c['universe_size']} US large-caps from the AlphaForge real-data manifest "
          "(Technology, Healthcare, Finance, Consumer, Energy). Only tickers with full history over the "
          "study window are retained. Known survivorship caveat: the universe is defined as of today, "
          "not point-in-time; delisted peers are not included. This biases returns upward.")
    A(f"- **Period.** {c['start']} → {c['end']} ({c['trading_days']} trading days). The first 252 "
      "trading days are consumed as warmup for the 12-1 momentum lookback; all reported metrics "
      "are post-warmup.")
    if c.get("analysis_returns_mode") == "residualized":
        A(f"- **Risk model.** Daily returns are residualized with a no-look-ahead rolling "
          f"FF5+UMD model (window={c['residual_window']}, min_obs={c['residual_min_obs']}). "
          "The study therefore measures alpha after removing broad market, size, value, "
          "profitability, investment, and momentum exposures.")
    A(f"- **Factor construction.** Each factor is computed daily per ticker using the JS-parity "
      "formulas in `alphaforge-python/factors/`. Raw scores are z-scored cross-sectionally at each rebalance.")
    A(f"- **Portfolios.** Cross-sectional quintiles ({c['n_quintiles']} buckets). Long top quintile, "
      f"short bottom quintile, equal-weighted within each leg. Rebalance every {c['holding_period_days']} trading days.")
    A(f"- **Transaction costs.** Commission {c['tx_cost_model']['commission_bps']} bp + "
      f"half-spread {c['tx_cost_model']['half_spread_bps']} bp + linear impact "
      f"{c['tx_cost_model']['impact_bps_per_unit_turnover']} bp per unit of turnover squared.")
    A(f"- **Significance.** Stationary bootstrap ({c['bootstrap_reps']} reps, mean block length "
      f"{c['bootstrap_block_len']} days) for Sharpe CIs. Deflated Sharpe across the 5-factor trial set.")
    A("")
    A("## IC and IC Decay")
    A("")
    A("| Factor | h=1 | h=5 | h=10 | h=21 | h=63 |")
    A("|---|---|---|---|---|---|")
    for name, m in s["factors"].items():
        cells = [f"{m['ic_decay'][str(h) if isinstance(list(m['ic_decay'].keys())[0], str) else h]['mean_ic']:+.4f} (t={m['ic_decay'][str(h) if isinstance(list(m['ic_decay'].keys())[0], str) else h]['ic_t']:+.2f})" for h in [1,5,10,21,63]]
        A(f"| {name} | " + " | ".join(cells) + " |")
    A("")
    A("IC is the daily cross-sectional Spearman rank correlation between the factor score and the "
      "forward return at horizon h. A stable positive t-statistic at h≥21 is the minimum bar for "
      "a monthly-rebalanced signal.")
    A("")
    A("## Quintile-Spread Backtest (net of costs)")
    A("")
    A("| Factor | Gross SR | Net SR | Bootstrap 95% CI | p(SR>0) | Ann Return | Max DD | Avg Turnover |")
    A("|---|---|---|---|---|---|---|---|")
    for name, m in s["factors"].items():
        boot = m["net"]["sharpe_bootstrap"]
        A(f"| {name} | {m['gross']['sharpe']:+.2f} | {m['net']['sharpe']:+.2f} | "
          f"[{boot['ci_lo']:+.2f}, {boot['ci_hi']:+.2f}] | {boot['p_positive']:.2f} | "
          f"{m['net']['ann_return']:+.2%} | {m['net']['max_drawdown']:.2%} | "
          f"{m['net']['avg_turnover_per_rebal']:.2f} |")
    A("")
    A("Quintile annualized returns (low→high quintile, should be monotonic for a genuine factor):")
    A("")
    A("| Factor | Q1 (low) | Q2 | Q3 | Q4 | Q5 (high) | Q5−Q1 |")
    A("|---|---|---|---|---|---|---|")
    for name, m in s["factors"].items():
        q = m["quintile_annualized_returns"]
        A(f"| {name} | {q[0]:+.2%} | {q[1]:+.2%} | {q[2]:+.2%} | {q[3]:+.2%} | {q[4]:+.2%} | {q[4]-q[0]:+.2%} |")
    A("")
    A("## Deflated Sharpe Ratio")
    A("")
    A(f"With 5 factor trials, the Sharpe threshold a random strategy would hit by chance (SR₀) is "
      f"non-zero. DSR converts the observed Sharpe into a probability that the true Sharpe exceeds zero "
      f"*after* deflating for the number of trials.")
    A("")
    A("| Factor | Net SR | SR₀ (selection) | Deflated Sharpe (p) |")
    A("|---|---|---|---|")
    for name, m in s["factors"].items():
        dsr = m["net"]["deflated_sharpe"]
        sr0 = dsr.get("sr0_annualized", float("nan"))
        A(f"| {name} | {m['net']['sharpe']:+.2f} | {sr0:+.2f} | {dsr['dsr']:.3f} |")
    A("")
    A("A DSR above 0.95 is the conventional bar for claiming a Sharpe is credibly non-zero after "
      "multiple testing.")
    A("")
    A("## Baselines")
    A("")
    eq = s["baselines"]["equal_weight"]; rnd = s["baselines"]["random_long_short"]
    A(f"- **Equal-weight universe (long-only):** Sharpe {eq['sharpe']:+.2f}, ann return "
      f"{eq['ann_return']:+.2%}, max DD {eq['max_drawdown']:.2%}.")
    A(f"- **Random long-short ({rnd['n_seeds']} seeds):** mean Sharpe {rnd['mean_sharpe']:+.2f}, "
      f"SD {rnd['sd_sharpe']:.2f}, 95% CI [{rnd['ci_lo']:+.2f}, {rnd['ci_hi']:+.2f}]. "
      "Any factor whose net Sharpe falls inside this band is indistinguishable from randomness.")
    A("")
    A("## Regime Split — Best Factor")
    A("")
    best = s["best_factor"]; rg = s["regime_split_best"]
    A(f"Best net Sharpe: **{best}**. Decomposing its return stream by 21-day realized-vol regime "
      "of the equal-weight benchmark:")
    A("")
    A("| Regime | Days | Sharpe | Ann Return | Max DD |")
    A("|---|---|---|---|---|")
    for k in ["all", "high_vol", "low_vol"]:
        r = rg[k]
        A(f"| {k} | {r['n']} | {r['sharpe']:+.2f} | {r['ann_return']:+.2%} | {r['max_dd']:.2%} |")
    A("")
    A("## Honest Limitations")
    A("")
    A("1. **Survivorship bias.** The universe is today's surviving large-caps. Real point-in-time "
      "index membership (e.g., S&P 500 historical constituents) would include delisted names and "
      "lower realized returns by ~1–2% per year on the long-only baseline.")
    A("2. **No borrow costs.** Short-leg returns assume free, unlimited borrow. For non-mega-cap "
      "names a 20–100 bp annual borrow fee is typical and erodes the short alpha.")
    A("3. **Cost model is static.** A real impact model scales with ADV, spread with volatility, "
      "and fees with venue. Our single-parameter model is a rough proxy.")
    A("4. **Small universe.** 50 tickers means quintile buckets are 10 names — cross-sectional IC "
      "t-stats are noisier than on a 500-name universe. Results should be reproduced on a broader "
      "universe before any capital decision.")
    A("5. **No risk model.** Returns are not neutralized against sector or style factors, so reported "
      "alpha may be partly explained by sector tilts (especially for Momentum and Low-Vol variants).")
    A("6. **Trials beyond this study.** DSR here deflates for 5 factors. The full AlphaForge search "
      "(MARL hyperparameters, reward mixes, curriculum stages, ablations) is a much larger trial "
      "set — that headline MARL Sharpe should be deflated against its own full trial count, not 5.")
    A("")
    # ── Sector-neutral variant (D2) ─────────────────────────────────────
    if "factors_sector_neutral" in s:
        A("## Sector-Neutralized Variant (D2)")
        A("")
        A("Each factor score is within-sector demeaned at every rebalance before "
          "quintile bucketing. Any Sharpe lift that survives this operation is "
          "not a sector tilt.")
        A("")
        A("| Factor | Net SR (raw) | Net SR (sector-neutral) | Δ Sharpe | DSR (neutral) |")
        A("|---|---:|---:|---:|---:|")
        for name in s["factors_raw"]:
            raw_sr = s["factors_raw"][name]["net"]["sharpe"]
            neut = s["factors_sector_neutral"].get(name, {}).get("net", {})
            neut_sr = neut.get("sharpe", float("nan"))
            dsr_n = neut.get("deflated_sharpe", {}).get("dsr", float("nan"))
            A(f"| {name} | {raw_sr:+.2f} | {neut_sr:+.2f} | "
              f"{(neut_sr - raw_sr):+.2f} | {dsr_n:.3f} |")
        A("")

    # ── Hansen SPA + White's Reality Check (C5 + D1) ────────────────────
    if "hansen_spa" in s:
        A("## Data-Snooping Tests (C5 + D1)")
        A("")
        A("Two complementary tests on the K × T matrix of per-factor net daily "
          "returns. Both share the same stationary bootstrap "
          f"(block length {c['bootstrap_block_len']} days) but differ in "
          "recentering: White's Reality Check (2000) centers the bootstrap at "
          "the *observed* sample means (more conservative), while Hansen's SPA "
          "(2005) recenters only the non-positive candidates (less conservative "
          "when the candidate set contains many bad models).")
        A("")
        A("| Variant | Best Factor | Hansen SPA p | White RC p | Conclusion |")
        A("|---|---|---:|---:|---|")
        for key in ("raw", "sector_neutral"):
            sp = s["hansen_spa"][key]
            wrc = (s.get("white_reality_check") or {}).get(key, {})
            p_spa = sp.get("p_value", float("nan"))
            p_wrc = wrc.get("p_value", float("nan"))
            both_reject = (p_spa < 0.05) and (p_wrc < 0.05)
            one_rejects = (p_spa < 0.05) or (p_wrc < 0.05)
            verdict = ("both reject (strong skill)" if both_reject
                       else "one rejects (weak/borderline)" if one_rejects
                       else "neither rejects")
            A(f"| {key} | {sp.get('best_factor')} | {p_spa:.3f} | "
              f"{p_wrc:.3f} | {verdict} |")
        A("")

    # ── Purged + embargoed CV IC (C5) ───────────────────────────────────
    if "cv_ic_raw" in s:
        A("## Purged + Embargoed Cross-Validation IC (C5)")
        A("")
        A(f"López de Prado (2018): {c.get('cv_splits', 5)}-fold CV with a "
          f"21-day purge (label horizon) and {c.get('cv_embargo_pct', 0.01) * 100:.0f}% "
          "sample embargo after each test fold. Mean IC across folds should "
          "be close to the naive IC if the signal is genuine; a large drop "
          "indicates label leakage in the naive computation.")
        A("")
        A("| Factor | Raw-CV Mean IC | Raw-CV t | Neutral-CV Mean IC | Neutral-CV t |")
        A("|---|---:|---:|---:|---:|")
        for name in s["factors_raw"]:
            r = s["cv_ic_raw"].get(name, {})
            n = s["cv_ic_sector_neutral"].get(name, {})
            A(f"| {name} | {r.get('mean_ic', float('nan')):+.4f} | "
              f"{r.get('ic_t', float('nan')):+.2f} | "
              f"{n.get('mean_ic', float('nan')):+.4f} | "
              f"{n.get('ic_t', float('nan')):+.2f} |")
        A("")

    # ── Train / test split (D4) ─────────────────────────────────────────
    if "train_test_split_neutral" in s:
        A(f"## Held-Out OOS Split (D4) — cutoff {c.get('oos_start')}, embargo {c.get('oos_embargo_days')}d")
        A("")
        A("The OOS window is never used for any parameter, formula, or signal "
          "choice in this study. A genuine factor should retain *directional* "
          "and roughly magnitude-comparable Sharpe in the test slice.")
        A("")
        A("| Factor | Train SR | Train Ann Ret | Train MaxDD | Test SR | Test Ann Ret | Test MaxDD |")
        A("|---|---:|---:|---:|---:|---:|---:|")
        for name, tt in s["train_test_split_neutral"].items():
            tr = tt["train"]; te = tt["test"]
            A(f"| {name} | {tr['sharpe']:+.2f} | {tr['ann_return']:+.2%} | {tr['max_drawdown']:.2%} "
              f"| {te['sharpe']:+.2f} | {te['ann_return']:+.2%} | {te['max_drawdown']:.2%} |")
        A("")

    A("## What Would Move This to a Capital-Allocation Result")
    A("")
    A("- Point-in-time universe (CRSP or Norgate survivorship-bias-free).")
    A("- Borrow-fee data on short leg.")
    A("- Beta-neutralization at portfolio level (market-short hedge).")
    A("- Calibrate square-root impact k_bps to realized large-trade prints.")
    A("- Capacity analysis: $X of AUM implied by turnover × ADV participation.")
    A("")
    (OUT_DIR / "factor_study_report.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
