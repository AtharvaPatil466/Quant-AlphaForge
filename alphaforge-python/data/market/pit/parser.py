"""Parse the S&P 500 constituent table from a Wikipedia revision's wikitext.

Public surface: parse_constituent_table(wikitext) -> pd.DataFrame
with columns: ticker, company_name, gics_sector, gics_sub_industry,
              headquarters, date_added_text, cik, founded_text.

The parser handles the post-2014 Wikipedia table format where the
constituent table is identified by id="constituents". Earlier eras of
the article use slightly different layouts and will need format-era
detection in a later session — out of scope for session 1.
"""

from __future__ import annotations

import re
from typing import Optional

import mwparserfromhell as mwp
import pandas as pd

# The constituents table has been identified three different ways across
# format eras. We try them in order:
#   1. Modern (post-~2018): id="constituents" attribute on the {| line
#   2. 2010-2017 era: caption `|+ S&P 500 component stocks` (or similar)
#   3. Last-resort: any wikitable with a Ticker/Symbol header row near the top
_TABLE_ID_RE = re.compile(
    r'\{\|[^\n]*id\s*=\s*"constituents"[^\n]*',
    re.IGNORECASE,
)
_CAPTION_RE = re.compile(
    r'\|\+\s*S\s*&\s*amp;?\s*P\s*500\s*[Cc]omponent', re.IGNORECASE,
)
_TICKER_HEADER_RE = re.compile(
    r'!\s*\[\[Ticker\s+symbol\]\]|!\s*Symbol\b|!\s*Ticker\b',
    re.IGNORECASE,
)


def _find_table_block(wikitext: str, start_pos: int) -> tuple[int, int]:
    """Given a position inside or just before a `{|`, find the bounds of the
    enclosing wikitext table. Returns (open_index, close_index)."""
    # Walk back to the nearest `{|` at or before start_pos.
    open_idx = wikitext.rfind("{|", 0, start_pos + 2)
    if open_idx < 0:
        # No `{|` at/before — start_pos *is* the open if wikitext[start_pos:] begins with {|
        if wikitext.startswith("{|", start_pos):
            open_idx = start_pos
        else:
            raise ValueError("table open marker not found")
    depth = 1
    i = open_idx + 2
    while i < len(wikitext):
        if wikitext.startswith("{|", i):
            depth += 1
            i += 2
        elif wikitext.startswith("|}", i):
            depth -= 1
            i += 2
            if depth == 0:
                return open_idx, i
        else:
            i += 1
    raise ValueError("constituents table not properly closed")


_CONSTITUENT_HEADER_TOKENS = {
    # canonical constituents-table columns
    "symbol", "ticker", "ticker symbol", "security", "company",
    "gics sector", "sec filing", "sec filings", "central index key",
    "cik", "headquarters", "headquarters location", "date first added",
    "date added", "founded",
}
_CHANGES_HEADER_TOKENS = {
    # tokens that strongly indicate the "Recent changes" table
    "added", "removed", "reason",
}


def _score_table_header(block: str) -> int:
    """Score a wikitext table block by how many constituent-column header
    tokens its header row matches. Returns a positive integer score; 0
    means "doesn't look like the constituents table". Penalizes tables
    that look like the changes table."""
    rows = _split_rows(block)
    if not rows:
        return 0
    header_cells = [_clean_cell(c).lower().rstrip(":").strip() for c in _split_cells(rows[0])]
    constituent_hits = sum(1 for h in header_cells if h in _CONSTITUENT_HEADER_TOKENS)
    changes_hits = sum(1 for h in header_cells if h in _CHANGES_HEADER_TOKENS)
    # Penalize changes-table heavily: any 2+ "Added/Removed/Reason" hits
    # disqualify regardless of incidental constituent-token matches.
    if changes_hits >= 2:
        return 0
    return constituent_hits


