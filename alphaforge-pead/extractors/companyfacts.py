"""EDGAR Company Facts EPS extractor.

Implements the four engineering pre-commitments from
`research/PEAD_DESIGN.md` §2:

  2.1 Restatements (as-of-date discipline) — preserve every (filed, val)
      tuple so `value_as_of(ticker, period_end, as_of_ts)` returns the
      latest filed-on-or-before timestamp.
  2.2 Fiscal period alignment — key by (cik, fy, fp). Event time =
      `filed` from the 10-Q / 10-K row.
  2.3 EPS concept hierarchy — primary
      `us-gaap:IncomeLossFromContinuingOperationsPerDilutedShare`,
      fallback `us-gaap:EarningsPerShareDiluted`, then drop. Never Basic.
  2.4 Eligibility window — keep rows with `period_end >= 2012-01-01`.
      Per-firm 8-quarter minimum is enforced downstream by the universe
      intersection report, not here.

Source endpoint:
    https://data.sec.gov/api/xbrl/companyfacts/CIK{nnnnnnnnnn}.json

The SEC requires a User-Agent identifying the requester (name + contact)
and caps requests at 10/sec. We reuse the User-Agent already established
by the PIT-universe scraper.

Output schema (one row per (cik, period_end, filed) tuple):

    cik, ticker, period_end, fp, fy, filed, form, concept, val,
    start_date, end_date, substitution_level

`substitution_level` is `1` when the primary concept was used, `2` for
the fallback. Step-2 substitutions also append a line to the global
substitution log at `data/edgar_eps/_substitution_log.jsonl`.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import pyarrow as pa
import pyarrow.parquet as pq
import requests


log = logging.getLogger(__name__)


# --- constants --------------------------------------------------------------


COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
DEFAULT_USER_AGENT = "AlphaForge-PEAD/0.1 (atharvapatil466@gmail.com)"

PRIMARY_CONCEPT = "IncomeLossFromContinuingOperationsPerDilutedShare"
FALLBACK_CONCEPT = "EarningsPerShareDiluted"
BANNED_CONCEPT = "EarningsPerShareBasic"  # contract violation if used

UNITS_KEY = "USD/shares"
SUBSTRATE_START = date(2012, 1, 1)

VALID_FP = {"Q1", "Q2", "Q3", "FY"}


# Period-kind classification (PEAD_DESIGN.md §2.2 addendum, 2026-05-17).
# Tolerance ranges account for irregular fiscal calendars (53-week years,
# day-of-week boundaries) and integer rounding of (end-start).days.
_QUARTERLY_RANGE = (85, 95)    # ~13 weeks
_YTD_Q2_RANGE = (175, 190)     # ~26 weeks
_YTD_Q3_RANGE = (265, 280)     # ~39 weeks
_ANNUAL_RANGE = (355, 380)     # ~52 weeks (incl. 53-week years)


def _classify_period(duration_days: int) -> str:
    if _QUARTERLY_RANGE[0] <= duration_days <= _QUARTERLY_RANGE[1]:
        return "quarterly"
    if _YTD_Q2_RANGE[0] <= duration_days <= _YTD_Q2_RANGE[1]:
        return "ytd_q2"
    if _YTD_Q3_RANGE[0] <= duration_days <= _YTD_Q3_RANGE[1]:
        return "ytd_q3"
    if _ANNUAL_RANGE[0] <= duration_days <= _ANNUAL_RANGE[1]:
        return "annual"
    return "other"


# --- types ------------------------------------------------------------------


@dataclass(slots=True)
class EpsRow:
    cik: int
    ticker: str
    period_end: date
    fp: str          # FROM FILING — see PEAD_DESIGN.md §2.2 addendum (2026-05-17). Audit/reporting only; NOT a join key.
    fy: int          # FROM FILING — same caveat.
    filed: datetime
    form: str
    concept: str
    val: float
    start_date: date
    end_date: date
    substitution_level: int  # 1 or 2
    period_duration_days: int  # (end_date - start_date).days; derived 2026-05-17
    period_kind: str  # "quarterly" / "annual" / "ytd_q2" / "ytd_q3" / "other"; derived 2026-05-17


# --- helpers ----------------------------------------------------------------


def _pad_cik(cik: int | str) -> str:
    return f"{int(cik):010d}"


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def _parse_filed(s: str) -> datetime:
    # SEC publishes `filed` as a YYYY-MM-DD string. We anchor at UTC midnight.
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


# --- fetching ---------------------------------------------------------------


def fetch_company_facts(
    cik: int | str,
    session: Optional[requests.Session] = None,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout: int = 30,
) -> Optional[dict]:
    """Fetch the Company Facts JSON for one CIK.

    Returns `None` on 404 (the API returns 404 for CIKs with no XBRL
    history — common for very small or de-registered companies). Raises
    on other HTTP errors.
    """
    s = session or requests.Session()
    url = COMPANY_FACTS_URL.format(cik=_pad_cik(cik))
    r = s.get(url, headers={"User-Agent": user_agent, "Accept": "application/json"}, timeout=timeout)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


# --- parsing ----------------------------------------------------------------


class ContractViolation(Exception):
    """Raised when the parser would do something the PEAD design contract bans."""


def _extract_units_payload(facts_json: dict, concept: str) -> Optional[list[dict]]:
    """Return the USD/shares time series for one us-gaap concept, or None
    if the concept (or its USD/shares unit) is not reported."""
    try:
        return facts_json["facts"]["us-gaap"][concept]["units"][UNITS_KEY]
    except KeyError:
        return None


def parse_company_facts(
    facts_json: dict,
    ticker: str,
    substrate_start: date = SUBSTRATE_START,
) -> tuple[list[EpsRow], list[dict]]:
    """Parse one company's Facts JSON into EpsRow records and a list of
    step-2-substitution log entries.

    Contract enforcement:
      - Concept hierarchy: primary first; for any (fy, fp) that the
        primary doesn't cover, the fallback is consulted. Every fallback
        use produces a substitution log entry.
      - `BANNED_CONCEPT` (EarningsPerShareBasic) is checked for presence
        ONLY to guarantee we never accidentally read it; we never select
        from it. (Sanity check, not a hard error.)
      - Substrate window: drop rows with period_end < substrate_start.
      - Valid `fp` values are {Q1, Q2, Q3, FY}; anything else is dropped
        with a log line (CY / quarterly aggregates appear in the API
        and would corrupt the SUE alignment if not filtered).
    """
    if facts_json.get("facts", {}).get("us-gaap", {}).get(BANNED_CONCEPT) is not None:
        # Not an error — many companies report Basic as well as Diluted. We
        # just MUST NOT read it. Logging here documents that we saw it and
        # ignored it.
        log.debug("[%s] %s present and ignored per contract", ticker, BANNED_CONCEPT)

    cik = int(facts_json.get("cik", 0))

    primary_rows = _extract_units_payload(facts_json, PRIMARY_CONCEPT) or []
    fallback_rows = _extract_units_payload(facts_json, FALLBACK_CONCEPT) or []

    # Key by (fy, fp, filed) so a (fy, fp) restatement chain is preserved.
    # Within the chain, multiple `filed` timestamps are all retained.
    keyed_primary: dict[tuple, dict] = {}
    for r in primary_rows:
        key = (r.get("fy"), r.get("fp"), r.get("filed"))
        keyed_primary[key] = r

    out: list[EpsRow] = []
    substitution_log: list[dict] = []

    # Pass 1: emit every primary-concept row that passes the filters.
    primary_fy_fp_seen: set[tuple] = set()
    for r in primary_rows:
        row = _row_or_none(r, cik, ticker, PRIMARY_CONCEPT, substitution_level=1,
                           substrate_start=substrate_start)
        if row is not None:
            out.append(row)
            primary_fy_fp_seen.add((row.fy, row.fp))

    # Pass 2: for (fy, fp) tuples NOT covered by the primary, take the
    # fallback. We do not back-fill primary-covered tuples with the
    # fallback — the primary's restatement chain stands as-is.
    for r in fallback_rows:
        fy = r.get("fy")
        fp = r.get("fp")
        if (fy, fp) in primary_fy_fp_seen:
            continue
        row = _row_or_none(r, cik, ticker, FALLBACK_CONCEPT, substitution_level=2,
                           substrate_start=substrate_start)
        if row is not None:
            out.append(row)
            substitution_log.append({
                "cik": cik,
                "ticker": ticker,
                "fy": int(fy),
                "fp": fp,
                "filed": r.get("filed"),
                "reason": "primary concept absent for this fiscal period",
            })

    # Sort by (period_end, filed) for deterministic output.
    out.sort(key=lambda x: (x.period_end, x.filed))
    return out, substitution_log


def _row_or_none(
    raw: dict,
    cik: int,
    ticker: str,
    concept: str,
    substitution_level: int,
    substrate_start: date,
) -> Optional[EpsRow]:
    """Validate + convert one API row, or return None to drop it."""
    fp = raw.get("fp")
    fy = raw.get("fy")
    filed_str = raw.get("filed")
    form = raw.get("form")
    val = raw.get("val")
    start_str = raw.get("start")
    end_str = raw.get("end")

    if fp not in VALID_FP:
        return None
    if fy is None or filed_str is None or form is None or val is None or end_str is None:
        return None

    try:
        end_d = _parse_date(end_str)
        # Some API rows omit `start` (instantaneous concepts). EPS is a
        # duration concept, but be defensive — fall back to end if missing.
        start_d = _parse_date(start_str) if start_str else end_d
        filed_dt = _parse_filed(filed_str)
    except (ValueError, TypeError):
        return None

    if end_d < substrate_start:
        return None

    duration = (end_d - start_d).days
    kind = _classify_period(duration)

    return EpsRow(
        cik=cik,
        ticker=ticker,
        period_end=end_d,
        fp=fp,
        fy=int(fy),
        filed=filed_dt,
        form=str(form),
        concept=concept,
        val=float(val),
        start_date=start_d,
        end_date=end_d,
        substitution_level=substitution_level,
        period_duration_days=int(duration),
        period_kind=kind,
    )


# --- parquet I/O ------------------------------------------------------------


def _schema() -> pa.Schema:
    return pa.schema([
        pa.field("cik", pa.int64()),
        pa.field("ticker", pa.string()),
        pa.field("period_end", pa.date32()),
        pa.field("fp", pa.string()),
        pa.field("fy", pa.int32()),
        pa.field("filed", pa.timestamp("ns", tz="UTC")),
        pa.field("form", pa.string()),
        pa.field("concept", pa.string()),
        pa.field("val", pa.float64()),
        pa.field("start_date", pa.date32()),
        pa.field("end_date", pa.date32()),
        pa.field("substitution_level", pa.int8()),
        pa.field("period_duration_days", pa.int32()),
        pa.field("period_kind", pa.string()),
    ])


def write_cik_shard(rows: list[EpsRow], out_root: Path, cik: int) -> Path:
    """Write one CIK's rows to `out_root/by_cik/CIK{nnnnnnnnnn}.parquet`."""
    out_dir = out_root / "by_cik"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"CIK{_pad_cik(cik)}.parquet"
    table = pa.Table.from_pylist([
        {
            "cik": r.cik,
            "ticker": r.ticker,
            "period_end": r.period_end,
            "fp": r.fp,
            "fy": r.fy,
            "filed": r.filed,
            "form": r.form,
            "concept": r.concept,
            "val": r.val,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "substitution_level": r.substitution_level,
            "period_duration_days": r.period_duration_days,
            "period_kind": r.period_kind,
        }
        for r in rows
    ], schema=_schema())
    pq.write_table(table, path, compression="zstd")
    return path


