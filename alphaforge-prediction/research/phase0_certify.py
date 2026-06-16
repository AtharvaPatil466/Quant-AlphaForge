"""Phase 0 Certification Orchestrator (substrate #10 — Kalshi FLB).

Per `PREDICTION_MARKETS_DESIGN.md` §2 (Phase 0 exit gate) and §15 (SHA anchor):

  1. Runs the Phase 0 validators (`validation.validator`).
  2. Recomputes the SHA-256 of `research/PREDICTION_MARKETS_DESIGN.md`.
  3. Writes `research/PREDICTION_PHASE0_CERTIFIED.md` recording that SHA plus the
     validator results, and the overall CERTIFIED / INCOMPLETE verdict.

The cert is CERTIFIED iff every implemented gate passes (no FAIL, ≥1 PASS) — the
three §2 gates: coverage, resolution integrity, no-look-ahead. SKIPs (e.g. an
empty store before any pull) leave the verdict INCOMPLETE, never CERTIFIED.

Mirrors `alphaforge-india/research/phase0_certify.py`: delegates to the same
validator the standalone CLI uses, so cert + CLI never diverge.
"""
from __future__ import annotations

import hashlib
import logging
import sys
from datetime import date
from pathlib import Path

# Path bootstrap — allow `python -m research.phase0_certify` from sub-project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from validation import validator as V  # noqa: E402

log = logging.getLogger("prediction.phase0_certify")


def compute_design_hash(design_path: Path) -> str:
    """SHA-256 of PREDICTION_MARKETS_DESIGN.md (streamed)."""
    if not design_path.exists():
        return "ERROR_DESIGN_DOC_MISSING"
    h = hashlib.sha256()
    with open(design_path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def certify_status(results: list[V.CheckResult]) -> str:
    n_fail = sum(1 for r in results if r.status == V.Status.FAIL.value)
    n_pass = sum(1 for r in results if r.status == V.Status.PASS.value)
    if n_fail == 0 and n_pass == len(results) and len(results) > 0:
        return "CERTIFIED"
    if n_fail > 0:
        return "FAILED"
    return "INCOMPLETE"


def generate_report(data_root: Path, design_path: Path, output_path: Path) -> str:
    log.info("Running Phase 0 certification checks...")
    design_hash = compute_design_hash(design_path)

    df = V.load_resolved(data_root)
    results = V.run_all_checks(df)
    status = certify_status(results)

    n_pass = sum(1 for r in results if r.status == V.Status.PASS.value)
    n_fail = sum(1 for r in results if r.status == V.Status.FAIL.value)
    n_skip = sum(1 for r in results if r.status == V.Status.SKIP.value)

    lines = [
        f"# Phase 0 Certification: {status}",
        "",
        f"**Substrate:** #10 — Kalshi favorite-longshot bias",
        f"**Date:** {date.today().isoformat()}",
        f"**Design Document SHA-256:** `{design_hash}`",
        "",
        "The Phase 1 / Phase 2 orchestrators recompute this SHA at runtime (via "
        "`afgauntlet.PreRegistration`) and refuse to execute on mismatch (§15).",
        "",
        "## Phase 0 Exit Gates (§2)",
        "",
        "| Gate | Status | Summary |",
        "|------|--------|---------|",
    ]
    for r in results:
        lines.append(f"| {r.name} | {V._icon(r.status)} | {r.summary} |")

    cov = next((r for r in results if r.name == "coverage"), None)
    if cov and cov.metrics.get("by_category"):
        lines += ["", "## Category coverage", "", "| Category | Resolved contracts |", "|---|---|"]
        for cat, cnt in cov.metrics["by_category"].items():
            lines.append(f"| {cat} | {cnt} |")

    lines += [
        "",
        "## Summary",
        f"- PASS: {n_pass}",
        f"- FAIL: {n_fail}",
        f"- SKIP: {n_skip}",
        "",
        f"**Verdict: {status}.**",
    ]
    if status != "CERTIFIED":
        lines.append(
            "\n_Not yet CERTIFIED — run the downloader (`python -m ingest.downloader`) "
            "to populate `data/processed/resolved/` and re-run this script._"
        )

    report = "\n".join(lines) + "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report)
    log.info("Report written to %s. Status: %s", output_path, status)
    return status


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    base_dir = Path(__file__).resolve().parent.parent
    data_root = base_dir / "data"
    design_path = base_dir / "research" / "PREDICTION_MARKETS_DESIGN.md"
    output_path = base_dir / "research" / "PREDICTION_PHASE0_CERTIFIED.md"
    status = generate_report(data_root, design_path, output_path)
    # Exit 0 always (cert is a report); the validator CLI is the gating one.
    return 0 if status in {"CERTIFIED", "INCOMPLETE"} else 1


if __name__ == "__main__":
    sys.exit(main())