def _extract_constituents_table(wikitext: str) -> str:
    """Slice out the constituents table block. Header-content scoring
    handles the three format eras (id="constituents" / caption / no
    identifier) without ambiguity against the Recent Changes table."""
    # Direct match: id="constituents" — definitive when present.
    m = _TABLE_ID_RE.search(wikitext)
    if m is not None:
        s, e = _find_table_block(wikitext, m.start())
        return wikitext[s:e]

    # Direct match: caption "S&P 500 component...".
    m = _CAPTION_RE.search(wikitext)
    if m is not None:
        s, e = _find_table_block(wikitext, m.start())
        return wikitext[s:e]

    # Header-content scoring across all wikitables.
    best_score = 0
    best_block: str | None = None
    for tbl_match in re.finditer(r'\{\|[^\n]*', wikitext):
        try:
            s, e = _find_table_block(wikitext, tbl_match.start())
        except ValueError:
            continue
        block = wikitext[s:e]
        if block.count("\n|-") < 100:
            continue  # too small to be the 500-row constituents table
        score = _score_table_header(block)
        if score > best_score:
            best_score = score
            best_block = block

    if best_block is not None and best_score >= 3:
        return best_block

    raise ValueError(
        f"constituents table not found in wikitext "
        f"(best fallback score: {best_score})"
    )


_REF_RE = re.compile(r'<ref\b[^>]*>.*?</ref>', re.IGNORECASE | re.DOTALL)
_REF_SELFCLOSE_RE = re.compile(r'<ref\b[^>]*/>', re.IGNORECASE)
_HTML_COMMENT_RE = re.compile(r'<!--.*?-->', re.DOTALL)


def _strip_inline_markup(s: str) -> str:
    """Remove `<ref>...</ref>`, `<ref ... />`, and `<!-- -->` blocks.

    Their contents can contain newlines and lines starting with `|`,
    which would otherwise be mis-parsed as cell separators and shift
    every column. This was the source of the 2022-11-15 vandalism
    catastrophe (998 phantom REMOVE events from one rolled-back edit
    that briefly replaced the article with an older 4-column format
    whose caption contained a multi-line ref tag).
    """
    s = _REF_RE.sub('', s)
    s = _REF_SELFCLOSE_RE.sub('', s)
    s = _HTML_COMMENT_RE.sub('', s)
    return s


def _split_rows(table_block: str) -> list[str]:
    """Split a wikitext table into rows on `|-` separators."""
    # Strip ref/comment blocks first — see _strip_inline_markup.
    table_block = _strip_inline_markup(table_block)
    # Drop the table header line and the closing `|}`
    lines = table_block.splitlines()
    body_lines = lines[1:-1]
    body = "\n".join(body_lines)
    # Rows are separated by lines that are exactly `|-` (possibly with
    # attribute markup after, e.g. `|- style="..."`).
    rows = re.split(r'(?m)^\|-[^\n]*$', body)
    # Drop empty/whitespace rows.
    return [r.strip() for r in rows if r.strip()]


def _split_cells(row_block: str) -> list[str]:
    """Split a row's wikitext into cells.

    Wikitext cell separators are `||` (inline) or a new line beginning
    with `|`. Header cells use `!` / `!!` instead — handled too.

    Lines starting with `|+` are table CAPTIONS, not cells. They must be
    skipped — failing to do so adds a phantom "+ caption text" cell at
    position 0 of the header row, shifting every column by one and
    silently producing garbage data (this was the 2011-era catastrophe).
    """
    # Normalize inline separators onto their own lines so we can split
    # uniformly.
    normalized = row_block.replace("||", "\n|").replace("!!", "\n!")
    cells: list[str] = []
    for line in normalized.splitlines():
        line = line.strip()
        if not line:
            continue
        # Skip table-caption lines — they're not cells.
        if line.startswith("|+"):
            continue
        if line.startswith("|") or line.startswith("!"):
            # Strip the leading marker and any cell-attribute prefix
            # (e.g. `| style="..." | actual content`).
            content = line[1:].lstrip()
            if "|" in content and content.split("|", 1)[0].strip().endswith('"'):
                # has attribute prefix
                content = content.split("|", 1)[1].lstrip()
            cells.append(content)
        else:
            # Continuation line of the previous cell.
            if cells:
                cells[-1] = cells[-1] + " " + line
    return cells


def _clean_cell(cell_wikitext: str) -> str:
    """Strip wikitext markup from a cell, returning clean text."""
    if not cell_wikitext:
        return ""
    code = mwp.parse(cell_wikitext)
    return code.strip_code(normalize=True, collapse=True).strip()


# Templates that wrap a ticker symbol. The first positional argument is
# the ticker. Format-era drift gives us several variants.
_TICKER_TEMPLATES = {
    "nysesymbol", "nasdaqsymbol", "batsymbol", "amexsymbol",
    "nyse", "nasdaq", "bats", "amex",  # bare exchange-name templates
}


