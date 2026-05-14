#!/usr/bin/env python3
"""Orchestrator CLI for the local Binance parquet store.

This is the ONLY module in alphaforge-crypto that touches the network. Every
other module reads from `<repo>/data/binance/`.

Pipeline:
    discover universe → pin top-N to manifest → download streams → validate

Example invocations:
    # smoke test
    python3 sync_binance_data.py --top-n 3 --start-date 2025-01-01 --end-date 2025-01-07

    # full v0 backfill
    python3 sync_binance_data.py --top-n 30 --start-date 2020-01-01

    # explicit symbol list (bypass universe selection)
    python3 sync_binance_data.py --symbols BTCUSDT ETHUSDT SOLUSDT --start-date 2024-01-01
"""

from __future__ import annotations

import argparse
import json
from datetime import date

from data.binance_client import BinanceClient
from data.downloader import BinanceDataDownloader
from data.paths import default_paths
from data.universe import (
    DEFAULT_TOP_N,
    discover_usdt_perpetuals,
    select_top_n_by_volume,
    write_universe_manifest,
)
from data.validator import BinanceDataValidator


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync AlphaForge Binance market data to local parquet store")
    parser.add_argument("--start-date", default="2020-01-01", help="Inclusive UTC start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", default=None, help="Inclusive UTC end date (YYYY-MM-DD)")
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N, help="Top N USDT perpetuals by 24h volume")
    parser.add_argument("--symbols", nargs="*", default=None, help="Explicit symbol list (overrides --top-n)")
    parser.add_argument("--kline-interval", default="1h", help="Kline interval (1m, 5m, 1h, 1d, ...)")
    parser.add_argument("--data-dir", default=None, help="Override parquet store root")
    parser.add_argument("--no-spot", action="store_true", help="Skip spot klines")
    parser.add_argument("--no-perp", action="store_true", help="Skip perp klines")
    parser.add_argument("--no-funding", action="store_true", help="Skip funding rate history")
    parser.add_argument("--include-open-interest", action="store_true",
                        help="Include OI history (Binance only serves trailing 30d)")
    args = parser.parse_args()

    end_date = args.end_date or date.today().isoformat()
    paths = default_paths(args.data_dir)

    with BinanceClient() as client:
        if args.symbols:
            symbols = [s.upper() for s in args.symbols]
            print(f"Using explicit symbol list: {symbols}")
            quote_volume = None
            specs_for_manifest = None
        else:
            print("Discovering USDT-margined perpetuals...")
            all_perps = discover_usdt_perpetuals(client)
            print(f"  found {len(all_perps)} TRADING USDT perpetuals")

            top = select_top_n_by_volume(client, all_perps, top_n=args.top_n)
            symbols = [p.symbol for p in top]
            print(f"  top {args.top_n} by 24h quote volume: {symbols}")

            tickers = client.fapi_24h_tickers()
            quote_volume = {row["symbol"]: float(row.get("quoteVolume", 0.0)) for row in tickers}
            specs_for_manifest = top

        if specs_for_manifest is not None:
            manifest_path = write_universe_manifest(
                specs_for_manifest,
                top_n=args.top_n,
                base_dir=args.data_dir,
                quote_volume_by_symbol=quote_volume,
            )
            print(f"Universe manifest written: {manifest_path}")

        downloader = BinanceDataDownloader(
            client,
            base_dir=args.data_dir,
            kline_interval=args.kline_interval,
        )
        print(f"Syncing {len(symbols)} symbols from {args.start_date} to {end_date}...")
        result = downloader.sync(
            symbols=symbols,
            start_date=args.start_date,
            end_date=end_date,
            include_spot=not args.no_spot,
            include_perp=not args.no_perp,
            include_funding=not args.no_funding,
            include_open_interest=args.include_open_interest,
        )
        print(f"  total rows downloaded: {result.total_rows()}")
        print(f"  files written: {len(set(result.files_written))}")

    print("Validating parquet store...")
    validator = BinanceDataValidator(base_dir=args.data_dir, kline_interval=args.kline_interval)
    report = validator.validate_all(
        symbols=symbols,
        include_spot=not args.no_spot,
        include_perp=not args.no_perp,
        include_funding=not args.no_funding,
        include_open_interest=args.include_open_interest,
    )

    report_path = paths.binance_root / "_validation_report.json"
    report_path.write_text(json.dumps(report.to_dict(), indent=2))
    print(f"  clean streams: {report.clean_count}")
    print(f"  flagged streams: {report.flagged_count}")
    print(f"  full report: {report_path}")

    for item in report.items:
        if item.issues:
            codes = ", ".join(i.code for i in item.issues)
            print(f"  FLAGGED {item.symbol}/{item.stream}: {codes}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
