"""Build the four-factor return matrix for §7 residualization.

Per `research/INDIA_DESIGN.md` §7:

    Factor 1: Market (RM-Rf) — Nifty 500 EW return minus risk-free rate
    Factor 2: Risk-free rate — RBI 91-day T-Bill rate (external CSV or constant)
    Factor 3: Size (SMB-like)  — long bottom-half by free-float mcap,
                                  short top-half
    Factor 4: Liquidity        — long low-Amihud quintile, short high-Amihud

Outputs CSV consumable by `research/run_phase3.py --factor-matrix`. Without
this matrix, Phase 3 gauntlet runs on RAW portfolio returns and the verdict
is marked provisional. With it, the §7 alpha-intercept hard rule is enforced.

Known limitations carried into the verdict report:
  - No external RBI T-bill data. Defaults to constant 7%/yr (annualized,
    daily-compounded). Override with `--risk-free-csv` if you have a series.
  - No free-float-mcap source for SMB. Falls back to close × volume (daily
    turnover) as a proxy. This conflates size with liquidity to some degree
    — documented honestly in §14.8 as known limitation.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

# Path bootstrap — allow `python -m research.build_factor_matrix` from root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gauntlet import residualization as RES  # noqa: E402

log = logging.getLogger("india.build_factor_matrix")

DEFAULT_RISK_FREE_ANNUAL = 0.07   # 7%/yr — rough RBI T-bill long-run avg


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def load_bhavcopy_for_factors(
    processed_dir: Path,
    start: date,
    end: date,
    universe: set[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load close + volume wide panels from processed bhavcopy parquet.

    Optionally restrict to symbols in `universe` (e.g. Nifty 500 ever-members
    from `universe.pit`). If None, includes every EQ symbol in the parquet.
    """
    # Accept either {YYYY}.parquet (canonical, written by ingest.build_parquet)
    # or legacy bhavcopy*.parquet test fixtures.
    files = sorted(
        list(processed_dir.rglob("[0-9][0-9][0-9][0-9].parquet"))
        + list(processed_dir.rglob("bhavcopy*.parquet"))
    )
    if not files:
        raise FileNotFoundError(
            f"no bhavcopy parquets under {processed_dir}. Run downloader + "
            "build_parquet first."
        )
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    df = df[(df["date"] >= pd.Timestamp(start))
            & (df["date"] <= pd.Timestamp(end))]
    if df.empty:
        raise ValueError(f"no rows in factor-build window [{start}, {end}]")
    if universe is not None:
        df = df[df["symbol"].isin(universe)]
        if df.empty:
            raise ValueError("universe filter wiped out all rows")
    # Defensive dedup — see cs_calibration.load_ohl_panel for rationale.
    df = df.drop_duplicates(subset=["date", "symbol"], keep="first")

    close = df.pivot(index="date", columns="symbol", values="close").sort_index()
    volume = df.pivot(index="date", columns="symbol", values="volume").sort_index()
    # Align column space.
    all_syms = close.columns.union(volume.columns)
    return close.reindex(columns=all_syms), volume.reindex(columns=all_syms)


def load_universe_from_file(path: Path | None) -> set[str] | None:
    """One symbol per line, blank/comment lines ignored."""
    if path is None or not path.exists():
        return None
    out: set[str] = set()
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.add(line)
    return out or None


def build_risk_free_series(
    dates: pd.DatetimeIndex,
    csv_path: Path | None = None,
    constant_annual: float = DEFAULT_RISK_FREE_ANNUAL,
) -> pd.Series:
    """Daily risk-free rate aligned to `dates`.

    If `csv_path` is supplied, reads a 2-column CSV (date, rate_annual)
    and interpolates onto `dates`. Otherwise uses a constant annualized
    rate compounded daily.
    """
    if csv_path is not None and csv_path.exists():
        rf_df = pd.read_csv(csv_path, parse_dates=[0])
        rf_df = rf_df.set_index(rf_df.columns[0])
        rf_annual = rf_df.iloc[:, 0]
        rf_annual = rf_annual.reindex(dates, method="ffill").bfill()
        rf_daily = (1.0 + rf_annual) ** (1 / 252.0) - 1.0
        rf_daily.name = "Rf"
        return rf_daily

    # Constant fallback — log a clear warning so the user knows.
    log.warning("No risk-free CSV supplied; using constant %.2f%%/yr.",
                constant_annual * 100)
    rf_daily_value = (1.0 + constant_annual) ** (1 / 252.0) - 1.0
    return pd.Series(rf_daily_value, index=dates, name="Rf")


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def build_matrix(
    close: pd.DataFrame,
    volume: pd.DataFrame,
    risk_free_daily: pd.Series | None = None,
) -> pd.DataFrame:
    """Return the four-factor matrix using `gauntlet.residualization` helpers."""
    matrix = RES.build_factor_matrix(
        close=close, volume=volume,
        market_cap=None,                  # fall back to close * volume proxy
        risk_free_daily=risk_free_daily,
    )
    # Drop the 'const' column — `run_phase3.py` does not consume it; the
    # downstream `residualize()` adds its own intercept.
    if "const" in matrix.columns:
        matrix = matrix.drop(columns=["const"])
    return matrix


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Build the four-factor return matrix from bhavcopy."
    )
    p.add_argument("--processed-dir", type=Path,
                   default=Path("data/processed/bhavcopy"))
    p.add_argument("--start", type=_parse_date, required=True,
                   help="First date (YYYY-MM-DD).")
    p.add_argument("--end", type=_parse_date, required=True,
                   help="Last date (YYYY-MM-DD).")
    p.add_argument("--universe-file", type=Path, default=None,
                   help="Optional Nifty 500 ever-members file (one symbol per line).")
    p.add_argument("--risk-free-csv", type=Path, default=None,
                   help="Optional 2-column CSV (date, annualized_rate). "
                        "If absent, uses constant 7%%/yr.")
    p.add_argument("--risk-free-constant", type=float,
                   default=DEFAULT_RISK_FREE_ANNUAL,
                   help="Constant annualized risk-free fallback (default 0.07).")
    p.add_argument("--out", type=Path, required=True,
                   help="Output CSV path.")
    p.add_argument("-v", "--verbose", action="count", default=0)
    args = p.parse_args(argv)

    logging.basicConfig(
        level=max(logging.WARNING - 10 * args.verbose, logging.DEBUG),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    universe = load_universe_from_file(args.universe_file)
    if universe:
        log.info("Universe filter: %d symbols", len(universe))

    close, volume = load_bhavcopy_for_factors(
        args.processed_dir, args.start, args.end, universe=universe,
    )
    log.info("Loaded panel: %d dates × %d symbols",
             len(close.index), len(close.columns))

    rf = build_risk_free_series(
        close.index, csv_path=args.risk_free_csv,
        constant_annual=args.risk_free_constant,
    )

    matrix = build_matrix(close, volume, risk_free_daily=rf)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    matrix.to_csv(args.out)
    log.info("Wrote factor matrix: %s (%d dates × %d factors)",
             args.out, len(matrix), len(matrix.columns))
    print(f"Wrote {args.out} ({len(matrix)} dates × {len(matrix.columns)} factors)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
