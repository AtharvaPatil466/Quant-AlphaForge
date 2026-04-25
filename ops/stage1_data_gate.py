#!/usr/bin/env python3
"""Stage 1 verification gate for the parquet-backed market-data layer."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = ROOT_DIR / "alphaforge-python"
PROJECT_PYTHON = PROJECT_DIR / ".venv" / "bin" / "python"

CHECK_CODE = """
import json
import time

from data.market.loader import MarketDataLoader, MarketDataRangeError
from data.market.paths import universe_manifest_path, validation_report_path
from data.market.universe import manifest_records


def _manifest_map(payload):
    return {
        item["ticker"]: item
        for item in payload.get("tickers", [])
    }


loader = MarketDataLoader()
expected_manifest = {item["ticker"]: item for item in manifest_records()}
actual_manifest = _manifest_map(json.loads(universe_manifest_path().read_text()))
validation_report = _manifest_map(json.loads(validation_report_path().read_text()))

manifest_mismatches = []
for ticker, expected in expected_manifest.items():
    actual = actual_manifest.get(ticker)
    if actual != expected:
        manifest_mismatches.append(
            {
                "ticker": ticker,
                "expected_start": expected["usable_start"],
                "actual_start": None if actual is None else actual.get("usable_start"),
                "expected_end": expected["usable_end"],
                "actual_end": None if actual is None else actual.get("usable_end"),
            }
        )
for ticker in sorted(set(actual_manifest) - set(expected_manifest)):
    extra = actual_manifest[ticker]
    manifest_mismatches.append(
        {
            "ticker": ticker,
            "expected_start": None,
            "actual_start": extra.get("usable_start"),
            "expected_end": None,
            "actual_end": extra.get("usable_end"),
        }
    )

start_mismatches = []
for ticker, item in actual_manifest.items():
    reported = validation_report.get(ticker)
    if reported is None:
        start_mismatches.append(
            {
                "ticker": ticker,
                "manifest_start": item.get("usable_start"),
                "reported_start": None,
            }
        )
        continue
    if item.get("usable_start") != reported.get("usable_start"):
        start_mismatches.append(
            {
                "ticker": ticker,
                "manifest_start": item.get("usable_start"),
                "reported_start": reported.get("usable_start"),
            }
        )

range_checks = []
for ticker, bad_start in (("AAPL", "2010-01-01"), ("PSX", "2012-04-12")):
    try:
        loader.load_ticker(ticker, start_date=bad_start)
    except MarketDataRangeError as exc:
        range_checks.append(
            {
                "ticker": ticker,
                "requested_start": bad_start,
                "raised": True,
                "message": str(exc),
            }
        )
    else:
        range_checks.append(
            {
                "ticker": ticker,
                "requested_start": bad_start,
                "raised": False,
                "message": None,
            }
        )

quarantine_checks = []
quarantine_leaks = []
for ticker_dir in sorted(loader.paths.quarantine_root.iterdir()):
    if not ticker_dir.is_dir():
        continue
    active_dir = loader.paths.market_root / ticker_dir.name
    active_years = sorted(
        int(path.stem)
        for path in active_dir.glob("*.parquet")
        if path.stem.isdigit()
    ) if active_dir.exists() else []
    quarantined_years = sorted(
        int(path.stem)
        for path in ticker_dir.glob("*.parquet")
        if path.stem.isdigit()
    )
    quarantine_only_years = sorted(set(quarantined_years) - set(active_years))
    if not quarantine_only_years:
        continue
    df = loader.load_ticker(ticker_dir.name)
    loaded_years = sorted({int(year) for year in df.index.year.unique()}) if not df.empty else []
    leaked_years = sorted(set(quarantine_only_years) & set(loaded_years))
    quarantine_checks.append(
        {
            "ticker": ticker_dir.name,
            "quarantine_only_years": quarantine_only_years,
            "loaded_years": loaded_years,
            "leaked_years": leaked_years,
        }
    )
    if leaked_years:
        quarantine_leaks.append(
            {
                "ticker": ticker_dir.name,
                "leaked_years": leaked_years,
            }
        )

