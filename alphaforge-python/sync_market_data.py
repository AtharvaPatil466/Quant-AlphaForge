#!/usr/bin/env python3
"""Download, validate, and document the local parquet-backed market-data store."""

from __future__ import annotations

import argparse
from datetime import date

from data.market import (
    ALL_REAL_TICKERS,
    MarketDataDownloader,
    MarketDataValidator,
    write_universe_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync AlphaForge real market data to local parquet files")
    parser.add_argument("--start-date", default="2010-01-01", help="Inclusive start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", default=None, help="Inclusive end date (YYYY-MM-DD)")
    parser.add_argument("--tickers", nargs="*", default=None, help="Optional explicit ticker subset")
    parser.add_argument("--data-dir", default=None, help="Override parquet store root")
    parser.add_argument("--chunk-size", type=int, default=10, help="Download chunk size")
    args = parser.parse_args()

    tickers = args.tickers or ALL_REAL_TICKERS
    manifest_path = write_universe_manifest()

    downloader = MarketDataDownloader(base_dir=args.data_dir, chunk_size=args.chunk_size)
    sync_result = downloader.sync(
        tickers=tickers,
        start_date=args.start_date,
        end_date=args.end_date or date.today().isoformat(),
    )

    validator = MarketDataValidator(base_dir=args.data_dir)
    report = validator.validate_all(tickers=tickers, quarantine=True)

    clean = sum(1 for item in report.tickers if item.clean)
    flagged = len(report.tickers) - clean
    print(f"Universe manifest: {manifest_path}")
    print(f"Downloaded rows: {sum(sync_result.downloaded_rows.values())}")
    print(f"Files written: {len(sync_result.written_files)}")
    print(f"Clean tickers: {clean}")
    print(f"Flagged tickers: {flagged}")
    for item in report.tickers:
        if item.issues:
            reasons = ", ".join(issue.code for issue in item.issues)
            print(f"{item.ticker}: FLAGGED ({reasons})")
        else:
            print(
                f"{item.ticker}: clean {item.clean_trading_days} days "
                f"({item.usable_start} -> {item.usable_end})"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
