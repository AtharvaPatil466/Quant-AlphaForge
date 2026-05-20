"""Corwin-Schultz cost-model calibration check — Phase 0 §6 deliverable.

Per `research/INDIA_DESIGN.md` §6:

    > Corwin-Schultz calibration check (Phase 0 deliverable): before any
    > backtest runs, compute Corwin-Schultz half-spread estimates on the
    > bhavcopy OHL data for a 50-stock random sample of Nifty 500 names
    > across IS, OOS-A, and OOS-B windows. Compare against the 5 bp
    > half-spread implicit in the parametric model. If Corwin-Schultz
    > shows median > 10 bp on Nifty 500 names, document the divergence
    > the same way Tier 2 documented the 2 bp vs 7-8 bp gap. Do not
    > recalibrate mid-research — document and proceed.

Sampling: 50 stocks selected with a *seeded* PRNG so the calibration
is reproducible across re-runs. Universe = either a supplied PIT
ever-members list or all symbols in the processed bhavcopy parquet.

Output:
  - `research/CS_CALIBRATION_REPORT.md` — markdown summary, including a
    PASS/WARN/FAIL line per window and the §6 documentation discipline
    flag if median > 10 bp.
  - `research/cs_calibration.json` — raw per-stock-per-window medians.

The result is *documented*, not used to recalibrate the gauntlet cost
model. Per §15 hard rules, cost numbers are frozen.
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from signals import cost_model as CM  # noqa: E402

log = logging.getLogger("india.cs_calibration")


# ---------------------------------------------------------------------------
# Substrate windows per INDIA_DESIGN.md §3
# ---------------------------------------------------------------------------

IS_START = date(2004, 1, 1)
IS_END = date(2014, 12, 31)
OOS_A_START = date(2015, 1, 1)
OOS_A_END = date(2019, 12, 31)
OOS_B_START = date(2020, 1, 1)
OOS_B_END = date(2026, 5, 18)

# Parametric assumption from cost_model.py / §6.
PARAMETRIC_HALF_SPREAD_BPS = 5.0
DIVERGENCE_DOCUMENT_THRESHOLD_BPS = 10.0   # §6 threshold for honest disclosure

DEFAULT_SAMPLE_SIZE = 50
DEFAULT_SEED = 20260518


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class WindowCalibration:
    name: str
    start: str
    end: str
    n_stocks_sampled: int
    n_stocks_with_data: int
    median_half_spread_bps: float | None
    p25_half_spread_bps: float | None
    p75_half_spread_bps: float | None
    mean_half_spread_bps: float | None
    above_threshold: bool       # median > 10 bp
    above_parametric: bool      # median > 5 bp (always true if any signal)
    per_stock_medians: dict[str, float] = field(default_factory=dict)


@dataclass
class CalibrationReport:
    sample_size_requested: int
    seed: int
    sample_symbols: list[str]
    parametric_half_spread_bps: float
    documentation_threshold_bps: float
    windows: list[WindowCalibration]
    generated_at: str


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_ohl_panel(
    processed_dir: Path,
    start: date,
    end: date,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return (high_df, low_df, close_df) wide panels filtered to window."""
    # Accept either {YYYY}.parquet (canonical) or legacy fixture name.
    files = sorted(
        list(processed_dir.rglob("[0-9][0-9][0-9][0-9].parquet"))
        + list(processed_dir.rglob("bhavcopy*.parquet"))
    )
    if not files:
        raise FileNotFoundError(
            f"no bhavcopy parquets under {processed_dir}. Run downloader "
            "+ build_parquet first."
        )
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    df = df[(df["date"] >= pd.Timestamp(start))
            & (df["date"] <= pd.Timestamp(end))]
    if df.empty:
        raise ValueError(f"no rows in [{start}, {end}]")
    # Defensive dedup: era-overlap dates can appear twice in the parquet
    # store when build_parquet processes the same unified file via both
    # passes. Exact-identical rows are safe to dedupe; conflicting rows
    # would already have been caught by the TOTTRDQTY cross-check.
    df = df.drop_duplicates(subset=["date", "symbol"], keep="first")

    high_df = df.pivot(index="date", columns="symbol", values="high").sort_index()
    low_df = df.pivot(index="date", columns="symbol", values="low").sort_index()
    close_df = df.pivot(index="date", columns="symbol", values="close").sort_index()
    syms = high_df.columns.union(low_df.columns).union(close_df.columns)
    return (high_df.reindex(columns=syms),
            low_df.reindex(columns=syms),
            close_df.reindex(columns=syms))


def load_universe(path: Path | None) -> set[str] | None:
    if path is None or not path.exists():
        return None
    out: set[str] = set()
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.add(line)
    return out or None


def sample_symbols(
    available: list[str],
    universe: set[str] | None,
    sample_size: int,
    seed: int,
) -> list[str]:
    """Pick `sample_size` symbols at random from the universe intersection."""
    pool = available
    if universe is not None:
        pool = [s for s in available if s in universe]
    if len(pool) == 0:
        raise ValueError("empty symbol pool after universe filter")
    actual_n = min(sample_size, len(pool))
    rng = random.Random(seed)
    return sorted(rng.sample(pool, actual_n))


