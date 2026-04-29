"""SEC EDGAR ticker → CIK lookup.

Source: https://www.sec.gov/files/company_tickers.json — the canonical
public mapping, refreshed nightly. We pull once per scrape run and
cache the result on disk.

The mapping returned by EDGAR keys current tickers, so this lookup is
authoritative for "today" but does NOT recover historical tickers that
have since been retired or renamed. For historical-ticker resolution
we rely on the in-table CIK (when present) plus a manual-override map
in later sessions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import requests

from .config import EDGAR_TICKERS_URL, USER_AGENT

# Cache the EDGAR file alongside our other artifacts so a scrape run
# is reproducible from a single directory.
_CACHE_PATH = Path(__file__).resolve().parent / "artifacts" / "edgar_company_tickers.json"


def fetch_edgar_tickers(force_refresh: bool = False) -> dict[str, str]:
    """Return a mapping ticker_uppercase -> zero-padded 10-digit CIK string.

    Caches the EDGAR file on disk; pass force_refresh=True to bypass.
    """
    if _CACHE_PATH.exists() and not force_refresh:
        raw = json.loads(_CACHE_PATH.read_text())
    else:
        resp = requests.get(
            EDGAR_TICKERS_URL,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        raw = resp.json()
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(json.dumps(raw))

    # The EDGAR file is shaped {"0": {"cik_str": 320193, "ticker": "AAPL", ...}, ...}
    out: dict[str, str] = {}
    for record in raw.values():
        ticker = str(record.get("ticker", "")).upper().strip()
        cik_int = record.get("cik_str")
        if not ticker or cik_int is None:
            continue
        out[ticker] = str(cik_int).zfill(10)
    return out


def lookup_cik(ticker: str, table: Optional[dict[str, str]] = None) -> Optional[str]:
    """Return the CIK for a ticker, or None if not found.

    Handles the EDGAR-vs-Wikipedia share-class punctuation drift:
    EDGAR uses `BRK-B` while Wikipedia and yfinance use `BRK.B`.
    Tries the input as-given, then a `.`<->`-` swap.

    Pass a pre-fetched `table` to avoid re-reading the cache for many lookups.
    """
    if not ticker:
        return None
    if table is None:
        table = fetch_edgar_tickers()
    key = ticker.upper().strip()
    if key in table:
        return table[key]
    # Share-class punctuation swap.
    if "." in key:
        alt = key.replace(".", "-")
        if alt in table:
            return table[alt]
    if "-" in key:
        alt = key.replace("-", ".")
        if alt in table:
            return table[alt]
    return None
