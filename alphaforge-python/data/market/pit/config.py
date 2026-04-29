"""Tunable constants for PIT universe reconstruction.

Per PIT_UNIVERSE_DESIGN.md §5.2: byte-delta threshold is intentionally
configurable, not hardcoded in the filter logic. Adjust after running
the empirical-calibration pass and inspecting the byte-delta histogram.
"""

import re

# Wikipedia revision filter — minimum byte-size delta to consider a
# revision potentially membership-altering. Default 50 bytes corresponds
# roughly to one row insertion in the constituent table.
#
# Empirical calibration (session 2, 2,811 revisions 2010-2026):
#   - median byte_delta = 13 (typo fixes dominate)
#   - p90 = 413, p99 = 39,719 (heavy tail of major edits)
#   - TSLA addition (rev 995546256): 96 bytes (above 50 — caught)
#   - FB→META rename (rev 1092243288): 4 bytes (below 50 — MISSED by delta)
#   - 851 / 2,811 revisions (30.3%) survive at threshold = 50
#
# Conclusion: byte-delta alone misses pure-rename revisions because they
# only swap a few characters. We OR a comment-keyword filter (below) to
# catch those.
MIN_BYTE_DELTA = 50

# Edit-comment keyword filter — case-insensitive. Captures revisions
# whose byte-delta is too small to clear MIN_BYTE_DELTA but whose author
# explicitly described a membership change. Tuned against observed
# comments for ADD/REMOVE/RENAME/REPLACE events 2010-2026.
MEMBERSHIP_COMMENT_RE = re.compile(
    r'\b('
    r'replac\w*|'         # replaced, replaces, replacing
    r'added|adds|adding|'
    r'removed|removes|removing|'
    r'delisted|delist|'
    r'merger|merged|acquisition|acquired|'
    r'ticker\s*chg|ticker\s*change|'
    r'name\s*chg|name\s*change|renamed|rename|'
    r'effective\s+\d|'    # "effective 9-Jun-2022" pattern
    r'spinoff|spin[\-\s]off|spun\s*off'
    r')\b',
    re.IGNORECASE,
)
# Note: deliberately omitted "s&p 500" / "sp 500" — those keywords match
# MediaWiki's auto-generated section-edit comments like
# `/* S&P 500 component stocks */` and produced ~1,000 false positives in
# the session-2 calibration. The section header only indicates *what
# section was edited*, not that a membership change occurred.

# Wikipedia API
WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI_PAGE = "List of S&P 500 companies"

# SEC EDGAR
EDGAR_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

# Identify ourselves to both endpoints — required by Wikipedia and EDGAR ToS.
USER_AGENT = "AlphaForge-PIT-Universe/0.1 (atharvapatil466@gmail.com)"
