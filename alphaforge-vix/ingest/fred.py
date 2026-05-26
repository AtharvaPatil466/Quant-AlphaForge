"""FRED 3-month T-bill rate (DGS3MO) for cost-of-carry adjustments.

Per `VIX_DESIGN.md` §6 — VIX-futures margin earns the 3M T-bill rate
during the position's hold time. This series is used in Phase 3 P&L
accounting; without it, the backtest assumes 0% on margin (conservative
in low-rate eras, understated in 2022+).

Spike test 2026-05-20: FRED CSV endpoint timed out twice from sandbox
(60s + 90s read timeouts). Worth retrying from the user's Mumbai
machine. This module is built to fail GRACEFULLY — if the download
times out, downstream code can fall back to a constant rate
(VIX_DESIGN.md acknowledges 0% pre-2022, ~4-5% post).
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd
import requests

log = logging.getLogger("vix.ingest.fred")

DGS3MO_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS3MO"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,text/plain,*/*;q=0.8",
}

# Fallback constant rates if FRED is unreachable. From §6 + §14.7.
# Annualized, simple convention. Daily compounding is (1+r)^(1/252) - 1.
FALLBACK_ANNUAL_RATE_PRE_2022 = 0.005     # ~0.5%/yr — ZIRP-era average
FALLBACK_ANNUAL_RATE_POST_2022 = 0.045    # ~4.5%/yr — post-hiking-cycle


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

@dataclass
class DownloadResult:
    path: Path | None
    bytes: int
    rows: int | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.path is not None and self.bytes > 0 and self.error is None


def output_path(root: Path) -> Path:
    return root / "rates" / "DGS3MO.csv"


def _atomic_write(path: Path, body: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    sha = hashlib.sha256(body).hexdigest()
    with tmp.open("wb") as fp:
        fp.write(body)
        fp.flush()
        os.fsync(fp.fileno())
    os.replace(tmp, path)
    return sha


def download_dgs3mo(
    output_root: Path,
    session: requests.Session | None = None,
    timeout: int = 60,
    max_attempts: int = 3,
) -> DownloadResult:
    """Download FRED DGS3MO with retry on timeout. Fails gracefully."""
    session = session or requests.Session()
    target = output_path(output_root)
    last_err: str | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            r = session.get(DGS3MO_URL, headers=DEFAULT_HEADERS, timeout=timeout)
            if r.status_code == 200 and len(r.content) > 200:
                # Sanity: should start with DATE header.
                head = r.content[:50].decode("utf-8", errors="ignore").upper()
                if "DATE" in head and "DGS3MO" in head:
                    _atomic_write(target, r.content)
                    df = parse_dgs3mo(target)
                    return DownloadResult(path=target, bytes=len(r.content),
                                          rows=len(df))
                last_err = f"200 OK but body doesn't look like DGS3MO CSV: {head!r}"
            elif r.status_code in (403, 404):
                # Permanent — URL pattern broken.
                return DownloadResult(
                    path=None, bytes=0, rows=None,
                    error=f"http {r.status_code} (permanent)",
                )
            else:
                last_err = f"http {r.status_code}"
        except requests.RequestException as e:
            last_err = repr(e)
        if attempt < max_attempts:
            time.sleep(min(2.0 ** attempt, 30.0))
    return DownloadResult(path=None, bytes=0, rows=None, error=last_err)


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------

def parse_dgs3mo(csv_path: Path) -> pd.Series:
    """Parse FRED DGS3MO CSV → pd.Series of annualized rates (decimal).

    FRED returns rates in PERCENT; we convert to decimal (e.g. 4.5 → 0.045).
    Missing values are encoded as "." in the FRED format.
    """
    df = pd.read_csv(csv_path)
    df.columns = [c.strip() for c in df.columns]
    # FRED CSVs use either "DATE" or "observation_date" depending on the
    # endpoint. Accept either.
    date_col = "DATE" if "DATE" in df.columns else df.columns[0]
    value_col = "DGS3MO" if "DGS3MO" in df.columns else df.columns[-1]
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=[date_col])
    df = df.set_index(date_col).sort_index()
    # "." → NaN, then percent → decimal.
    s = pd.to_numeric(df[value_col], errors="coerce") / 100.0
    s.name = "rate_annual"
    s.index.name = "date"
    return s


# ---------------------------------------------------------------------------
# Fallback series
# ---------------------------------------------------------------------------

def build_fallback_series(
    start: date, end: date,
    pre_2022_rate: float = FALLBACK_ANNUAL_RATE_PRE_2022,
    post_2022_rate: float = FALLBACK_ANNUAL_RATE_POST_2022,
) -> pd.Series:
    """Two-piece constant approximation when FRED is unreachable.

    Per §14.7 — risk-free rate is regime-dependent. This is a deliberate
    conservative fallback, NOT a replacement for the real series. The
    fallback is logged loudly so downstream verdicts flag the limitation.
    """
    log.warning(
        "Using FRED fallback rates: pre-2022=%.3f%%/yr, post-2022=%.3f%%/yr. "
        "Real DGS3MO series will produce a more accurate Phase 3 verdict.",
        pre_2022_rate * 100, post_2022_rate * 100,
    )
    idx = pd.date_range(pd.Timestamp(start), pd.Timestamp(end), freq="B")
    s = pd.Series(post_2022_rate, index=idx, name="rate_annual")
    s.loc[s.index < pd.Timestamp("2022-01-01")] = pre_2022_rate
    s.index.name = "date"
    return s


def annualized_to_daily(rate_annual: pd.Series) -> pd.Series:
    """Convert annualized rate to daily compounding factor: (1+r)^(1/252)-1."""
    return (1.0 + rate_annual) ** (1 / 252.0) - 1.0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Download FRED DGS3MO.")
    p.add_argument("--output-root", type=Path, default=Path("data"))
    p.add_argument("--timeout", type=int, default=60)
    p.add_argument("--max-attempts", type=int, default=3)
    p.add_argument("-v", "--verbose", action="count", default=0)
    args = p.parse_args(argv)

    logging.basicConfig(
        level=max(logging.WARNING - 10 * args.verbose, logging.DEBUG),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    r = download_dgs3mo(args.output_root,
                        timeout=args.timeout,
                        max_attempts=args.max_attempts)
    if r.ok:
        print(f"OK  bytes={r.bytes:,}  rows={r.rows}  path={r.path}")
        return 0
    print(f"FAIL  error={r.error}")
    print("  Phase 0 cert will use fallback rates (see fred.build_fallback_series).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
