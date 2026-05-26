"""CBOE VIX index downloader — spot + four term-structure indices.

Per `VIX_DESIGN.md` §2.2 (and the §17 ADDENDUM which makes these the
ONLY structural-vol inputs after VIX futures settlement data became
unavailable). Five symbols share one URL template:

    https://cdn.cboe.com/api/global/us_indices/daily_prices/{NAME}_History.csv

where `NAME ∈ {VIX, VIX1D, VIX9D, VIX3M, VIX6M}`. All five return a CSV
with `DATE,OPEN,HIGH,LOW,CLOSE` and `DATE` in `MM/DD/YYYY` format.

Coverage (verified by spike test 2026-05-20):
    VIX       — 1990-01-02 → present  (full substrate window)
    VIX6M     — 2008-01-02 → present  (covers 4 years into IS)
    VIX3M     — 2009-09-18 → present  (covers 5.7 years into IS)
    VIX9D     — 2011-01-04 → present  (covers 7 years into IS)
    VIX1D     — 2022-05-13 → present  (OOS-B only)

The downloader writes one CSV per symbol to disk (atomic write) and
provides parsers to load them into a unified wide panel. Atomic-write
+ retry pattern mirrors `alphaforge-india/ingest/downloader.py`.
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

log = logging.getLogger("vix.ingest.cboe")

CDN_BASE = "https://cdn.cboe.com/api/global/us_indices/daily_prices"

# All five symbols share the same URL template.
SYMBOLS: tuple[str, ...] = ("VIX", "VIX1D", "VIX9D", "VIX3M", "VIX6M")

# Browser-shaped headers. CBOE's CDN has been observed to 403 default
# `python-requests/X` UA strings.
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,application/csv,text/plain,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

RETRY_BACKOFF = (2.0, 8.0, 32.0)


# ---------------------------------------------------------------------------
# URL + path construction
# ---------------------------------------------------------------------------

def url_for(symbol: str) -> str:
    if symbol not in SYMBOLS:
        raise ValueError(f"unknown CBOE symbol {symbol!r}; expected one of {SYMBOLS}")
    return f"{CDN_BASE}/{symbol}_History.csv"


def output_path(root: Path, symbol: str) -> Path:
    """Where the downloaded CSV is written: {root}/vix_indices/{symbol}.csv"""
    return root / "vix_indices" / f"{symbol}.csv"


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

class HaltedError(Exception):
    """Raised when CBOE returns a status that indicates the URL pattern is
    fundamentally broken (404 / 403) rather than transient (5xx / timeout)."""


@dataclass
class DownloadResult:
    symbol: str
    status: int | None
    bytes: int
    sha256: str | None
    attempts: int
    path: Path | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == 200 and self.bytes > 200 and self.path is not None


def _atomic_write(path: Path, body: bytes) -> str:
    """Write body to path atomically. Returns sha256 hex."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    sha = hashlib.sha256(body).hexdigest()
    with tmp.open("wb") as fp:
        fp.write(body)
        fp.flush()
        os.fsync(fp.fileno())
    os.replace(tmp, path)
    return sha


def download_index(
    symbol: str,
    output_root: Path,
    session: requests.Session | None = None,
    timeout: int = 30,
) -> DownloadResult:
    """Download a single CBOE index CSV. Retries 3× on transient errors
    (timeouts, 5xx). 4xx halts immediately (URL pattern is wrong)."""
    session = session or requests.Session()
    url = url_for(symbol)
    target = output_path(output_root, symbol)

    last_status: int | None = None
    last_error: str | None = None
    for attempt_idx, backoff in enumerate(RETRY_BACKOFF, start=1):
        try:
            resp = session.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
            last_status = resp.status_code
            body = resp.content
            if resp.status_code == 200 and len(body) > 200:
                # Sanity check: body should look like the CBOE CSV header.
                head = body[:50].decode("utf-8", errors="ignore").upper()
                if "DATE" not in head or "CLOSE" not in head:
                    raise HaltedError(
                        f"{symbol}: 200 OK but body doesn't look like a CBOE "
                        f"CSV. First 50 bytes: {head!r}"
                    )
                sha = _atomic_write(target, body)
                return DownloadResult(
                    symbol=symbol, status=200, bytes=len(body), sha256=sha,
                    attempts=attempt_idx, path=target,
                )
            if resp.status_code in (403, 404):
                # Permanent — URL pattern is wrong. Halt.
                raise HaltedError(
                    f"{symbol}: CBOE returned {resp.status_code} on {url}. "
                    "URL pattern may have changed."
                )
            # 5xx or 200 with empty body — retry.
            last_error = f"http {resp.status_code} body={len(body)}"
        except HaltedError:
            raise
        except requests.RequestException as e:
            last_error = repr(e)
        if attempt_idx < len(RETRY_BACKOFF):
            time.sleep(backoff)
    return DownloadResult(
        symbol=symbol, status=last_status, bytes=0, sha256=None,
        attempts=len(RETRY_BACKOFF), path=None, error=last_error,
    )