# ---------------------------------------------------------------------------
# Per-window calibration
# ---------------------------------------------------------------------------

def calibrate_window(
    name: str, start: date, end: date,
    processed_dir: Path,
    sample: list[str],
    cs_window: int = 21,
) -> WindowCalibration:
    """Run Corwin-Schultz on the sampled stocks within the window. Returns
    per-window summary statistics."""
    high_df, low_df, close_df = load_ohl_panel(processed_dir, start, end)
    sample_in_data = [s for s in sample if s in high_df.columns]

    if not sample_in_data:
        return WindowCalibration(
            name=name, start=start.isoformat(), end=end.isoformat(),
            n_stocks_sampled=len(sample),
            n_stocks_with_data=0,
            median_half_spread_bps=None,
            p25_half_spread_bps=None, p75_half_spread_bps=None,
            mean_half_spread_bps=None,
            above_threshold=False, above_parametric=False,
        )

    cs = CM.corwin_schultz_spread(
        high=high_df[sample_in_data], low=low_df[sample_in_data],
        close=close_df[sample_in_data], window=cs_window,
    )
    # cs is a DataFrame of rolling half-spreads in bps. Per-stock median over time.
    per_stock_median = cs.median(axis=0, skipna=True)
    valid = per_stock_median.dropna()
    if valid.empty:
        return WindowCalibration(
            name=name, start=start.isoformat(), end=end.isoformat(),
            n_stocks_sampled=len(sample),
            n_stocks_with_data=len(sample_in_data),
            median_half_spread_bps=None,
            p25_half_spread_bps=None, p75_half_spread_bps=None,
            mean_half_spread_bps=None,
            above_threshold=False, above_parametric=False,
        )

    overall_median = float(valid.median())
    return WindowCalibration(
        name=name, start=start.isoformat(), end=end.isoformat(),
        n_stocks_sampled=len(sample),
        n_stocks_with_data=int((cs.notna().any(axis=0)).sum()),
        median_half_spread_bps=overall_median,
        p25_half_spread_bps=float(valid.quantile(0.25)),
        p75_half_spread_bps=float(valid.quantile(0.75)),
        mean_half_spread_bps=float(valid.mean()),
        above_threshold=(overall_median > DIVERGENCE_DOCUMENT_THRESHOLD_BPS),
        above_parametric=(overall_median > PARAMETRIC_HALF_SPREAD_BPS),
        per_stock_medians={s: float(v) for s, v in valid.items()},
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_calibration(
    processed_dir: Path,
    universe_path: Path | None = None,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    seed: int = DEFAULT_SEED,
    cs_window: int = 21,
) -> CalibrationReport:
    universe = load_universe(universe_path)
    # Use the union of symbols across all windows to choose the sample,
    # since we want one consistent sample evaluated in each window.
    high_df, *_ = load_ohl_panel(processed_dir, IS_START, OOS_B_END)
    available = list(high_df.columns)
    sample = sample_symbols(available, universe, sample_size, seed)
    log.info("Sampled %d symbols (seed=%d).", len(sample), seed)

    windows = []
    for name, start, end in (
        ("IS", IS_START, IS_END),
        ("OOS_A", OOS_A_START, OOS_A_END),
        ("OOS_B", OOS_B_START, OOS_B_END),
    ):
        try:
            w = calibrate_window(name, start, end, processed_dir, sample,
                                   cs_window=cs_window)
        except ValueError as e:
            log.warning("window %s skipped: %r", name, e)
            w = WindowCalibration(
                name=name, start=start.isoformat(), end=end.isoformat(),
                n_stocks_sampled=len(sample), n_stocks_with_data=0,
                median_half_spread_bps=None, p25_half_spread_bps=None,
                p75_half_spread_bps=None, mean_half_spread_bps=None,
                above_threshold=False, above_parametric=False,
            )
        windows.append(w)
        log.info("  %s: median=%s bp (n=%d/%d)",
                 name,
                 f"{w.median_half_spread_bps:.2f}"
                 if w.median_half_spread_bps is not None else "—",
                 w.n_stocks_with_data, w.n_stocks_sampled)

    return CalibrationReport(
        sample_size_requested=sample_size,
        seed=seed,
        sample_symbols=sample,
        parametric_half_spread_bps=PARAMETRIC_HALF_SPREAD_BPS,
        documentation_threshold_bps=DIVERGENCE_DOCUMENT_THRESHOLD_BPS,
        windows=windows,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def render_markdown(report: CalibrationReport) -> str:
    lines: list[str] = []
    flagged_windows = [w for w in report.windows if w.above_threshold]
    if flagged_windows:
        headline = ("# Corwin-Schultz Calibration — DIVERGENCE FLAGGED "
                    f"({len(flagged_windows)} window(s) > "
                    f"{report.documentation_threshold_bps:.0f} bp)")
    else:
        headline = "# Corwin-Schultz Calibration — Within Documentation Threshold"
    lines.append(headline)
    lines.append("")
    lines.append(f"_Generated {report.generated_at}_")
    lines.append("")
    lines.append(f"**Sample size:** {report.sample_size_requested} symbols "
                 f"(seed={report.seed})")
    lines.append(f"**Parametric half-spread (§6):** "
                 f"{report.parametric_half_spread_bps:.1f} bp")
    lines.append(f"**Divergence-document threshold (§6):** "
                 f"{report.documentation_threshold_bps:.1f} bp")
    lines.append("")
    lines.append("## Per-window summary")
    lines.append("")
    lines.append("| Window | Dates | N with data | Median (bp) | "
                 "P25 | P75 | Mean | vs §6 5bp | vs 10bp |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---|---|")
    for w in report.windows:
        if w.median_half_spread_bps is None:
            lines.append(f"| {w.name} | {w.start} → {w.end} | "
                         f"{w.n_stocks_with_data} | — | — | — | — | — | — |")
            continue
        lines.append(
            f"| {w.name} | {w.start} → {w.end} | {w.n_stocks_with_data} "
            f"| **{w.median_half_spread_bps:.2f}** "
            f"| {w.p25_half_spread_bps:.2f} | {w.p75_half_spread_bps:.2f} "
            f"| {w.mean_half_spread_bps:.2f} "
            f"| {'ABOVE' if w.above_parametric else 'below'} "
            f"| {'ABOVE ⚠' if w.above_threshold else 'below'} |"
        )
    lines.append("")
    if flagged_windows:
        lines.append("## §6 Documentation Discipline")
        lines.append("")
        lines.append("Per `INDIA_DESIGN.md` §6:")
        lines.append("")
        lines.append("> If Corwin-Schultz shows median > 10 bp on Nifty 500 "
                     "names, document the divergence the same way Tier 2 "
                     "documented the 2 bp vs 7-8 bp gap. **Do not recalibrate "
                     "mid-research** — document and proceed.")
        lines.append("")
        lines.append("Affected windows:")
        for w in flagged_windows:
            lines.append(
                f"- **{w.name}** ({w.start} → {w.end}): "
                f"median {w.median_half_spread_bps:.2f} bp "
                f"vs parametric {report.parametric_half_spread_bps:.1f} bp = "
                f"{w.median_half_spread_bps / report.parametric_half_spread_bps:.1f}× higher"
            )
        lines.append("")
        lines.append("This DIVERGENCE is recorded as documented finding under "
                     "§14 known limitations. The gauntlet cost model (§6) is "
                     "**not** modified — §15 hard rules freeze the cost "
                     "numbers. The cost-doubling Gate 4 stress is the "
                     "intended robustness check against this risk.")
        lines.append("")
    else:
        lines.append("## §6 Compliance")
        lines.append("")
        lines.append(f"All windows below the {report.documentation_threshold_bps:.0f} bp "
                     "documentation threshold. Parametric assumption holds "
                     "within tolerance; no §14 limitation update required.")
        lines.append("")
    lines.append("## Sample symbols")
    lines.append("")
    lines.append(f"{len(report.sample_symbols)} symbols, seeded so re-runs "
                 f"reproduce: `{', '.join(report.sample_symbols[:10])}` "
                 f"{'...' if len(report.sample_symbols) > 10 else ''}")
    return "\n".join(lines)


def report_to_json(report: CalibrationReport) -> dict[str, Any]:
    return {
        "sample_size_requested": report.sample_size_requested,
        "seed": report.seed,
        "sample_symbols": report.sample_symbols,
        "parametric_half_spread_bps": report.parametric_half_spread_bps,
        "documentation_threshold_bps": report.documentation_threshold_bps,
        "windows": [asdict(w) for w in report.windows],
        "generated_at": report.generated_at,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Corwin-Schultz half-spread calibration vs parametric §6."
    )
    p.add_argument("--processed-dir", type=Path,
                   default=Path("data/processed/bhavcopy"))
    p.add_argument("--universe-file", type=Path, default=None,
                   help="Optional Nifty 500 ever-members file.")
    p.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE)
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--cs-window", type=int, default=21)
    p.add_argument("--report-md", type=Path,
                   default=Path("research/CS_CALIBRATION_REPORT.md"))
    p.add_argument("--results-json", type=Path,
                   default=Path("research/cs_calibration.json"))
    p.add_argument("-v", "--verbose", action="count", default=0)
    args = p.parse_args(argv)

    logging.basicConfig(
        level=max(logging.WARNING - 10 * args.verbose, logging.DEBUG),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    report = run_calibration(
        processed_dir=args.processed_dir,
        universe_path=args.universe_file,
        sample_size=args.sample_size, seed=args.seed,
        cs_window=args.cs_window,
    )

    args.results_json.parent.mkdir(parents=True, exist_ok=True)
    args.results_json.write_text(json.dumps(report_to_json(report), indent=2))
    args.report_md.parent.mkdir(parents=True, exist_ok=True)
    args.report_md.write_text(render_markdown(report))

    log.info("CS calibration written: %s, %s", args.report_md, args.results_json)
    any_flagged = any(w.above_threshold for w in report.windows)
    return 1 if any_flagged else 0


if __name__ == "__main__":
    sys.exit(main())