def append_substitution_log(out_root: Path, entries: Iterable[dict]) -> None:
    p = out_root / "_substitution_log.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        for e in entries:
            f.write(json.dumps(e, default=str) + "\n")


# --- canonical accessor (value_as_of) ---------------------------------------


def value_as_of(
    shard_path: Path,
    ticker: str,
    period_end: date,
    as_of_ts: datetime,
    period_kind: Optional[str] = "quarterly",
) -> Optional[float]:
    """Return the EPS value for `(ticker, period_end)` known on `as_of_ts`,
    or None if no filing satisfies `filed <= as_of_ts`.

    **2026-05-17 (PEAD_DESIGN.md §2.2 addendum):** the SEC API may
    report multiple distinct values for the same (ticker, period_end)
    if it returns quarterly + annual + YTD-cumulative rows that share
    a period_end. By default this accessor filters to
    `period_kind == "quarterly"` — the canonical Phase 1 substrate.
    Pass `period_kind=None` to bypass (e.g., when querying annual values).

    This is the canonical accessor. Direct parquet indexing by
    `period_end` alone is a contract violation.
    """
    if not shard_path.exists():
        return None
    table = pq.read_table(shard_path)
    df = table.to_pandas()
    return value_as_of_frame(df, ticker, period_end, as_of_ts, period_kind)


def value_as_of_frame(
    df: "pd.DataFrame",
    ticker: str,
    period_end: date,
    as_of_ts: datetime,
    period_kind: Optional[str] = "quarterly",
) -> Optional[float]:
    """Frame-based sibling of :func:`value_as_of`.

    Performs the identical (ticker, period_end) + optional period_kind +
    ``filed <= as_of_ts`` selection against an already-loaded shard
    DataFrame, returning the latest-filed value. Selection semantics are
    bit-for-bit identical to ``value_as_of``; this overload exists so a
    caller iterating over many (period_end × as_of) pairs can load the
    parquet shard ONCE and reuse the in-memory frame instead of
    re-reading and re-deserializing the parquet on every lookup.
    """
    df = df[(df["ticker"] == ticker) & (df["period_end"] == period_end)]
    if period_kind is not None and "period_kind" in df.columns:
        df = df[df["period_kind"] == period_kind]
    df = df[df["filed"] <= as_of_ts]
    if df.empty:
        return None
    df = df.sort_values("filed")
    return float(df.iloc[-1]["val"])
