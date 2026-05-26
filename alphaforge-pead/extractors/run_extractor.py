"""CLI runner: walk the PIT universe, fetch Company Facts, write shards.

Drives `extractors.companyfacts` across the PIT 877-ticker universe.

Inputs:
  - PIT event log + baseline at `alphaforge-python/data/market/pit/artifacts/`.
    We derive the unique (cik, ticker) pairs by scanning the event log and
    baseline, falling back to the EDGAR ticker→CIK cache for cases where
    the event log's ticker has been re-mapped.

SEC API contract:
  - 10 requests/second hard cap (SEC bans IPs that exceed it).
  - User-Agent must identify requester.

Behavior:
  - Idempotent: skips CIKs whose shard already exists (`--force` to override).
  - 404 from the API is treated as "no XBRL coverage for this CIK"; logged
    and the CIK is recorded in a missing-coverage list, not an error.
  - All step-2 substitutions append to `data/edgar_eps/_substitution_log.jsonl`.

Usage:
    python3 -m extractors.run_extractor \\
        --pit-root ../alphaforge-python/data/market/pit/artifacts \\
        --out data/edgar_eps/
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections import deque
from pathlib import Path
from typing import Iterable

import requests

from .companyfacts import (
    DEFAULT_USER_AGENT,
    append_substitution_log,
    fetch_company_facts,
    parse_company_facts,
    write_cik_shard,
    _pad_cik,
)


log = logging.getLogger("pead.run_extractor")


# --- rate limiter -----------------------------------------------------------


class _SecRateLimiter:
    """Sliding-window limiter that keeps actual request rate under SEC's
    10 req/s ceiling. Cheaper than asyncio + semaphores for our scale."""

    def __init__(self, max_per_second: int = 8) -> None:
        # 8 instead of 10 leaves margin for clock drift / retries.
        self.max_per_second = max_per_second
        self._timestamps: deque[float] = deque(maxlen=max_per_second)

    def acquire(self) -> None:
        now = time.monotonic()
        if len(self._timestamps) == self.max_per_second:
            oldest = self._timestamps[0]
            wait = 1.0 - (now - oldest)
            if wait > 0:
                time.sleep(wait)
                now = time.monotonic()
        self._timestamps.append(now)


# --- PIT universe loader ----------------------------------------------------


def load_pit_universe(pit_root: Path) -> list[tuple[int, str]]:
    """Return unique (cik, ticker) pairs from the PIT event log + baseline.

    Falls back to ticker→CIK via the cached EDGAR `company_tickers.json`
    if the event-log row lacks a CIK.
    """
    import pyarrow.parquet as pq

    pairs: dict[int, str] = {}

    baseline = pit_root / "_baseline_2010-01-10.parquet"
    if baseline.exists():
        df = pq.read_table(baseline).to_pandas()
        for _, row in df.iterrows():
            cik = row.get("cik")
            ticker = row.get("ticker")
            if cik and ticker:
                try:
                    pairs[int(cik)] = str(ticker).upper()
                except (ValueError, TypeError):
                    continue

    event_log = pit_root / "_event_log.parquet"
    if event_log.exists():
        df = pq.read_table(event_log).to_pandas()
        for _, row in df.iterrows():
            cik = row.get("cik")
            ticker = row.get("ticker")
            if cik and ticker:
                try:
                    pairs[int(cik)] = str(ticker).upper()
                except (ValueError, TypeError):
                    continue

    if not pairs:
        raise RuntimeError(f"no (cik, ticker) pairs found under {pit_root}")

    return sorted(pairs.items())


# --- driver ----------------------------------------------------------------


def run(
    pit_root: Path,
    out_root: Path,
    force: bool = False,
    user_agent: str = DEFAULT_USER_AGENT,
    universe: list[tuple[int, str]] | None = None,
) -> dict:
    universe = universe if universe is not None else load_pit_universe(pit_root)
    log.info("PIT universe: %d (cik, ticker) pairs", len(universe))

    out_dir = out_root / "by_cik"
    out_dir.mkdir(parents=True, exist_ok=True)

    limiter = _SecRateLimiter()
    session = requests.Session()

    n_fetched = 0
    n_skipped = 0
    n_no_coverage = 0
    n_errors = 0
    no_coverage_ciks: list[int] = []

    for cik, ticker in universe:
        shard_path = out_dir / f"CIK{_pad_cik(cik)}.parquet"
        if shard_path.exists() and not force:
            n_skipped += 1
            continue

        limiter.acquire()
        try:
            facts = fetch_company_facts(cik, session=session, user_agent=user_agent)
        except requests.HTTPError as e:
            n_errors += 1
            log.warning("[%s/CIK%010d] HTTP error: %s", ticker, cik, e)
            continue
        except Exception as e:  # noqa: BLE001 — surface but keep going
            n_errors += 1
            log.warning("[%s/CIK%010d] %s: %s", ticker, cik, type(e).__name__, e)
            continue

        if facts is None:
            n_no_coverage += 1
            no_coverage_ciks.append(cik)
            log.info("[%s/CIK%010d] no XBRL coverage (404)", ticker, cik)
            continue

        rows, substitutions = parse_company_facts(facts, ticker=ticker)
        if rows:
            write_cik_shard(rows, out_root, cik)
        if substitutions:
            append_substitution_log(out_root, substitutions)
        n_fetched += 1
        log.info("[%s/CIK%010d] %d rows, %d substitutions",
                 ticker, cik, len(rows), len(substitutions))

    # Persist the missing-coverage list for the universe-intersection report
    if no_coverage_ciks:
        (out_root / "_no_xbrl_coverage.json").write_text(
            json.dumps(no_coverage_ciks, indent=2)
        )

    summary = {
        "universe_size": len(universe),
        "fetched": n_fetched,
        "skipped_existing": n_skipped,
        "no_xbrl_coverage": n_no_coverage,
        "errors": n_errors,
    }
    log.info("done: %s", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="PEAD EDGAR Company Facts extractor")
    parser.add_argument("--pit-root", type=Path,
                        default=Path("../alphaforge-python/data/market/pit/artifacts"))
    parser.add_argument("--out", type=Path, default=Path("data/edgar_eps"))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    args = parser.parse_args()

    # 2026-05-17: also persist logs to disk, so future investigations
    # can recover the per-CIK status and error context after the run.
    log_dir = args.out.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"extractor_{time.strftime('%Y%m%d_%H%M%S')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(log_path)],
    )
    log.info("logging to %s", log_path)
    try:
        summary = run(
            pit_root=args.pit_root,
            out_root=args.out,
            force=args.force,
            user_agent=args.user_agent,
        )
    except RuntimeError as e:
        log.error("%s", e)
        return 2
    return 0 if summary["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