latencies = []
for ticker in sorted(actual_manifest):
    started = time.perf_counter()
    df = loader.load_ticker(
        ticker,
        start_date="2021-04-12",
        end_date="2026-04-10",
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
    latencies.append(
        {
            "ticker": ticker,
            "elapsed_ms": elapsed_ms,
            "rows": int(len(df)),
        }
    )

max_latency = max(latencies, key=lambda item: item["elapsed_ms"])
over_limit = [
    item for item in latencies
    if item["elapsed_ms"] > 50.0
]

print(
    json.dumps(
        {
            "manifest_sync": {
                "checked_tickers": len(expected_manifest),
                "mismatch_count": len(manifest_mismatches),
                "mismatches": manifest_mismatches[:10],
            },
            "report_alignment": {
                "checked_tickers": len(actual_manifest),
                "start_mismatch_count": len(start_mismatches),
                "start_mismatches": start_mismatches[:10],
            },
            "range_checks": range_checks,
            "quarantine_exclusion": {
                "checked_tickers": len(quarantine_checks),
                "leak_count": len(quarantine_leaks),
                "leaks": quarantine_leaks[:10],
            },
            "latency": {
                "checked_tickers": len(latencies),
                "max": max_latency,
                "over_limit_count": len(over_limit),
                "over_limit": over_limit[:10],
            },
        }
    )
)
""".strip()


def main() -> int:
    if not PROJECT_PYTHON.exists():
        raise FileNotFoundError(
            f"Missing interpreter for Stage 1 gate: {PROJECT_PYTHON}"
        )

    started = time.perf_counter()
    completed = subprocess.run(
        [str(PROJECT_PYTHON), "-c", CHECK_CODE],
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
        check=False,
    )

    if completed.returncode != 0:
        details = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"Stage 1 gate failed to execute:\n{details}".rstrip())

    stdout_lines = completed.stdout.strip().splitlines()
    if not stdout_lines:
        raise RuntimeError("Stage 1 gate produced no output.")
    result = json.loads(stdout_lines[-1])

    if result["manifest_sync"]["mismatch_count"] != 0:
        raise RuntimeError(
            "Manifest file is out of sync with generated defaults: "
            f"{result['manifest_sync']['mismatches']}"
        )
    if result["report_alignment"]["start_mismatch_count"] != 0:
        raise RuntimeError(
            "Manifest usable_start values do not match the validation report: "
            f"{result['report_alignment']['start_mismatches']}"
        )
    failed_range_checks = [
        item for item in result["range_checks"]
        if not item["raised"]
    ]
    if failed_range_checks:
        raise RuntimeError(
            "Pre-manifest range requests did not raise as expected: "
            f"{failed_range_checks}"
        )
    if result["quarantine_exclusion"]["leak_count"] != 0:
        raise RuntimeError(
            "Quarantined years leaked into active loader output: "
            f"{result['quarantine_exclusion']['leaks']}"
        )
    if result["latency"]["over_limit_count"] != 0:
        raise RuntimeError(
            "5-year parquet reads exceeded 50ms: "
            f"{result['latency']['over_limit']}"
        )

    total_seconds = round(time.perf_counter() - started, 3)
    print(
        f"PASS manifest-sync ({result['manifest_sync']['checked_tickers']} tickers)"
    )
    print(
        f"PASS report-alignment ({result['report_alignment']['checked_tickers']} tickers)"
    )
    print(
        "PASS range-errors "
        + ", ".join(
            f"{item['ticker']}<{item['requested_start']}>"
            for item in result["range_checks"]
        )
    )
    print(
        "PASS quarantine-exclusion "
        f"({result['quarantine_exclusion']['checked_tickers']} tickers checked)"
    )
    print(
        "PASS latency "
        f"(max {result['latency']['max']['ticker']} "
        f"{result['latency']['max']['elapsed_ms']}ms)"
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "total_seconds": total_seconds,
                "result": result,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
