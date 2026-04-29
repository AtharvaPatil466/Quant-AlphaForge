"""Spot-check fixture for the point-in-time S&P 500 universe.

Per PIT_UNIVERSE_DESIGN.md §7.3 — these tests encode named historical
events that the event log MUST capture correctly. They are a precondition
for the Siblis cross-check (§7.1) and the SPX TR reconciliation (§7.2):
a parser that fails any of these is producing garbage even if the
aggregate counts look right.

The fixture is small by design — every event is hand-verified against
public S&P announcements and is non-controversial.

Run:
    .venv/bin/python -m pytest tests/test_pit_universe_fixture.py -v
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest


EVENT_LOG = (
    Path(__file__).resolve().parent.parent
    / "data" / "market" / "pit" / "artifacts" / "_event_log.parquet"
)


@pytest.fixture(scope="module")
def events() -> pd.DataFrame:
    if not EVENT_LOG.exists():
        pytest.skip(
            f"event log not yet built ({EVENT_LOG.name}); "
            "run `python -m data.market.pit.session3_build_events` first"
        )
    return pd.read_parquet(EVENT_LOG)


def _find(events: pd.DataFrame, ticker: str, action: str,
          d_start: str, d_end: str) -> pd.DataFrame:
    return events[
        (events["ticker"] == ticker)
        & (events["action"] == action)
        & (events["effective_date"] >= d_start)
        & (events["effective_date"] <= d_end)
    ]


# ── Headline named events ────────────────────────────────────────────


def test_tesla_added_dec_2020(events):
    """Tesla joined the S&P 500 effective 2020-12-21, replacing AIV."""
    rows = _find(events, "TSLA", "ADD", "2020-12-21", "2020-12-22")
    assert len(rows) == 1, f"expected exactly one TSLA ADD event, got {len(rows)}"
    row = rows.iloc[0]
    assert row["cik"] == "0001318605", f"TSLA CIK mismatch: {row['cik']}"
    assert row["source_revision_id"] == "995546256", \
        f"unexpected source revision for TSLA add: {row['source_revision_id']}"


def test_facebook_renamed_to_meta_jun_2022(events):
    """FB → META rename effective 2022-06-09. CIK 0001326801 must be
    preserved across the rename — that's the entire point of CIK-based
    identity resolution. If this fails as ADD+REMOVE instead, the
    differ's RENAME path is broken."""
    rows = _find(events, "META", "RENAME", "2022-06-08", "2022-06-12")
    assert len(rows) == 1, f"expected one META RENAME event, got {len(rows)}"
    row = rows.iloc[0]
    assert row["counterparty_ticker"] == "FB", \
        f"counterparty should be FB, got {row['counterparty_ticker']}"
    assert row["cik"] == "0001326801", f"META CIK mismatch: {row['cik']}"
    # And the ADD/REMOVE pair should NOT exist.
    assert _find(events, "META", "ADD", "2022-06-08", "2022-06-12").empty, \
        "META should not have an ADD event during rename window"
    assert _find(events, "FB", "REMOVE", "2022-06-08", "2022-06-12").empty, \
        "FB should not have a REMOVE event during rename window"


def test_twitter_delisted_oct_2022(events):
    """Twitter was acquired by Musk and delisted late October 2022."""
    rows = _find(events, "TWTR", "REMOVE", "2022-10-29", "2022-11-05")
    assert len(rows) >= 1, f"missing TWTR REMOVE event"


def test_ge_healthcare_spinoff_jan_2023(events):
    """GE HealthCare was spun off from GE and joined the S&P 500 on
    2023-01-04. Critically: GEHC has its own CIK (0001932393), distinct
    from GE's (0000040545). Without CIK-distinct identity this would be
    misclassified as a RENAME of GE."""
    rows = _find(events, "GEHC", "ADD", "2023-01-03", "2023-01-06")
    assert len(rows) == 1, f"expected one GEHC ADD event, got {len(rows)}"
    assert rows.iloc[0]["cik"] == "0001932393", \
        f"GEHC CIK mismatch: {rows.iloc[0]['cik']}"


