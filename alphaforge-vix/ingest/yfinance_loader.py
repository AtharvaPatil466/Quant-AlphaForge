"""yfinance-backed loaders for SPY / ^VIX / SVXY / VXX.

Per `VIX_DESIGN.md` §2.3 + §2.4 + §17 ADDENDUM (2026-05-21):

  SPY      — realized-vol input. Full history 1993 → present. Required.
  ^VIX     — spot VIX for cross-check vs CBOE indices. 1990 → present.
  SVXY     — short-vol ETP. 2011-10-04 → present. **Regime change**
             on 2018-02-27 when exposure shifted from -1× to -0.5×.
             Loader tags every row with `regime ∈ {"pre_restructuring",
             "post_restructuring"}` so downstream code can split safely.
  VXX      — long-vol ETP, **post-relaunch only** per §17 ADDENDUM.
             yfinance carries 2018-01-25 → present. The original
             2009-2019 Barclays VXX is NOT in yfinance.

Output schema (parquet, one per ticker under `data/etps/`):
  date, open, high, low, close, adj_close, volume,
  dividends, stock_splits, [regime — SVXY only]
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

log = logging.getLogger("vix.ingest.yfinance")


# ---------------------------------------------------------------------------
# Ticker registry
# ---------------------------------------------------------------------------

# SVXY restructuring date — exposure changed from -1× to -0.5×.
# Per CBOE/ProShares announcements + VIX_DESIGN.md §14.4.
SVXY_RESTRUCTURING_DATE = date(2018, 2, 27)


@dataclass(frozen=True)
class TickerSpec:
    ticker: str
    description: str
    expected_first_date: date
    note: str = ""


TICKERS: dict[str, TickerSpec] = {
    "SPY": TickerSpec(
        ticker="SPY",
        description="S&P 500 ETF — realized-vol input for VRP signal",
        expected_first_date=date(1993, 1, 29),
    ),
    "^VIX": TickerSpec(
        ticker="^VIX",
        description="Spot VIX index — cross-check against CBOE indices",
        expected_first_date=date(1990, 1, 2),
    ),
    "SVXY": TickerSpec(
        ticker="SVXY",
        description="Short-vol ETP — primary execution instrument",
        expected_first_date=date(2011, 10, 4),
        note=("2018-02-27 restructuring: exposure changed -1× → -0.5×. "
              "Loader tags `regime` column accordingly."),
    ),
    "VXX": TickerSpec(
        ticker="VXX",
        description="Long-vol ETP — hedge instrument (post-relaunch only)",
        expected_first_date=date(2018, 1, 25),
        note=("yfinance carries only the 2018+ relaunch instrument; "
              "the original 2009-2019 Barclays VXX is unavailable."),
    ),
}


# ---------------------------------------------------------------------------
# Output paths
# ---------------------------------------------------------------------------

def output_path(root: Path, ticker_key: str) -> Path:
    """Where the parquet for a ticker is written: {root}/etps/{ticker}.parquet.

    The `^VIX` ticker is written under `vix_yf.parquet` (no `^` in filename).
    """
    safe = ticker_key.replace("^", "").lower() or "vix"
    if ticker_key == "^VIX":
        safe = "vix_yf"
    return root / "etps" / f"{safe}.parquet"


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

@dataclass
class DownloadResult:
    ticker: str
    path: Path | None
    rows: int
    first_date: date | None
    last_date: date | None
    meets_expected_first: bool
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.rows > 0 and self.path is not None and self.error is None


def _yf_history(ticker: str, period: str = "max"):
    """Thin wrapper around yfinance.Ticker(...).history(period='max')."""
    import yfinance as yf
    return yf.Ticker(ticker).history(period=period, auto_adjust=False)


def download_ticker(
    ticker_key: str,
    output_root: Path,
    fetcher=_yf_history,
) -> DownloadResult:
    """Download one ticker via yfinance. Writes parquet. Returns metadata.

    `fetcher` is injectable so tests can supply a fake.
    """
    if ticker_key not in TICKERS:
        return DownloadResult(
            ticker=ticker_key, path=None, rows=0,
            first_date=None, last_date=None,
            meets_expected_first=False,
            error=f"unknown ticker {ticker_key!r}",
        )
    spec = TICKERS[ticker_key]
    try:
        hist = fetcher(spec.ticker, "max")
    except Exception as e:
        return DownloadResult(
            ticker=ticker_key, path=None, rows=0,
            first_date=None, last_date=None,
            meets_expected_first=False, error=repr(e),
        )

    if hist is None or len(hist) == 0:
        return DownloadResult(
            ticker=ticker_key, path=None, rows=0,
            first_date=None, last_date=None,
            meets_expected_first=False,
            error="yfinance returned empty frame",
        )

    # Normalize column names. yfinance returns "Open", "High", etc.
    hist = hist.copy()
    hist.columns = [c.lower().replace(" ", "_") for c in hist.columns]
    if "adj_close" not in hist.columns and "close" in hist.columns:
        # Some tickers (e.g. indices) don't have a separate adj_close.
        hist["adj_close"] = hist["close"]
    hist.index = pd.to_datetime(hist.index)
    if hist.index.tz is not None:
        hist.index = hist.index.tz_localize(None)
    hist.index.name = "date"

    # SVXY regime tag.
    if ticker_key == "SVXY":
        boundary = pd.Timestamp(SVXY_RESTRUCTURING_DATE)
        hist["regime"] = "pre_restructuring"
        hist.loc[hist.index >= boundary, "regime"] = "post_restructuring"

    target = output_path(output_root, ticker_key)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    hist.to_parquet(tmp)
    os.replace(tmp, target)

    first = hist.index.min().date()
    last = hist.index.max().date()
    return DownloadResult(
        ticker=ticker_key, path=target,
        rows=len(hist), first_date=first, last_date=last,
        meets_expected_first=(first <= spec.expected_first_date
                              or first <= spec.expected_first_date.replace(day=1)),
    )


def download_all(output_root: Path, fetcher=_yf_history) -> dict[str, DownloadResult]:
    return {key: download_ticker(key, output_root, fetcher=fetcher)
            for key in TICKERS}


def load_ticker(ticker_key: str, output_root: Path) -> pd.DataFrame:
    """Load a downloaded parquet for a ticker. Restores DatetimeIndex."""
    path = output_path(output_root, ticker_key)
    if not path.exists():
        raise FileNotFoundError(path)
    df = pd.read_parquet(path)
    if "date" in df.columns:  # round-trip safety if it ended up as a column
        df = df.set_index("date")
    df.index = pd.to_datetime(df.index)
    return df


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Download SPY/^VIX/SVXY/VXX from yfinance."
    )
    p.add_argument("--output-root", type=Path, default=Path("data"))
    p.add_argument("--tickers", type=str,
                   default=",".join(TICKERS.keys()),
                   help=f"Comma-separated subset of {sorted(TICKERS)}")
    p.add_argument("-v", "--verbose", action="count", default=0)
    args = p.parse_args(argv)

    logging.basicConfig(
        level=max(logging.WARNING - 10 * args.verbose, logging.DEBUG),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    keys = [k.strip() for k in args.tickers.split(",") if k.strip()]
    unknown = [k for k in keys if k not in TICKERS]
    if unknown:
        log.error("unknown tickers: %s", unknown)
        return 2

    n_ok = 0
    for key in keys:
        log.info("downloading %s ...", key)
        r = download_ticker(key, args.output_root)
        if r.ok:
            n_ok += 1
            print(f"  [{key}] OK  rows={r.rows:>5}  "
                  f"first={r.first_date}  last={r.last_date}")
        else:
            print(f"  [{key}] FAIL  error={r.error}")
    log.info("done: %d / %d successful", n_ok, len(keys))
    return 0 if n_ok == len(keys) else 1


if __name__ == "__main__":
    sys.exit(main())
