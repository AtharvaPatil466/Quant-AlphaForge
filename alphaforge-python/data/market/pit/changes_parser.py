"""Parse Wikipedia's "Selected changes to the list of S&P 500 components"
table — a separately-curated change log on the same page.

Identifier: id="changes" (modern era). The table format is:
    Effective Date | Added Ticker | Added Security | Removed Ticker | Removed Security | Reason

Per the article's editor comment, this table excludes pure ticker
renames and company-name changes — only true index changes appear here.
That makes it a useful semi-independent cross-check against our
snapshot-diff event log: every row here should have both an ADD and a
REMOVE on the matching effective_date in our log.

Public surface: parse_changes_table(wikitext) -> pd.DataFrame
columns: effective_date, added_ticker, added_security,
         removed_ticker, removed_security, reason
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

import mwparserfromhell as mwp
import pandas as pd

from .parser import (
    _find_table_block, _split_cells, _split_rows, _strip_inline_markup,
    _clean_cell, _CAPTION_RE,
)

# Direct identifier for the modern changes table.
_CHANGES_ID_RE = re.compile(
    r'\{\|[^\n]*id\s*=\s*"changes"[^\n]*',
    re.IGNORECASE,
)


def _extract_changes_table(wikitext: str) -> str:
    """Locate and return the changes-table wikitext block."""
    m = _CHANGES_ID_RE.search(wikitext)
    if m is None:
        # Fallback: find the section heading and grab the next wikitable.
        sec = re.search(
            r'==[^=]*[Ss]elected changes[^=]*==', wikitext,
        )
        if sec is None:
            raise ValueError("changes table not found")
        # Walk forward until the next `{|`.
        start_search = sec.end()
        m_next = re.search(r'\{\|', wikitext[start_search:])
        if m_next is None:
            raise ValueError("no wikitable after Selected changes heading")
        s, e = _find_table_block(wikitext, start_search + m_next.start())
        return wikitext[s:e]
    s, e = _find_table_block(wikitext, m.start())
    return wikitext[s:e]


_DATE_FORMATS = [
    "%B %d, %Y",     # April 9, 2026
    "%b %d, %Y",     # Apr 9, 2026
    "%B %d %Y",      # April 9 2026
    "%Y-%m-%d",      # 2026-04-09
    "%d %B %Y",      # 9 April 2026
    "%d %b %Y",      # 9 Apr 2026
]


def _parse_date(text: str) -> Optional[str]:
    """Parse a date cell into ISO YYYY-MM-DD, or return None."""
    if not text:
        return None
    txt = text.strip().replace(" ", " ")
    # Some rows have annotations; take the first ~30 chars.
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(txt[:30].strip(), fmt).date().isoformat()
        except ValueError:
            continue
    # Strip trailing footnote markers like "April 9, 2026 [a]" or "[1]"
    cleaned = re.sub(r'\s*\[[^\]]+\]\s*$', '', txt).strip()
    if cleaned != txt:
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(cleaned, fmt).date().isoformat()
            except ValueError:
                continue
    return None


def _extract_ticker_text(cell_wikitext: str) -> Optional[str]:
    """Extract a ticker from a changes-table cell (often plain text or
    `{{NyseSymbol|TICKER}}` etc.)."""
    if not cell_wikitext:
        return None
    code = mwp.parse(cell_wikitext)
    for tmpl in code.filter_templates():
        name = str(tmpl.name).strip().lower()
        if name in {"nysesymbol", "nasdaqsymbol", "batsymbol", "amexsymbol"} and tmpl.params:
            return str(tmpl.params[0].value).strip().upper()
    text = code.strip_code(normalize=True, collapse=True).strip()
    # Bare alphanumeric ticker, possibly with . or -
    m = re.match(r'^([A-Z][A-Z0-9.\-]{0,9})$', text.upper())
    if m:
        return m.group(1)
    if text:
        return text.upper().strip() or None
    return None


def parse_changes_table(wikitext: str) -> pd.DataFrame:
    """Parse the Selected-changes table into a DataFrame."""
    block = _extract_changes_table(wikitext)
    rows = _split_rows(block)
    if len(rows) < 3:
        raise ValueError(f"too few rows in changes table: {len(rows)}")

    # The header spans two physical rows (rowspan/colspan). Skip both.
    # Data rows start at index 2.
    records: list[dict] = []
    for raw_row in rows[2:]:
        cells = _split_cells(raw_row)
        if len(cells) < 5:
            continue
        # Expected order: Effective Date | Added Ticker | Added Security
        #                 | Removed Ticker | Removed Security | Reason
        eff_date_text = _clean_cell(cells[0])
        eff_date = _parse_date(eff_date_text)
        if eff_date is None:
            # Some rows might span multiple effective dates or be malformed
            continue
        records.append({
            "effective_date": eff_date,
            "effective_date_text": eff_date_text,
            "added_ticker": _extract_ticker_text(cells[1]),
            "added_security": _clean_cell(cells[2]) if len(cells) > 2 else None,
            "removed_ticker": _extract_ticker_text(cells[3]) if len(cells) > 3 else None,
            "removed_security": _clean_cell(cells[4]) if len(cells) > 4 else None,
            "reason": _clean_cell(cells[5])[:300] if len(cells) > 5 else None,
        })

    df = pd.DataFrame.from_records(records)
    return df
