"""Static sector-map builder for the PIT S&P 500 substrate.

Phase 4's sector-neutral variant needs sector labels for the full
ever-member universe, not just the legacy 50-name manifest. The Phase 1
artifacts already contain the raw ingredients:
  - baseline parquet with 2010 sectors for the initial 500 names
  - cached Wikipedia snapshot wikitext for later revisions

This module turns those into a repo-local ticker -> sector map and
caches the result back into `artifacts/`.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd


ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"
DEFAULT_CACHE_PATH = ARTIFACTS_DIR / "_sector_map.json"
DEFAULT_BASELINE_PATH = ARTIFACTS_DIR / "_baseline_2010-01-10.parquet"
DEFAULT_SNAPSHOTS_DIR = ARTIFACTS_DIR / "snapshots"


def _normalize_sector(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "none":
        return None
    return text


def _read_cached_sector_map(path: Path) -> dict[str, str] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text())
    return {
        str(ticker).upper(): str(sector)
        for ticker, sector in payload.get("sector_map", {}).items()
    }


def load_pit_sector_map(
    *,
    cache_path: str | Path | None = None,
    baseline_path: str | Path | None = None,
    snapshots_dir: str | Path | None = None,
    refresh: bool = False,
) -> dict[str, str]:
    """Load or build a static sector map for the PIT universe."""
    cache_file = Path(cache_path) if cache_path else DEFAULT_CACHE_PATH
    if not refresh:
        cached = _read_cached_sector_map(cache_file)
        if cached:
            return cached

    baseline_file = Path(baseline_path) if baseline_path else DEFAULT_BASELINE_PATH
    snapshots_root = Path(snapshots_dir) if snapshots_dir else DEFAULT_SNAPSHOTS_DIR

    baseline = pd.read_parquet(baseline_file)
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in baseline.itertuples(index=False):
        sector = _normalize_sector(getattr(row, "gics_sector", None))
        ticker = str(getattr(row, "ticker")).upper()
        if sector:
            counts[ticker][sector] += 1

    # Lazy import so codepaths that don't need parser machinery don't
    # require the optional parse dependencies.
    from .parser import parse_constituent_table

    for snap_path in sorted(snapshots_root.glob("*.json")):
        try:
            payload = json.loads(snap_path.read_text())
            df = parse_constituent_table(payload["wikitext"])
        except Exception:
            continue
        if "ticker" not in df.columns or "gics_sector" not in df.columns:
            continue
        for row in df.itertuples(index=False):
            sector = _normalize_sector(getattr(row, "gics_sector", None))
            ticker = str(getattr(row, "ticker")).upper()
            if sector and ticker:
                counts[ticker][sector] += 1

    sector_map = {
        ticker: counter.most_common(1)[0][0]
        for ticker, counter in counts.items()
        if counter
    }
    cache_file.write_text(json.dumps({"sector_map": sector_map}, indent=2) + "\n")
    return sector_map