def test_ge_vernova_spinoff_apr_2024(events):
    """GE Vernova spun off and joined the S&P 500 on 2024-04-02."""
    rows = _find(events, "GEV", "ADD", "2024-04-01", "2024-04-05")
    assert len(rows) == 1, f"expected one GEV ADD event, got {len(rows)}"
    assert rows.iloc[0]["cik"] == "0001996810", \
        f"GEV CIK mismatch: {rows.iloc[0]['cik']}"


def test_ge_itself_was_never_removed(events):
    """GE (CIK 0000040545, now 'GE Aerospace') was NOT removed — it
    spun off subsidiaries but stayed in the index. Earlier versions of
    this fixture mistakenly asserted a 2018 GE removal (GE was demoted
    from the *Dow* in June 2018, not the S&P 500)."""
    removes = events[
        (events["ticker"] == "GE")
        & (events["action"] == "REMOVE")
    ]
    assert removes.empty, (
        f"GE should not have any REMOVE events in the log, found {len(removes)}: "
        f"{removes[['effective_date', 'cik']].to_dict('records')}"
    )


def test_symantec_renamed_to_nlok_nov_2019(events):
    """SYMC → NLOK rename when Symantec sold its enterprise security
    business and rebranded. CIK 0000849399 should be preserved."""
    rows = _find(events, "NLOK", "RENAME", "2019-11-04", "2019-11-15")
    assert len(rows) == 1, f"expected one NLOK RENAME, got {len(rows)}"
    row = rows.iloc[0]
    assert row["counterparty_ticker"] == "SYMC"
    assert row["cik"] == "0000849399"


def test_nlok_renamed_to_gen_nov_2022(events):
    """NLOK → GEN rename when NortonLifeLock merged with Avast to form
    Gen Digital. Same CIK 0000849399 as the prior SYMC→NLOK rename, so
    we have a TWO-STEP rename chain on the same CIK across 3 years."""
    rows = _find(events, "GEN", "RENAME", "2022-11-08", "2022-11-15")
    assert len(rows) == 1, f"expected one GEN RENAME, got {len(rows)}"
    row = rows.iloc[0]
    assert row["counterparty_ticker"] == "NLOK"
    assert row["cik"] == "0000849399"


# ── Aggregate sanity ─────────────────────────────────────────────────


def test_event_log_size_in_expected_range(events):
    """The S&P 500 sees roughly 25-50 changes per year. Over 16 years
    that's 400-800 ADD+REMOVE pairs (~800-1600 events) plus a handful of
    renames. We expect 600-1200 events total. Materially outside that
    range = parser fragility regression OR differ over/under-counting."""
    n = len(events)
    assert 600 <= n <= 1200, f"event log size {n} outside expected [600, 1200] band"


def test_add_remove_balance(events):
    """Every ADD should have a matching REMOVE somewhere in the timeline
    (the index size is stable at ~500). The difference should be small —
    within ~20% of either count. Wildly imbalanced counts mean the parser
    is producing garbage one direction or the other."""
    n_add = (events["action"] == "ADD").sum()
    n_rem = (events["action"] == "REMOVE").sum()
    assert n_add > 0 and n_rem > 0
    ratio = max(n_add, n_rem) / min(n_add, n_rem)
    assert ratio <= 1.30, (
        f"ADD/REMOVE imbalance: ADD={n_add}, REMOVE={n_rem}, "
        f"ratio={ratio:.2f} (expected ≤ 1.30)"
    )


def test_rename_events_have_counterparty(events):
    """Every RENAME must have a non-null counterparty_ticker (the OLD
    ticker)."""
    renames = events[events["action"] == "RENAME"]
    if renames.empty:
        return
    null_cp = renames["counterparty_ticker"].isna().sum()
    assert null_cp == 0, f"{null_cp} RENAME events lack counterparty_ticker"


def test_all_events_have_source_provenance(events):
    """Every event must have non-null source and source_revision_id —
    the §11 provenance discipline."""
    null_src = events["source"].isna().sum()
    null_rev = events["source_revision_id"].isna().sum()
    assert null_src == 0, f"{null_src} events lack source"
    assert null_rev == 0, f"{null_rev} events lack source_revision_id"