def download_all(
    output_root: Path,
    session: requests.Session | None = None,
    rate_limit_seconds: float = 1.0,
) -> dict[str, DownloadResult]:
    """Download all five symbols. Polite spacing between downloads."""
    session = session or requests.Session()
    out: dict[str, DownloadResult] = {}
    for i, sym in enumerate(SYMBOLS):
        if i > 0:
            time.sleep(rate_limit_seconds)
        log.info("CBOE download: %s", sym)
        out[sym] = download_index(sym, output_root, session=session)
    return out


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_index(csv_path: Path, symbol: str | None = None) -> pd.DataFrame:
    """Parse a CBOE index CSV into a DataFrame indexed by date.

    Columns: open, high, low, close (lowercased).
    """
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)
    df = pd.read_csv(csv_path)
    df.columns = [c.strip().lower() for c in df.columns]
    required = {"date", "open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"{csv_path}: CBOE CSV missing columns {missing}; got {list(df.columns)}"
        )
    # MM/DD/YYYY is the canonical CBOE format. Some files use ISO; accept both.
    df["date"] = pd.to_datetime(df["date"], format="mixed", errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    if symbol is not None:
        df["symbol"] = symbol
    return df.set_index("date")[["open", "high", "low", "close"]]


def build_term_structure_panel(data_root: Path) -> pd.DataFrame:
    """Combine VIX + VIX1D/9D/3M/6M into one wide panel indexed by date.

    Columns: VIX, VIX1D, VIX9D, VIX3M, VIX6M (close prices).
    Symbols are reindexed to the union of dates; non-coverage is NaN
    (e.g., VIX1D is NaN before 2022-05-13).
    """
    frames = []
    for sym in SYMBOLS:
        path = output_path(data_root, sym)
        if not path.exists():
            log.warning("missing %s — skipping", path)
            continue
        df = parse_index(path, symbol=sym)
        frames.append(df["close"].rename(sym))
    if not frames:
        raise FileNotFoundError(
            f"no CBOE index files under {data_root}/vix_indices/. Run "
            "`download_all` first."
        )
    panel = pd.concat(frames, axis=1, sort=True).sort_index()
    return panel


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Download CBOE VIX + term-structure indices."
    )
    p.add_argument("--output-root", type=Path, default=Path("data"),
                   help="Output root (default: ./data). CSVs land under "
                        "<root>/vix_indices/.")
    p.add_argument("--symbols", type=str, default=",".join(SYMBOLS),
                   help="Comma-separated symbols (default: all 5).")
    p.add_argument("--rate-limit-seconds", type=float, default=1.0)
    p.add_argument("-v", "--verbose", action="count", default=0)
    args = p.parse_args(argv)

    logging.basicConfig(
        level=max(logging.WARNING - 10 * args.verbose, logging.DEBUG),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    symbols = tuple(s.strip().upper() for s in args.symbols.split(",") if s.strip())
    unknown = [s for s in symbols if s not in SYMBOLS]
    if unknown:
        log.error("unknown symbols: %s", unknown)
        return 2

    sess = requests.Session()
    results: dict[str, DownloadResult] = {}
    for i, sym in enumerate(symbols):
        if i > 0:
            time.sleep(args.rate_limit_seconds)
        log.info("downloading %s ...", sym)
        try:
            results[sym] = download_index(sym, args.output_root, session=sess)
        except HaltedError as e:
            log.error("HALT on %s: %s", sym, e)
            results[sym] = DownloadResult(
                symbol=sym, status=403, bytes=0, sha256=None,
                attempts=1, path=None, error=str(e),
            )

    n_ok = sum(1 for r in results.values() if r.ok)
    log.info("done: %d / %d successful", n_ok, len(results))
    for sym in symbols:
        r = results[sym]
        tag = "OK" if r.ok else "FAIL"
        size = f"{r.bytes:,}B" if r.bytes else "—"
        print(f"  [{sym}] {tag}  bytes={size}  sha={r.sha256[:8] if r.sha256 else '—'}")

    return 0 if n_ok == len(symbols) else 1


if __name__ == "__main__":
    sys.exit(main())
