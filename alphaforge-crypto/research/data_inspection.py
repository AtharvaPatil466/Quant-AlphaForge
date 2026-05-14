#!/usr/bin/env python3
"""Exploratory inspection of the local Binance parquet store.

Produces a markdown report and CSV exports under
`alphaforge-crypto/research/out/data_inspection/`. The point is to understand
the funding-rate and basis distributions BEFORE committing to a study design.

What it computes:

1.  **Coverage map** — per symbol: first/last bar, row counts for spot, perp,
    funding. Reveals which symbols onboarded mid-history.
2.  **Funding rate distribution** — per symbol summary stats (mean, median,
    std, |max|, q05, q95, share of negative rates), then a cross-symbol
    aggregate.
3.  **Funding autocorrelation** — ρ(funding_t, funding_{t-k}) for
    k ∈ {1, 3, 9, 21} (i.e. 8h, 1d, 3d, 7d ahead at 8h funding cadence).
    Cross-symbol mean reported.
4.  **Cross-sectional dispersion** — at each funding timestamp, what's the
    std and range of funding across the universe? If it's flat (everyone at
    0.0001 most of the time), there's no cross-sectional carry to harvest.
5.  **Spot-perp basis** — (perp_close - spot_close) / spot_close at each
    1h bar. Per-symbol summary + autocorrelation at k ∈ {1, 8, 24} hours.

The script is intentionally read-only and idempotent. Re-running just
overwrites the report.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import sys
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data.loader import load_funding_panel, load_klines_panel
from data.paths import default_paths
from data.universe import load_universe_manifest


OUT_DIR = PROJECT_ROOT / "research" / "out" / "data_inspection"

FUNDING_LAGS = [1, 3, 9, 21]   # 8h, 1d, 3d, 7d at 8h cadence
BASIS_LAGS_H = [1, 8, 24]       # 1h, 8h, 1d at 1h cadence


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    paths = default_paths()
    manifest = load_universe_manifest()
    symbols = [s["symbol"] for s in manifest["symbols"]]
    print(f"Loaded universe manifest: {len(symbols)} symbols")
    print(f"Parquet store: {paths.binance_root}")

    coverage = _coverage_report(symbols)
    coverage.to_csv(OUT_DIR / "coverage.csv", index=False)

    funding_stats, funding_panel = _funding_distribution(symbols)
    funding_stats.to_csv(OUT_DIR / "funding_stats_per_symbol.csv", index=False)

    funding_autocorr = _funding_autocorrelation(funding_panel)
    funding_autocorr.to_csv(OUT_DIR / "funding_autocorrelation.csv", index=False)

    cross_section = _funding_cross_section(funding_panel)
    cross_section.to_csv(OUT_DIR / "funding_cross_section.csv", index=False)

    basis_stats, basis_panel = _basis_distribution(symbols)
    basis_stats.to_csv(OUT_DIR / "basis_stats_per_symbol.csv", index=False)
    basis_autocorr = _basis_autocorrelation(basis_panel)
    basis_autocorr.to_csv(OUT_DIR / "basis_autocorrelation.csv", index=False)

    report_path = OUT_DIR / "INSPECTION_REPORT.md"
    report_path.write_text(_render_report(
        coverage=coverage,
        funding_stats=funding_stats,
        funding_autocorr=funding_autocorr,
        cross_section=cross_section,
        basis_stats=basis_stats,
        basis_autocorr=basis_autocorr,
    ))
    print(f"Report written: {report_path}")
    print(f"CSV exports: {OUT_DIR}")
    return 0


# ---- coverage ----------------------------------------------------------------

def _coverage_report(symbols: list[str]) -> pd.DataFrame:
    rows: list[dict] = []
    for symbol in symbols:
        spot = load_klines_panel([symbol], market="spot")
        perp = load_klines_panel([symbol], market="perp")
        funding = load_funding_panel([symbol])
        rows.append({
            "symbol": symbol,
            "spot_rows": len(spot),
            "spot_first_ts": _first_ts(spot, "open_time"),
            "spot_last_ts": _last_ts(spot, "open_time"),
            "perp_rows": len(perp),
            "perp_first_ts": _first_ts(perp, "open_time"),
            "perp_last_ts": _last_ts(perp, "open_time"),
            "funding_rows": len(funding),
            "funding_first_ts": _first_ts(funding, "funding_time"),
            "funding_last_ts": _last_ts(funding, "funding_time"),
        })
    return pd.DataFrame(rows)


def _first_ts(df: pd.DataFrame, col: str) -> str | None:
    if df.empty or col not in df.columns:
        return None
    return str(pd.to_datetime(int(df[col].min()), unit="ms", utc=True))


def _last_ts(df: pd.DataFrame, col: str) -> str | None:
    if df.empty or col not in df.columns:
        return None
    return str(pd.to_datetime(int(df[col].max()), unit="ms", utc=True))


# ---- funding distribution ----------------------------------------------------

def _funding_distribution(symbols: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    panel = load_funding_panel(symbols)
    if panel.empty:
        return pd.DataFrame(), panel

    rows: list[dict] = []
    for symbol, group in panel.groupby("symbol"):
        r = group["funding_rate"].astype(float)
        if r.empty:
            continue
        rows.append({
            "symbol": symbol,
            "n": int(r.size),
            "mean": float(r.mean()),
            "median": float(r.median()),
            "std": float(r.std()),
            "q05": float(r.quantile(0.05)),
            "q95": float(r.quantile(0.95)),
            "min": float(r.min()),
            "max": float(r.max()),
            "abs_max": float(r.abs().max()),
            "share_negative": float((r < 0).mean()),
            "share_zero": float((r == 0).mean()),
            "annualized_mean_pct": float(r.mean() * 3 * 365 * 100),  # 3 events/day
        })
    stats = pd.DataFrame(rows).sort_values("annualized_mean_pct", ascending=False)
    return stats, panel


def _funding_autocorrelation(panel: pd.DataFrame) -> pd.DataFrame:
    if panel.empty:
        return pd.DataFrame()
    rows: list[dict] = []
    for symbol, group in panel.groupby("symbol"):
        series = group.sort_values("funding_time")["funding_rate"].astype(float).reset_index(drop=True)
        if len(series) < max(FUNDING_LAGS) + 5:
            continue
        row = {"symbol": symbol, "n": int(series.size)}
        for lag in FUNDING_LAGS:
            row[f"rho_lag_{lag}"] = float(series.autocorr(lag=lag))
        rows.append(row)
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame

    summary_row = {"symbol": "_mean_across_symbols", "n": int(frame["n"].mean())}
    for lag in FUNDING_LAGS:
        summary_row[f"rho_lag_{lag}"] = float(frame[f"rho_lag_{lag}"].mean())
    return pd.concat([frame, pd.DataFrame([summary_row])], ignore_index=True)


def _funding_cross_section(panel: pd.DataFrame) -> pd.DataFrame:
    if panel.empty:
        return pd.DataFrame()
    wide = panel.pivot_table(
        index="funding_time", columns="symbol", values="funding_rate", aggfunc="last"
    )
    if wide.empty:
        return wide
    cs = pd.DataFrame({
        "funding_time": wide.index,
        "ts_utc": pd.to_datetime(wide.index, unit="ms", utc=True),
        "n_symbols": wide.notna().sum(axis=1).values,
        "cs_mean": wide.mean(axis=1).values,
        "cs_std": wide.std(axis=1).values,
        "cs_min": wide.min(axis=1).values,
        "cs_max": wide.max(axis=1).values,
        "cs_range": (wide.max(axis=1) - wide.min(axis=1)).values,
        "cs_q05": wide.quantile(0.05, axis=1).values,
        "cs_q95": wide.quantile(0.95, axis=1).values,
    })
    return cs


# ---- basis -----------------------------------------------------------------

def _basis_distribution(symbols: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict] = []
    panel_chunks: list[pd.DataFrame] = []
    for symbol in symbols:
        spot = load_klines_panel([symbol], market="spot")
        perp = load_klines_panel([symbol], market="perp")
        if spot.empty or perp.empty:
            continue
        spot_small = spot[["open_time", "close"]].rename(columns={"close": "spot_close"})
        perp_small = perp[["open_time", "close"]].rename(columns={"close": "perp_close"})
        merged = spot_small.merge(perp_small, on="open_time", how="inner")
        if merged.empty:
            continue
        merged["symbol"] = symbol
        merged["basis_pct"] = (merged["perp_close"] - merged["spot_close"]) / merged["spot_close"]
        b = merged["basis_pct"].astype(float).dropna()
        if b.empty:
            continue
        rows.append({
            "symbol": symbol,
            "n": int(b.size),
            "mean_bps": float(b.mean() * 1e4),
            "median_bps": float(b.median() * 1e4),
            "std_bps": float(b.std() * 1e4),
            "q05_bps": float(b.quantile(0.05) * 1e4),
            "q95_bps": float(b.quantile(0.95) * 1e4),
            "abs_max_bps": float(b.abs().max() * 1e4),
            "share_negative": float((b < 0).mean()),
        })
        panel_chunks.append(merged[["symbol", "open_time", "spot_close", "perp_close", "basis_pct"]])
    stats = pd.DataFrame(rows).sort_values("abs_max_bps", ascending=False)
    panel = pd.concat(panel_chunks, ignore_index=True) if panel_chunks else pd.DataFrame()
    return stats, panel


def _basis_autocorrelation(panel: pd.DataFrame) -> pd.DataFrame:
    if panel.empty:
        return pd.DataFrame()
    rows: list[dict] = []
    for symbol, group in panel.groupby("symbol"):
        series = group.sort_values("open_time")["basis_pct"].astype(float).reset_index(drop=True)
        if len(series) < max(BASIS_LAGS_H) + 5:
            continue
        row = {"symbol": symbol, "n": int(series.size)}
        for lag in BASIS_LAGS_H:
            row[f"rho_lag_{lag}h"] = float(series.autocorr(lag=lag))
        rows.append(row)
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    summary = {"symbol": "_mean_across_symbols", "n": int(frame["n"].mean())}
    for lag in BASIS_LAGS_H:
        summary[f"rho_lag_{lag}h"] = float(frame[f"rho_lag_{lag}h"].mean())
    return pd.concat([frame, pd.DataFrame([summary])], ignore_index=True)


# ---- report rendering ------------------------------------------------------

def _render_report(**sections) -> str:
    lines = [
        "# Binance Data Inspection Report",
        "",
        f"_Generated {datetime.now(timezone.utc).isoformat()}_",
        "",
        "Read this before designing the carry/basis study. Numbers reported are descriptive only — no strategy is being backtested here.",
        "",
    ]

    cov: pd.DataFrame = sections["coverage"]
    lines += ["## Coverage", "", _df_to_md(cov, max_rows=40), ""]

    fs: pd.DataFrame = sections["funding_stats"]
    lines += [
        "## Funding rate distribution (per symbol)",
        "",
        "Funding events occur every 8h on Binance USDT-M perpetuals (3 events/day). `annualized_mean_pct` ≈ mean × 3 × 365 × 100. Positive funding ⇒ longs pay shorts.",
        "",
        _df_to_md(fs, max_rows=40, float_fmt="{:.6f}"),
        "",
    ]

    fa: pd.DataFrame = sections["funding_autocorr"]
    lines += [
        "## Funding rate autocorrelation",
        "",
        f"Lags reported: {FUNDING_LAGS} funding events (8h cadence). Lag 1 = 8h, lag 3 = 1d, lag 9 = 3d, lag 21 = 7d. The cross-symbol mean is the row labeled `_mean_across_symbols`.",
        "",
        _df_to_md(fa, max_rows=40, float_fmt="{:.4f}"),
        "",
    ]

    cs: pd.DataFrame = sections["cross_section"]
    if not cs.empty:
        summary = pd.DataFrame({
            "metric": ["cs_std", "cs_range"],
            "mean": [float(cs["cs_std"].mean()), float(cs["cs_range"].mean())],
            "median": [float(cs["cs_std"].median()), float(cs["cs_range"].median())],
            "q95": [float(cs["cs_std"].quantile(0.95)), float(cs["cs_range"].quantile(0.95))],
            "max": [float(cs["cs_std"].max()), float(cs["cs_range"].max())],
        })
        lines += [
            "## Cross-sectional funding dispersion",
            "",
            "At each funding timestamp, how much spread is there across the universe? If `cs_std` is near zero most of the time, cross-sectional carry has no signal to rank on.",
            "",
            _df_to_md(summary, float_fmt="{:.6f}"),
            "",
        ]

    bs: pd.DataFrame = sections["basis_stats"]
    lines += [
        "## Spot-perp basis distribution (per symbol)",
        "",
        "`basis_pct = (perp_close - spot_close) / spot_close` measured at every 1h close, reported in bps (1 bp = 0.01%). Positive basis ⇒ perp trades above spot.",
        "",
        _df_to_md(bs, max_rows=40, float_fmt="{:.2f}"),
        "",
    ]

    ba: pd.DataFrame = sections["basis_autocorr"]
    lines += [
        "## Spot-perp basis autocorrelation",
        "",
        f"Lags reported: {BASIS_LAGS_H} hours.",
        "",
        _df_to_md(ba, max_rows=40, float_fmt="{:.4f}"),
        "",
    ]

    return "\n".join(lines)


def _df_to_md(df: pd.DataFrame, *, max_rows: int = 30, float_fmt: str = "{:.4f}") -> str:
    if df.empty:
        return "_(no data)_"
    if len(df) > max_rows:
        df = pd.concat([df.head(max_rows), pd.DataFrame([{c: "..." for c in df.columns}])], ignore_index=True)
    headers = list(df.columns)
    rows = []
    for _, row in df.iterrows():
        cells = []
        for c in headers:
            v = row[c]
            if isinstance(v, float) and np.isfinite(v):
                cells.append(float_fmt.format(v))
            elif v is None or (isinstance(v, float) and not np.isfinite(v)):
                cells.append("")
            else:
                cells.append(str(v))
        rows.append("| " + " | ".join(cells) + " |")
    header_line = "| " + " | ".join(headers) + " |"
    sep_line = "|" + "|".join("---" for _ in headers) + "|"
    return "\n".join([header_line, sep_line] + rows)


if __name__ == "__main__":
    raise SystemExit(main())
