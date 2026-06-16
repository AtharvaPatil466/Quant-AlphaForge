"""Phase 0 exit-criteria validator for the Kalshi resolved-contract store.

Per `research/PREDICTION_MARKETS_DESIGN.md` §2 (Phase 0 exit gate). Three
gates plus a category-coverage report:

  1. Coverage           — count of resolved, volume-bearing contracts, and the
                          per-category breakdown (§2 exit-gate item 1 + item 4).
  2. Resolution integrity — `result` ∈ {yes,no} AND settlement_value consistent
                          with result, on ≥ 99.9% of rows (§2 exit-gate item 2).
  3. No-look-ahead      — entry-snapshot timestamp strictly precedes close_time
                          on 100% of rows (§2 exit-gate item 3, "by construction").

Architecture mirrors `alphaforge-india/ingest/validator.py`: each check is a
free function returning a `CheckResult`; an orchestrator runs them all and
writes a markdown + JSON report. The CLI exits nonzero on any blocking FAIL.

This module reads parquet only; it never touches the network.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any

# Path bootstrap — allow `python -m validation.validator` from sub-project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest import schema as S  # noqa: E402

log = logging.getLogger("prediction.validator")

# Pre-committed thresholds (§2 exit gate).
RESOLUTION_INTEGRITY_THRESHOLD: float = 0.999   # ≥ 99.9%
LOOKAHEAD_THRESHOLD: float = 1.0                 # 100%
# §3 minimum resolved volume-bearing count is set conservatively here; the
# substantive MDE-driven minimum is computed in Phase 1 (binary_mde). Phase 0
# only asserts a non-trivial floor so an empty/near-empty store cannot certify.
MIN_RESOLVED_CONTRACTS: int = 200


class Status(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    SKIP = "skip"


@dataclass
class CheckResult:
    name: str
    status: str
    summary: str
    metrics: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Parquet loading
# ---------------------------------------------------------------------------

def load_resolved(data_root: Path):
    """Load + concatenate all resolved-contract parquet shards.

    Looks under ``{data_root}/processed/resolved/part-*.parquet``. De-duplicates
    on ``ticker`` (resume can re-emit a ticker into a later shard). Returns an
    empty canonical frame if nothing is present.
    """
    import pandas as pd

    shard_dir = data_root / "processed" / "resolved"
    if not shard_dir.exists():
        return S.empty_frame()
    parts = sorted(shard_dir.glob("part-*.parquet"))
    if not parts:
        return S.empty_frame()
    frames = []
    for p in parts:
        try:
            frames.append(pd.read_parquet(p))
        except Exception as e:  # corrupt shard shouldn't abort the whole pass
            log.warning("could not read shard %s: %r", p.name, e)
    if not frames:
        return S.empty_frame()
    df = pd.concat(frames, ignore_index=True)
    if "ticker" in df.columns:
        df = df.drop_duplicates(subset=["ticker"], keep="last").reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_coverage(df) -> CheckResult:
    """Gate 1 + 4: resolved volume-bearing count and per-category breakdown."""
    import pandas as pd  # noqa: F401

    n = len(df)
    if n == 0:
        return CheckResult(
            "coverage", Status.SKIP.value,
            "No resolved contracts loaded yet.",
            metrics={"n_resolved": 0, "by_category": {}},
        )
    n_volume = int((df["volume_fp"].astype(float) > 0).sum())
    cats = (
        df.assign(_cat=df["category"].fillna("").replace("", "(uncategorized)"))
        .groupby("_cat")
        .size()
        .sort_values(ascending=False)
    )
    by_category = {str(k): int(v) for k, v in cats.items()}
    # Substrate window span (close_time min/max -> ISO).
    closes = df["close_time"].astype("int64")
    span = {
        "first_close": S.ns_to_iso(int(closes.min())),
        "last_close": S.ns_to_iso(int(closes.max())),
    }
    status = Status.PASS if n_volume >= MIN_RESOLVED_CONTRACTS else Status.FAIL
    summary = (
        f"{n_volume} volume-bearing resolved contracts across "
        f"{len(by_category)} categories "
        f"({span['first_close'][:10]} → {span['last_close'][:10]}). "
        f"Floor = {MIN_RESOLVED_CONTRACTS}."
    )
    return CheckResult(
        "coverage", status.value, summary,
        metrics={
            "n_resolved": n,
            "n_volume_bearing": n_volume,
            "min_required": MIN_RESOLVED_CONTRACTS,
            "by_category": by_category,
            "span": span,
        },
    )


def check_resolution_integrity(df) -> CheckResult:
    """Gate 2: result ∈ {yes,no} and settlement_value consistent, ≥ 99.9%."""
    n = len(df)
    if n == 0:
        return CheckResult(
            "resolution_integrity", Status.SKIP.value,
            "No resolved contracts loaded yet.", metrics={"n": 0},
        )
    results = df["result"].astype("string").str.lower()
    valid_result = results.isin(list(S.VALID_RESULTS))

    sv = df["settlement_value"].astype(float)
    # YES → settlement 1.0, NO → settlement 0.0 (within tolerance).
    expected = results.map({"yes": 1.0, "no": 0.0})
    consistent = (sv - expected).abs() <= 1e-6
    # Rows with an unparseable settlement value but a valid result are counted
    # as inconsistent (they cannot be reconciled).
    consistent = consistent.fillna(False)

    ok = valid_result & consistent
    n_ok = int(ok.sum())
    frac = n_ok / n
    n_bad_result = int((~valid_result).sum())
    n_bad_settle = int((valid_result & ~consistent).sum())

    status = Status.PASS if frac >= RESOLUTION_INTEGRITY_THRESHOLD else Status.FAIL
    summary = (
        f"{frac:.4%} of {n} rows have result∈{{yes,no}} with consistent "
        f"settlement (threshold {RESOLUTION_INTEGRITY_THRESHOLD:.1%}). "
        f"Bad result: {n_bad_result}; bad settlement: {n_bad_settle}."
    )
    errors = []
    if status is Status.FAIL:
        bad = df.loc[~ok, "ticker"].astype(str).head(10).tolist()
        errors = [f"example failing tickers: {bad}"]
    return CheckResult(
        "resolution_integrity", status.value, summary,
        metrics={
            "n": n, "n_ok": n_ok, "fraction_ok": frac,
            "n_bad_result": n_bad_result, "n_bad_settlement": n_bad_settle,
            "threshold": RESOLUTION_INTEGRITY_THRESHOLD,
        },
        errors=errors,
    )


def check_no_lookahead(df) -> CheckResult:
    """Gate 3: entry_snapshot_ts strictly < close_time on 100% of rows."""
    n = len(df)
    if n == 0:
        return CheckResult(
            "no_lookahead", Status.SKIP.value,
            "No resolved contracts loaded yet.", metrics={"n": 0},
        )
    snap = df["entry_snapshot_ts"].astype("int64")
    close = df["close_time"].astype("int64")
    # A valid snapshot must be present (>0) AND strictly before close.
    valid = (snap > 0) & (snap < close)
    n_ok = int(valid.sum())
    frac = n_ok / n
    status = Status.PASS if frac >= LOOKAHEAD_THRESHOLD else Status.FAIL
    summary = (
        f"{frac:.4%} of {n} rows have entry_snapshot_ts strictly before "
        f"close_time (threshold {LOOKAHEAD_THRESHOLD:.1%})."
    )
    errors = []
    if status is Status.FAIL:
        bad = df.loc[~valid, "ticker"].astype(str).head(10).tolist()
        errors = [f"example look-ahead/invalid-snapshot tickers: {bad}"]
    return CheckResult(
        "no_lookahead", status.value, summary,
        metrics={"n": n, "n_ok": n_ok, "fraction_ok": frac,
                 "threshold": LOOKAHEAD_THRESHOLD},
        errors=errors,
    )


def run_all_checks(df) -> list[CheckResult]:
    return [
        check_coverage(df),
        check_resolution_integrity(df),
        check_no_lookahead(df),
    ]


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------

def _icon(status: str) -> str:
    return {"pass": "PASS", "fail": "FAIL", "warn": "WARN", "skip": "SKIP"}.get(status, status)


def render_markdown(results: list[CheckResult]) -> str:
    n_pass = sum(1 for r in results if r.status == Status.PASS.value)
    n_fail = sum(1 for r in results if r.status == Status.FAIL.value)
    n_skip = sum(1 for r in results if r.status == Status.SKIP.value)
    overall = "PASS" if n_fail == 0 and n_pass > 0 else ("INCOMPLETE" if n_fail == 0 else "FAIL")

    lines = [
        f"# Phase 0 Validation — {overall}",
        "",
        f"**Date:** {date.today().isoformat()}",
        f"**Checks:** {n_pass} PASS / {n_fail} FAIL / {n_skip} SKIP",
        "",
        "| Check | Status | Summary |",
        "|-------|--------|---------|",
    ]
    for r in results:
        lines.append(f"| {r.name} | {_icon(r.status)} | {r.summary} |")

    # Category breakdown table from the coverage check.
    cov = next((r for r in results if r.name == "coverage"), None)
    if cov and cov.metrics.get("by_category"):
        lines += ["", "## Category coverage", "", "| Category | Resolved contracts |", "|---|---|"]
        for cat, cnt in cov.metrics["by_category"].items():
            lines.append(f"| {cat} | {cnt} |")

    # Errors block.
    errs = [(r.name, e) for r in results for e in r.errors]
    if errs:
        lines += ["", "## Errors", ""]
        for name, e in errs:
            lines.append(f"- **{name}**: {e}")
    return "\n".join(lines) + "\n"


def results_to_json(results: list[CheckResult]) -> dict[str, Any]:
    n_fail = sum(1 for r in results if r.status == Status.FAIL.value)
    n_pass = sum(1 for r in results if r.status == Status.PASS.value)
    return {
        "date": date.today().isoformat(),
        "overall": "PASS" if (n_fail == 0 and n_pass > 0) else ("INCOMPLETE" if n_fail == 0 else "FAIL"),
        "checks": [asdict(r) for r in results],
    }


def has_blocking_failure(results: list[CheckResult]) -> bool:
    return any(r.status == Status.FAIL.value for r in results)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Phase 0 validator for Kalshi resolved-contract store.")
    p.add_argument("--data-root", type=Path, default=Path("data"))
    p.add_argument("--report-md", type=Path, default=Path("research/PHASE0_VALIDATION.md"))
    p.add_argument("--report-json", type=Path, default=Path("research/phase0_validation.json"))
    p.add_argument("--verbose", "-v", action="count", default=0)
    args = p.parse_args(argv)

    logging.basicConfig(level=max(logging.WARNING - 10 * args.verbose, logging.DEBUG),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    df = load_resolved(args.data_root)
    results = run_all_checks(df)

    args.report_md.parent.mkdir(parents=True, exist_ok=True)
    args.report_md.write_text(render_markdown(results))
    args.report_json.parent.mkdir(parents=True, exist_ok=True)
    args.report_json.write_text(json.dumps(results_to_json(results), indent=2))

    log.info("validation report -> %s / %s", args.report_md, args.report_json)
    print(render_markdown(results))
    return 1 if has_blocking_failure(results) else 0


if __name__ == "__main__":
    sys.exit(main())
