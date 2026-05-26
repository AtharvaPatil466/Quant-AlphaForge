"""Phase 0 certification orchestrator for alphaforge-vix.

Runs all checks per `VIX_DESIGN.md` §2 (post §17 ADDENDUM), computes the
design-doc SHA-256 anchor, and writes `research/VIX_PHASE0_CERTIFIED.md`.

Usage:
    python -m research.phase0_certify
    python -m research.phase0_certify --data-root data --out research/VIX_PHASE0_CERTIFIED.md

Exit code 0 if certified (no blocking FAILs), 1 otherwise.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path

import pandas as pd

# Path bootstrap — allow `python -m research.phase0_certify` from sub-project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest import cboe as CBOE             # noqa: E402
from ingest import realized_vol as RV       # noqa: E402
from ingest import validator as V           # noqa: E402
from ingest import yfinance_loader as YF    # noqa: E402

log = logging.getLogger("vix.research.phase0_certify")


def compute_design_hash(design_path: Path) -> str:
    if not design_path.exists():
        return "ERROR_DESIGN_DOC_MISSING"
    h = hashlib.sha256()
    with open(design_path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def load_all_inputs(data_root: Path) -> V.ValidatorInputs:
    """Load every data product that the validator can consume. Missing
    products propagate as None; the validator handles them gracefully."""
    inputs = V.ValidatorInputs()

    # CBOE term-structure panel.
    try:
        inputs.cboe_panel = CBOE.build_term_structure_panel(data_root)
        log.info("loaded CBOE panel: %d dates × %d columns",
                 len(inputs.cboe_panel.index), len(inputs.cboe_panel.columns))
    except FileNotFoundError as e:
        log.warning("CBOE panel missing: %s", e)

    # SPY + realized-vol panel.
    try:
        spy_raw = YF.load_ticker("SPY", data_root)
        spy_close = spy_raw["close"] if "close" in spy_raw.columns else spy_raw.iloc[:, 0]
        inputs.spy_panel = RV.build_spy_panel(spy_close)
        log.info("loaded SPY panel: %d rows", len(inputs.spy_panel))
    except FileNotFoundError as e:
        log.warning("SPY missing: %s", e)

    # SVXY (with regime).
    try:
        inputs.svxy_df = YF.load_ticker("SVXY", data_root)
        log.info("loaded SVXY: %d rows", len(inputs.svxy_df))
    except FileNotFoundError as e:
        log.warning("SVXY missing: %s", e)

    # VXX.
    try:
        inputs.vxx_df = YF.load_ticker("VXX", data_root)
        log.info("loaded VXX: %d rows", len(inputs.vxx_df))
    except FileNotFoundError as e:
        log.warning("VXX missing: %s", e)

    # ^VIX from yfinance (for cross-check).
    try:
        yf_vix = YF.load_ticker("^VIX", data_root)
        inputs.yf_vix_close = yf_vix["close"] if "close" in yf_vix.columns else yf_vix.iloc[:, 0]
        log.info("loaded ^VIX (yf): %d rows", len(inputs.yf_vix_close))
    except FileNotFoundError as e:
        log.warning("^VIX (yf) missing: %s", e)

    return inputs


def certify(
    data_root: Path,
    design_path: Path,
    out_md: Path,
    out_json: Path | None = None,
) -> tuple[bool, dict[str, V.CheckResult]]:
    """Run cert end-to-end. Returns (certified, results)."""
    design_sha = compute_design_hash(design_path)
    log.info("VIX_DESIGN.md SHA-256: %s", design_sha)

    inputs = load_all_inputs(data_root)
    results = V.run_phase0_validators(inputs)

    blocking = sum(1 for r in results.values() if r.status == V.Status.FAIL.value)
    certified = (blocking == 0)

    # Write markdown.
    md = V.render_markdown_report(results, design_doc_sha=design_sha)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(md)
    log.info("wrote %s", out_md)

    # Optionally write structured JSON.
    if out_json:
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps({
            "design_doc_sha": design_sha,
            "certified": certified,
            "results": {k: asdict(r) for k, r in results.items()},
        }, indent=2, default=str))
        log.info("wrote %s", out_json)

    return certified, results


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Phase 0 certification for alphaforge-vix.")
    p.add_argument("--data-root", type=Path, default=Path("data"))
    p.add_argument("--design-doc", type=Path,
                   default=Path("research/VIX_DESIGN.md"))
    p.add_argument("--out", type=Path,
                   default=Path("research/VIX_PHASE0_CERTIFIED.md"))
    p.add_argument("--out-json", type=Path,
                   default=Path("research/vix_phase0_certified.json"))
    p.add_argument("-v", "--verbose", action="count", default=0)
    args = p.parse_args(argv)

    logging.basicConfig(
        level=max(logging.WARNING - 10 * args.verbose, logging.DEBUG),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    certified, results = certify(
        args.data_root, args.design_doc, args.out, args.out_json,
    )

    blocking = sum(1 for r in results.values() if r.status == V.Status.FAIL.value)
    n_pass = sum(1 for r in results.values() if r.status == V.Status.PASS.value)
    n_warn = sum(1 for r in results.values() if r.status == V.Status.WARN.value)
    n_skip = sum(1 for r in results.values() if r.status == V.Status.SKIP.value)

    print()
    print(f"PASS={n_pass}  WARN={n_warn}  FAIL={blocking}  SKIP={n_skip}")
    print(f"Status: {'CERTIFIED' if certified else 'NOT CERTIFIED'}")
    return 0 if certified else 1


if __name__ == "__main__":
    sys.exit(main())