def _extract_ticker(symbol_cell_wikitext: str) -> Optional[str]:
    """Extract the ticker from the Symbol cell.

    The cell typically contains a template like `{{NyseSymbol|TSLA}}`,
    but some eras use raw text or wikilinks. Try templates first; fall
    back to clean text.
    """
    if not symbol_cell_wikitext:
        return None
    code = mwp.parse(symbol_cell_wikitext)
    for tmpl in code.filter_templates():
        name = str(tmpl.name).strip().lower()
        if name in _TICKER_TEMPLATES and tmpl.params:
            return str(tmpl.params[0].value).strip().upper()
    text = code.strip_code(normalize=True, collapse=True).strip()
    # Some cells are just the bare ticker.
    m = re.match(r'^([A-Z][A-Z0-9.\-]{0,9})$', text)
    if m:
        return m.group(1)
    return text.upper() or None


def _normalize_cik(raw: str) -> Optional[str]:
    """CIKs in the table are zero-padded 10-digit strings. Normalize."""
    if not raw:
        return None
    digits = re.sub(r'\D', '', raw)
    if not digits:
        return None
    return digits.zfill(10)


# Header normalization — map column-header text variants to canonical
# field names. Eras differ in capitalization and punctuation.
_HEADER_MAP = {
    "symbol": "ticker",
    "ticker": "ticker",
    "ticker symbol": "ticker",
    "security": "company_name",
    "company": "company_name",
    "sec filings": "_sec_filings",  # discarded
    "gics sector": "gics_sector",
    "gics sub-industry": "gics_sub_industry",
    "gics sub industry": "gics_sub_industry",
    "headquarters location": "headquarters",
    "headquarters": "headquarters",
    "date first added": "date_added_text",
    "date added": "date_added_text",
    "added": "date_added_text",
    "central index key": "cik",
    "cik": "cik",
    "founded": "founded_text",
    "year founded": "founded_text",
}


def parse_constituent_table(wikitext: str) -> pd.DataFrame:
    """Parse a Wikipedia revision's wikitext into a constituents DataFrame.

    Columns (always present, may be NaN):
        ticker, company_name, gics_sector, gics_sub_industry,
        headquarters, date_added_text, cik, founded_text
    """
    table = _extract_constituents_table(wikitext)
    raw_rows = _split_rows(table)
    if not raw_rows:
        raise ValueError("no rows extracted from constituents table")

    # First row is the header.
    header_cells = [
        _clean_cell(c).lower().rstrip(":").strip()
        for c in _split_cells(raw_rows[0])
    ]
    field_names: list[str] = []
    for h in header_cells:
        canon = _HEADER_MAP.get(h)
        if canon is None:
            # Unknown column — keep position but discard at output stage.
            field_names.append(f"_unknown_{h}")
        else:
            field_names.append(canon)

    records: list[dict] = []
    for raw_row in raw_rows[1:]:
        cells = _split_cells(raw_row)
        if len(cells) < 2:
            continue
        record: dict[str, Optional[str]] = {}
        for fname, cell in zip(field_names, cells):
            if fname.startswith("_"):
                continue
            if fname == "ticker":
                record["ticker"] = _extract_ticker(cell)
            elif fname == "cik":
                record["cik"] = _normalize_cik(_clean_cell(cell))
            else:
                record[fname] = _clean_cell(cell)
        if record.get("ticker"):
            records.append(record)

    df = pd.DataFrame.from_records(records)

    # Ensure canonical column set is present even if some are missing.
    canonical = [
        "ticker", "company_name", "gics_sector", "gics_sub_industry",
        "headquarters", "date_added_text", "cik", "founded_text",
    ]
    for col in canonical:
        if col not in df.columns:
            df[col] = pd.NA
    df = df[canonical]

    # Normalize ticker casing one more time as a safety net.
    df["ticker"] = df["ticker"].astype("string").str.upper().str.strip()

    # Sanity gate: the S&P 500 has had 498-510 distinct ticker rows
    # throughout the 2010-2026 window. Anything materially smaller is
    # almost certainly a parser misfire (wrong table matched, mid-edit
    # vandalism, or format-era bug). Fail loudly rather than emit
    # phantom REMOVE events from the differ.
    if len(df) < 400:
        raise ValueError(
            f"parsed only {len(df)} constituent rows — below sanity "
            f"floor of 400. Likely parser misfire on this revision."
        )

    return df
