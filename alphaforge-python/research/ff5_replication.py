"""Build FF5 + UMD replicas from local characteristics and PIT price panels.

This module is intentionally strict about inputs. True FF5 replication
requires local size/value/profitability/investment characteristics; it
cannot be recovered from OHLCV alone.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, Sequence

import numpy as np
import pandas as pd

from data.market.pit import load_pit_sector_map


REQUIRED_CHARACTERISTIC_COLUMNS = (
    "ticker",
    "market_cap",
    "book_to_market",
    "profitability",
    "investment",
)

_CHAR_ALIASES = {
    "mkt_cap": "market_cap",
    "marketcap": "market_cap",
    "size": "market_cap",
    "book_to_market_ratio": "book_to_market",
    "bm": "book_to_market",
    "btm": "book_to_market",
    "operating_profitability": "profitability",
    "op": "profitability",
    "asset_growth": "investment",
    "inv": "investment",
}

_NOISY_OPINV_SECTORS = {"Financials", "Real Estate", "Utilities"}


def _normalize_columns(columns: Sequence[str]) -> dict[str, str]:
    rename: dict[str, str] = {}
    for col in columns:
        raw = str(col).strip()
        upper = raw.lower().replace("-", "_").replace(" ", "_")
        rename[raw] = _CHAR_ALIASES.get(upper, upper)
    return rename


def load_characteristics_table(path: str | Path) -> pd.DataFrame:
    """Load a local monthly characteristics table.

    Required columns after normalization:
      `date, ticker, market_cap, book_to_market, profitability, investment`
    """
    file = Path(path).expanduser().resolve()
    if not file.exists():
        raise FileNotFoundError(f"characteristics table not found: {file}")
    if file.suffix.lower() == ".parquet":
        df = pd.read_parquet(file)
    else:
        df = pd.read_csv(file)

    df = df.rename(columns=_normalize_columns(df.columns))
    if "date" not in df.columns:
        raise ValueError("characteristics table requires a `date` column")
    missing = [c for c in REQUIRED_CHARACTERISTIC_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"characteristics table missing required columns: {missing}")

    out = df.loc[:, ["date", *REQUIRED_CHARACTERISTIC_COLUMNS]].copy()
    out["date"] = pd.to_datetime(out["date"]).dt.tz_localize(None).dt.normalize()
    out["ticker"] = out["ticker"].astype(str).str.upper()
    for col in REQUIRED_CHARACTERISTIC_COLUMNS[1:]:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    # Sanity-gate market_cap: SEC XBRL share counts have two recurring
    # corruption modes — (a) shares reported in raw units when the filing
    # actually used thousands or millions, producing 1e15+ market caps;
    # (b) shares missing entirely with a forward-fill default of 1, so
    # market_cap collapses to the share price (~$10-$500). Drop rows
    # outside [$50M, $5T] — this band is loose enough to pass every real
    # S&P 500 large-cap and tight enough to reject both pathologies.
    invalid_mc = (out["market_cap"] < 50e6) | (out["market_cap"] > 5e12)
    invalid_count = int(invalid_mc.sum())
    if invalid_count:
        out.loc[invalid_mc, "market_cap"] = pd.NA

    out = out.sort_values(["date", "ticker"]).reset_index(drop=True)
    return out


def _month_end_rebalance_dates(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(index.to_series().groupby(index.to_period("M")).max().tolist())


def _asof_panel(
    chars: pd.DataFrame,
    field: str,
    rebalance_dates: pd.DatetimeIndex,
    *,
    lag_rebalances: int = 1,
) -> pd.DataFrame:
    panel = chars.pivot(index="date", columns="ticker", values=field).sort_index()
    union_idx = panel.index.union(rebalance_dates)
    panel = panel.reindex(union_idx).sort_index().ffill().reindex(rebalance_dates)
    return panel.shift(lag_rebalances)


def _weighted_return(weights: pd.Series, returns_row: pd.Series) -> float:
    aligned = pd.concat([weights.rename("w"), returns_row.rename("r")], axis=1).dropna()
    if aligned.empty:
        return 0.0
    gross = aligned["w"].sum()
    if gross <= 0:
        return 0.0
    w = aligned["w"] / gross
    return float((w * aligned["r"]).sum())


def _portfolio_weights(
    names: Iterable[str],
    market_cap: pd.Series,
) -> pd.Series:
    names = [n for n in names if n in market_cap.index and np.isfinite(market_cap.get(n, np.nan))]
    if not names:
        return pd.Series(dtype=float)
    weights = market_cap.loc[names].clip(lower=0.0)
    total = float(weights.sum())
    if total <= 0:
        weights[:] = 1.0
        total = float(weights.sum())
    return (weights / total).astype(float)


def _safe_quantile(series: pd.Series, q: float) -> float | None:
    clean = series.dropna()
    if len(clean) < 3:
        return None
    return float(clean.quantile(q))


def _winsorize_cross_section(
    series: pd.Series,
    lower: float = 0.01,
    upper: float = 0.99,
) -> pd.Series:
    clean = series.dropna()
    if len(clean) < 10:
        return series.dropna()
    lo = float(clean.quantile(lower))
    hi = float(clean.quantile(upper))
    return series.clip(lower=lo, upper=hi).dropna()


def _breakpoint_quantiles(
    series: pd.Series,
    reference_names: pd.Index,
) -> tuple[float | None, float | None]:
    """Approximate French breakpoints from a restricted reference subset.

    We do not have CRSP/NYSE exchange flags locally, so use the large-cap
    subset as a proxy reference universe when possible.
    """
    ref = series.reindex(reference_names).dropna()
    if len(ref) >= 3:
        lo = _safe_quantile(ref, 0.3)
        hi = _safe_quantile(ref, 0.7)
        if lo is not None and hi is not None:
            return lo, hi
    return _safe_quantile(series, 0.3), _safe_quantile(series, 0.7)


def _momentum_12_2(close: pd.DataFrame, as_of: pd.Timestamp) -> pd.Series:
    if as_of not in close.index:
        return pd.Series(dtype=float)
    loc = close.index.get_loc(as_of)
    if isinstance(loc, slice):
        loc = loc.stop - 1
    if loc < 252:
        return pd.Series(dtype=float)
    start = max(0, loc - 252)
    skip = max(0, loc - 21)
    base = close.iloc[start]
    end = close.iloc[skip]
    out = end / base - 1.0
    return out.replace([np.inf, -np.inf], np.nan)


def build_ff5_umd_replica(
    close: pd.DataFrame,
    characteristics: pd.DataFrame,
    *,
    risk_free: pd.Series | None = None,
) -> pd.DataFrame:
    """Build daily FF5 + UMD replica returns from PIT close data.

    `close` should already be membership-masked on the PIT universe.
    `characteristics` must be a local lagged fundamentals table loaded by
    `load_characteristics_table()`.
    """
    if close.empty:
        return pd.DataFrame(columns=["MKT", "SMB", "HML", "RMW", "CMA", "UMD"])

    rebal_dates = _month_end_rebalance_dates(pd.DatetimeIndex(close.index))
    if len(rebal_dates) < 2:
        return pd.DataFrame(columns=["MKT", "SMB", "HML", "RMW", "CMA", "UMD"])

    sector_map = load_pit_sector_map()

    annual_rebal_dates = pd.DatetimeIndex([dt for dt in rebal_dates if pd.Timestamp(dt).month == 6])
    if len(annual_rebal_dates) < 2:
        annual_rebal_dates = rebal_dates

    # Annual FF-style characteristic sorts use current June month-end
    # characteristics that are already point-in-time gated by filing date.
    mc_panel_annual = _asof_panel(characteristics, "market_cap", annual_rebal_dates, lag_rebalances=0)
    btm_panel_annual = _asof_panel(characteristics, "book_to_market", annual_rebal_dates, lag_rebalances=0)
    prof_panel_annual = _asof_panel(characteristics, "profitability", annual_rebal_dates, lag_rebalances=0)
    inv_panel_annual = _asof_panel(characteristics, "investment", annual_rebal_dates, lag_rebalances=0)

    # Market and momentum can continue to update monthly.
    mc_panel_monthly = _asof_panel(characteristics, "market_cap", rebal_dates, lag_rebalances=0)

    daily_rets = close.pct_change()
    factor_rows: list[dict[str, float]] = []
    factor_index: list[pd.Timestamp] = []

    daily_factor_map: dict[pd.Timestamp, dict[str, float]] = {}

    # Annual FF5 characteristic sorts (July t -> June t+1).
    for i in range(len(annual_rebal_dates) - 1):
        dt = annual_rebal_dates[i]
        next_dt = annual_rebal_dates[i + 1]
        if dt not in close.index:
            continue

        prices_row = close.loc[dt]
        universe = prices_row.dropna().index
        if len(universe) < 20:
            continue

        mc = mc_panel_annual.loc[dt].reindex(universe).dropna()
        if len(mc) < 20:
            continue

        size_universe = mc.index
        size_cut = float(mc.median())
        small = mc[mc <= size_cut].index
        big = mc[mc > size_cut].index

        btm = btm_panel_annual.loc[dt].reindex(size_universe)
        btm = btm[btm > 0].dropna()
        eligible = btm.index
        opinv_eligible = pd.Index(
            [tk for tk in eligible if sector_map.get(str(tk).upper()) not in _NOISY_OPINV_SECTORS]
        )
        prof = prof_panel_annual.loc[dt].reindex(opinv_eligible)
        inv = inv_panel_annual.loc[dt].reindex(opinv_eligible)

        # The SEC-derived characteristic table is noisier than the
        # French library inputs. Clip only the most pathological annual
        # cross-sectional tails before forming 30/70 breakpoints.
        btm = _winsorize_cross_section(btm)
        prof = _winsorize_cross_section(prof)
        inv = _winsorize_cross_section(inv)

        btm_lo, btm_hi = _breakpoint_quantiles(btm, big)
        prof_lo, prof_hi = _breakpoint_quantiles(prof, big)
        inv_lo, inv_hi = _breakpoint_quantiles(inv, big)
        if None in (btm_lo, btm_hi, prof_lo, prof_hi, inv_lo, inv_hi):
            continue

        value_high = btm[btm >= btm_hi].index
        value_neutral = btm[(btm > btm_lo) & (btm < btm_hi)].index
        value_low = btm[btm <= btm_lo].index

        prof_robust = prof[prof >= prof_hi].index
        prof_neutral = prof[(prof > prof_lo) & (prof < prof_hi)].index
        prof_weak = prof[prof <= prof_lo].index

        inv_conservative = inv[inv <= inv_lo].index
        inv_neutral = inv[(inv > inv_lo) & (inv < inv_hi)].index
        inv_aggressive = inv[inv >= inv_hi].index

        portfolios = {
            "SV": _portfolio_weights(set(small) & set(value_high), mc),
            "SN": _portfolio_weights(set(small) & set(value_neutral), mc),
            "SG": _portfolio_weights(set(small) & set(value_low), mc),
            "BV": _portfolio_weights(set(big) & set(value_high), mc),
            "BN": _portfolio_weights(set(big) & set(value_neutral), mc),
            "BG": _portfolio_weights(set(big) & set(value_low), mc),
            "SR": _portfolio_weights(set(small) & set(prof_robust), mc),
            "SM": _portfolio_weights(set(small) & set(prof_neutral), mc),
            "SW": _portfolio_weights(set(small) & set(prof_weak), mc),
            "BR": _portfolio_weights(set(big) & set(prof_robust), mc),
            "BM": _portfolio_weights(set(big) & set(prof_neutral), mc),
            "BW": _portfolio_weights(set(big) & set(prof_weak), mc),
            "SC": _portfolio_weights(set(small) & set(inv_conservative), mc),
            "SNI": _portfolio_weights(set(small) & set(inv_neutral), mc),
            "SA": _portfolio_weights(set(small) & set(inv_aggressive), mc),
            "BC": _portfolio_weights(set(big) & set(inv_conservative), mc),
            "BNI": _portfolio_weights(set(big) & set(inv_neutral), mc),
            "BA": _portfolio_weights(set(big) & set(inv_aggressive), mc),
        }

        window = daily_rets.loc[(daily_rets.index > dt) & (daily_rets.index <= next_dt), size_universe]
        for day, row in window.iterrows():
            pv = {name: _weighted_return(w, row) for name, w in portfolios.items()}
            smb_hml = (pv["SV"] + pv["SN"] + pv["SG"]) / 3.0 - (pv["BV"] + pv["BN"] + pv["BG"]) / 3.0
            smb_rmw = (pv["SR"] + pv["SM"] + pv["SW"]) / 3.0 - (pv["BR"] + pv["BM"] + pv["BW"]) / 3.0
            smb_cma = (pv["SC"] + pv["SNI"] + pv["SA"]) / 3.0 - (pv["BC"] + pv["BNI"] + pv["BA"]) / 3.0
            entry = daily_factor_map.setdefault(day, {})
            entry["SMB"] = (smb_hml + smb_rmw + smb_cma) / 3.0
            entry["HML"] = 0.5 * (pv["SV"] + pv["BV"]) - 0.5 * (pv["SG"] + pv["BG"])
            entry["RMW"] = 0.5 * (pv["SR"] + pv["BR"]) - 0.5 * (pv["SW"] + pv["BW"])
            entry["CMA"] = 0.5 * (pv["SC"] + pv["BC"]) - 0.5 * (pv["SA"] + pv["BA"])

    # Monthly market and momentum sorts.
    for i in range(len(rebal_dates) - 1):
        dt = rebal_dates[i]
        next_dt = rebal_dates[i + 1]
        if dt not in close.index:
            continue

        prices_row = close.loc[dt]
        universe = prices_row.dropna().index
        if len(universe) < 20:
            continue

        mc = mc_panel_monthly.loc[dt].reindex(universe).dropna()
        if len(mc) < 20:
            continue

        universe = mc.index
        mom = _momentum_12_2(close[universe], dt)
        mom_lo = _safe_quantile(mom, 0.3)
        mom_hi = _safe_quantile(mom, 0.7)
        if None in (mom_lo, mom_hi):
            continue

        size_cut = float(mc.median())
        small = mc[mc <= size_cut].index
        big = mc[mc > size_cut].index

        mom_winners = mom[mom >= mom_hi].dropna().index
        mom_neutral = mom[(mom > mom_lo) & (mom < mom_hi)].dropna().index
        mom_losers = mom[mom <= mom_lo].dropna().index

        portfolios = {
            "SWIN": _portfolio_weights(set(small) & set(mom_winners), mc),
            "SMOM": _portfolio_weights(set(small) & set(mom_neutral), mc),
            "SLOS": _portfolio_weights(set(small) & set(mom_losers), mc),
            "BWIN": _portfolio_weights(set(big) & set(mom_winners), mc),
            "BMOM": _portfolio_weights(set(big) & set(mom_neutral), mc),
            "BLOS": _portfolio_weights(set(big) & set(mom_losers), mc),
            "MKT": _portfolio_weights(universe, mc),
        }

        window = daily_rets.loc[(daily_rets.index > dt) & (daily_rets.index <= next_dt), universe]
        for day, row in window.iterrows():
            pv = {name: _weighted_return(w, row) for name, w in portfolios.items()}
            mkt = pv["MKT"]
            if risk_free is not None and day in risk_free.index and np.isfinite(risk_free.loc[day]):
                mkt -= float(risk_free.loc[day])
            entry = daily_factor_map.setdefault(day, {})
            entry["MKT"] = mkt
            entry["UMD"] = 0.5 * (pv["SWIN"] + pv["BWIN"]) - 0.5 * (pv["SLOS"] + pv["BLOS"])

    for day in sorted(daily_factor_map):
        row = daily_factor_map[day]
        if {"MKT", "SMB", "HML", "RMW", "CMA", "UMD"} <= set(row):
            factor_rows.append(row)
            factor_index.append(day)

    columns = ["MKT", "SMB", "HML", "RMW", "CMA", "UMD"]
    if not factor_rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(factor_rows, index=pd.DatetimeIndex(factor_index)).reindex(columns=columns).sort_index()
