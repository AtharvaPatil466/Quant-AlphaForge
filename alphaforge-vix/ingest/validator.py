"""Phase 0 exit-criteria validator for alphaforge-vix.

Per `VIX_DESIGN.md` §2.5 (as updated by §17.2 ADDENDUM, 2026-05-21).

Active checks:
  2. Term-structure indices — coverage + first-date sanity (CBOE)
  3. SPY + realized-vol panel — 5 known spike events (§2.3)
  4. ETP availability — SVXY full coverage + VXX post-relaunch + SVXY regime tag
  5. (orchestrator) cert document is filed

Cross-check (informational, not gating):
  - ^VIX from yfinance vs VIX from CBOE — daily-close correlation ≥ 0.99
  - VIX3M ≥ VIX on the majority of overlapping dates (long-run contango bias)

Gates 1 (VIX futures) and the FRED rate are SKIPPED per the ADDENDUM:
  - Futures: data source removed (CBOE moved to paid DataShop).
  - FRED: may fail from some networks; Phase 0 cert can proceed with the
    fallback series. Documented as §14.7 / §17 limitation.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

log = logging.getLogger("vix.ingest.validator")


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

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
# Helpers
# ---------------------------------------------------------------------------

def _is_weekday(d: date) -> bool:
    return d.weekday() < 5


# Expected earliest dates per §17.3 (post-ADDENDUM).
EXPECTED_FIRST_DATE = {
    "VIX": date(1990, 1, 2),
    "VIX1D": date(2022, 5, 13),
    "VIX9D": date(2011, 1, 4),
    "VIX3M": date(2009, 9, 18),
    "VIX6M": date(2008, 1, 2),
    "SPY_yf": date(1993, 1, 29),
    "VIX_yf": date(1990, 1, 2),
    "SVXY_yf": date(2011, 10, 4),
    "VXX_yf": date(2018, 1, 25),
}


# ---------------------------------------------------------------------------
# Check 2: term-structure indices
# ---------------------------------------------------------------------------

def check_term_structure(panel: pd.DataFrame | None) -> CheckResult:
    """All 5 CBOE indices present + earliest-date sanity per §17.3."""
    if panel is None or panel.empty:
        return CheckResult(
            name="term_structure",
            status=Status.FAIL.value,
            summary="No CBOE indices panel found. Run `ingest.cboe`.",
        )
    expected_cols = {"VIX", "VIX1D", "VIX9D", "VIX3M", "VIX6M"}
    missing = expected_cols - set(panel.columns)
    if missing:
        return CheckResult(
            name="term_structure",
            status=Status.FAIL.value,
            summary=f"Missing indices: {sorted(missing)}",
            metrics={"missing_columns": sorted(missing)},
        )
    per_col_first = {}
    drift_errors: list[str] = []
    for col in sorted(expected_cols):
        s = panel[col].dropna()
        if s.empty:
            drift_errors.append(f"{col}: all NaN")
            continue
        first = s.index.min().date()
        per_col_first[col] = first.isoformat()
        expected = EXPECTED_FIRST_DATE.get(col)
        # Allow ±5 calendar days of slack vs the published first-trading-day.
        if expected is not None:
            slack = abs((first - expected).days)
            if slack > 5:
                drift_errors.append(
                    f"{col}: first date {first} differs from expected "
                    f"{expected} by {slack} days"
                )

    last_date = panel.index.max().date()
    days_stale = (date.today() - last_date).days
    if days_stale > 7:
        drift_errors.append(f"Latest data is {days_stale} days old")

    status = Status.PASS if not drift_errors else Status.WARN
    return CheckResult(
        name="term_structure",
        status=status.value,
        summary=(f"5/5 indices present; "
                 f"{len(drift_errors)} drift warning(s)" if status is Status.WARN
                 else "5/5 indices present, first dates as expected"),
        metrics={
            "first_dates": per_col_first,
            "last_date": last_date.isoformat(),
            "rows": int(len(panel)),
        },
        errors=drift_errors,
    )


# ---------------------------------------------------------------------------
# Check 3: SPY + realized-vol spike events
# ---------------------------------------------------------------------------

def check_spy_spikes(spy_panel: pd.DataFrame | None,
                      spike_report=None) -> CheckResult:
    """Wraps `realized_vol.validate_spike_events`."""
    if spy_panel is None or spy_panel.empty:
        return CheckResult(
            name="spy_spike_events",
            status=Status.FAIL.value,
            summary="No SPY realized-vol panel. Run `ingest.yfinance_loader` "
                    "+ `ingest.realized_vol`.",
        )
    if spike_report is None:
        from ingest import realized_vol as RV
        spike_report = RV.validate_spike_events(spy_panel)

    failed = [r.name for r in spike_report.results if not r.passed]
    status = Status.PASS if spike_report.all_passed else Status.FAIL
    return CheckResult(
        name="spy_spike_events",
        status=status.value,
        summary=(f"{spike_report.n_passed}/{spike_report.n_total} "
                 f"known volatility-event spikes captured "
                 f"({'all PASS' if spike_report.all_passed else 'partial'})"),
        metrics={
            "n_passed": spike_report.n_passed,
            "n_total": spike_report.n_total,
            "per_spike": [
                {"name": r.name, "passed": r.passed,
                 "observed": r.observed, "summary": r.summary}
                for r in spike_report.results
            ],
        },
        errors=[r.summary for r in spike_report.results if not r.passed],
    )


# ---------------------------------------------------------------------------
# Check 4: ETP availability + SVXY regime tag
# ---------------------------------------------------------------------------

def check_etp_availability(
    svxy: pd.DataFrame | None,
    vxx: pd.DataFrame | None,
) -> CheckResult:
    """SVXY must cover 2011-10-04 → present with regime column populated.
    VXX must cover the post-2018 period; pre-2018 unavailability is EXPECTED
    per §17.3 and is therefore not a failure."""
    errs: list[str] = []
    metrics: dict[str, Any] = {}

    if svxy is None or svxy.empty:
        errs.append("SVXY parquet missing or empty")
    else:
        first = svxy.index.min().date()
        last = svxy.index.max().date()
        metrics["svxy_first"] = first.isoformat()
        metrics["svxy_last"] = last.isoformat()
        metrics["svxy_rows"] = int(len(svxy))
        if (first - EXPECTED_FIRST_DATE["SVXY_yf"]).days > 5:
            errs.append(
                f"SVXY first date {first} differs from expected "
                f"{EXPECTED_FIRST_DATE['SVXY_yf']}"
            )
        if "regime" not in svxy.columns:
            errs.append("SVXY missing `regime` column (restructuring tag)")
        else:
            n_pre = int((svxy["regime"] == "pre_restructuring").sum())
            n_post = int((svxy["regime"] == "post_restructuring").sum())
            metrics["svxy_pre_restructuring_rows"] = n_pre
            metrics["svxy_post_restructuring_rows"] = n_post
            if n_pre == 0:
                errs.append("SVXY has no pre-restructuring rows (expected ~1.5k)")
            if n_post == 0:
                errs.append("SVXY has no post-restructuring rows")

    if vxx is None or vxx.empty:
        errs.append("VXX parquet missing or empty")
    else:
        first = vxx.index.min().date()
        last = vxx.index.max().date()
        metrics["vxx_first"] = first.isoformat()
        metrics["vxx_last"] = last.isoformat()
        metrics["vxx_rows"] = int(len(vxx))
        if first.year < 2018:
            # Per §17.3, pre-2018 VXX is NOT available in yfinance. If we
            # see pre-2018 data, that's surprising but not failing.
            log.info("VXX has pre-2018 data: first=%s (unexpected per §17.3)",
                     first)

    status = Status.PASS if not errs else Status.FAIL
    summary = ("SVXY + VXX coverage as expected per §17 ADDENDUM"
               if status is Status.PASS
               else f"{len(errs)} ETP issue(s)")
    return CheckResult(
        name="etp_availability",
        status=status.value,
        summary=summary, metrics=metrics, errors=errs,
    )


# ---------------------------------------------------------------------------
# Cross-check: ^VIX (yfinance) vs VIX (CBOE)
# ---------------------------------------------------------------------------

def check_vix_cross_consistency(
    cboe_vix: pd.Series | None,
    yf_vix_close: pd.Series | None,
    min_correlation: float = 0.99,
) -> CheckResult:
    """The same underlying index. Closes should correlate ≥0.99."""
    if cboe_vix is None or yf_vix_close is None:
        return CheckResult(
            name="vix_cross_consistency",
            status=Status.SKIP.value,
            summary="Need both CBOE VIX panel and yfinance ^VIX series.",
        )
    cboe_vix.index = pd.to_datetime(cboe_vix.index)
    yf_vix_close.index = pd.to_datetime(yf_vix_close.index)
    common = cboe_vix.index.intersection(yf_vix_close.index)
    if len(common) < 100:
        return CheckResult(
            name="vix_cross_consistency",
            status=Status.WARN.value,
            summary=f"Only {len(common)} overlapping dates",
        )
    corr = float(cboe_vix.loc[common].corr(yf_vix_close.loc[common]))
    status = Status.PASS if corr >= min_correlation else Status.WARN
    return CheckResult(
        name="vix_cross_consistency",
        status=status.value,
        summary=(f"correlation = {corr:.4f} over {len(common)} dates "
                 f"(threshold {min_correlation:.2f})"),
        metrics={
            "n_overlap": int(len(common)),
            "correlation": corr,
        },
    )


# ---------------------------------------------------------------------------
# Cross-check: contango bias VIX3M ≥ VIX
# ---------------------------------------------------------------------------

def check_contango_bias(
    panel: pd.DataFrame | None,
    min_contango_fraction: float = 0.70,
) -> CheckResult:
    """Long-run contango bias: VIX3M ≥ VIX on most days. Sanity check on the
    structural premium that the strategy harvests."""
    if panel is None or "VIX" not in panel.columns or "VIX3M" not in panel.columns:
        return CheckResult(
            name="contango_bias",
            status=Status.SKIP.value,
            summary="Need both VIX and VIX3M columns in panel.",
        )
    both = panel[["VIX", "VIX3M"]].dropna()
    if len(both) < 100:
        return CheckResult(
            name="contango_bias",
            status=Status.WARN.value,
            summary=f"Only {len(both)} overlapping (VIX, VIX3M) dates",
        )
    contango_frac = float((both["VIX3M"] >= both["VIX"]).mean())
    status = Status.PASS if contango_frac >= min_contango_fraction else Status.WARN
    return CheckResult(
        name="contango_bias",
        status=status.value,
        summary=(f"VIX3M ≥ VIX on {contango_frac:.1%} of {len(both)} days "
                 f"(threshold {min_contango_fraction:.0%})"),
        metrics={
            "n_overlap": int(len(both)),
            "contango_fraction": contango_frac,
        },
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

@dataclass
class ValidatorInputs:
    """All data products the validator may consume. Any can be None."""
    cboe_panel: pd.DataFrame | None = None
    spy_panel: pd.DataFrame | None = None
    svxy_df: pd.DataFrame | None = None
    vxx_df: pd.DataFrame | None = None
    yf_vix_close: pd.Series | None = None


def run_phase0_validators(inputs: ValidatorInputs) -> dict[str, CheckResult]:
    """Run every check on the supplied inputs. Skipped checks emit
    Status.SKIP with a clear reason."""
    results: dict[str, CheckResult] = {}
    results["term_structure"] = check_term_structure(inputs.cboe_panel)
    results["spy_spike_events"] = check_spy_spikes(inputs.spy_panel)
    results["etp_availability"] = check_etp_availability(
        inputs.svxy_df, inputs.vxx_df,
    )
    results["vix_cross_consistency"] = check_vix_cross_consistency(
        inputs.cboe_panel["VIX"] if inputs.cboe_panel is not None
        and "VIX" in inputs.cboe_panel.columns else None,
        inputs.yf_vix_close,
    )
    results["contango_bias"] = check_contango_bias(inputs.cboe_panel)

    # Documented SKIPs per §17 ADDENDUM.
    results["vix_futures_settlements"] = CheckResult(
        name="vix_futures_settlements",
        status=Status.SKIP.value,
        summary="REMOVED per §17 ADDENDUM (CBOE moved to paid DataShop).",
    )
    results["fred_dgs3mo"] = CheckResult(
        name="fred_dgs3mo",
        status=Status.SKIP.value,
        summary=("Optional. May time out from some networks. Falls back to "
                 "constant rates per §14.7."),
    )
    return results


def render_markdown_report(
    results: dict[str, CheckResult],
    design_doc_sha: str = "",
) -> str:
    lines: list[str] = []
    from datetime import datetime, timezone
    counts = {s.value: 0 for s in Status}
    for r in results.values():
        counts[r.status] = counts.get(r.status, 0) + 1

    blocking = counts.get(Status.FAIL.value, 0)
    if blocking:
        lines.append(f"# Phase 0 Validation — NOT CERTIFIED")
        lines.append(f"")
        lines.append(f"**{blocking} blocking FAIL(s).**")
    else:
        lines.append(f"# Phase 0 Validation — CERTIFIED")
    lines.append("")
    lines.append(
        f"_Generated {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}_"
    )
    if design_doc_sha:
        lines.append(f"_VIX_DESIGN.md SHA-256: `{design_doc_sha}`_")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    for s in (Status.PASS, Status.WARN, Status.FAIL, Status.SKIP):
        lines.append(f"- **{s.value.upper()}**: {counts.get(s.value, 0)}")
    lines.append("")
    lines.append("## Per-check detail")
    lines.append("")
    for name, r in results.items():
        lines.append(f"### {name} — `{r.status.upper()}`")
        lines.append(f"{r.summary}\n")
        if r.metrics:
            lines.append("Metrics:")
            for k, v in r.metrics.items():
                if isinstance(v, (list, dict)) and len(str(v)) > 200:
                    lines.append(f"  - `{k}`: <{type(v).__name__} of len {len(v)}>")
                else:
                    lines.append(f"  - `{k}`: {v}")
            lines.append("")
        if r.errors:
            lines.append("Errors:")
            for e in r.errors[:10]:
                lines.append(f"  - {e}")
            if len(r.errors) > 10:
                lines.append(f"  - ... and {len(r.errors) - 10} more")
            lines.append("")
    return "\n".join(lines)
