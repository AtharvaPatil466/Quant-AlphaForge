"""Tests for universe/pit.py — Nifty 500 PIT membership log.

Tests cover:
    1. Name resolution layers (manual override, ISINMaster, aggressive norm)
    2. Event log construction from real IndexInclExcl.xls
    3. membership_on_date() semantics
    4. Resolution coverage (must be 100%)
    5. Membership count sanity checks
"""
from __future__ import annotations

from datetime import date

import pytest

from universe.isin_master import ISINMaster
from universe.pit import (
    PITUniverse,
    _normalize_aggressive,
    _strip_suffixes,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def isin_master() -> ISINMaster:
    return ISINMaster(
        equity_l_path="../EQUITY_L.csv",
        symbolchange_path="../symbolchange.csv",
    )


@pytest.fixture(scope="module")
def pit(isin_master: ISINMaster) -> PITUniverse:
    return PITUniverse(
        xls_path="../IndexInclExcl.xls",
        isin_master=isin_master,
        nifty500_list_path="../ind_nifty500list.csv",
    )


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------

class TestStripSuffixes:
    def test_sus(self):
        result = _strip_suffixes("Larsen & Toubro Ltd.-Sus")
        assert "Larsen & Toubro" in result
        assert "Sus" not in result

    def test_delisted(self):
        result = _strip_suffixes("GKN Driveshafts Ltd. -Delisted")
        assert "GKN Driveshafts" in result
        assert "Delisted" not in result

    def test_merged(self):
        result = _strip_suffixes("Jindal Strips Ltd.- Merged")
        assert "Jindal Strips" in result
        assert "Merged" not in result

    def test_old_suffix(self):
        result = _strip_suffixes("Godrej Industries Ltd.-Old")
        assert "Godrej Industries" in result
        assert "Old" not in result

    def test_erstwhile(self):
        result = _strip_suffixes("Aptech Ltd. (Erstwhile)")
        assert "Aptech" in result
        assert "Erstwhile" not in result

    def test_no_suffix(self):
        result = _strip_suffixes("Reliance Industries Ltd.")
        assert "Reliance Industries" in result


class TestNormalizeAggressive:
    def test_basic(self):
        assert _normalize_aggressive("Tata Steel Ltd.") == "TATA STEEL LTD"

    def test_removes_india(self):
        assert _normalize_aggressive("Alfa Laval (India) Ltd.") == "ALFA LAVAL LTD"

    def test_replaces_ampersand(self):
        result = _normalize_aggressive("Bombay Dyeing & Manufacturing Co. Ltd.")
        assert "AND" in result

    def test_replaces_corporate_words(self):
        result = _normalize_aggressive("Deepak Fertilisers & Petrochemicals Corporation Ltd.")
        assert "CORP" in result
        assert "CORPORATION" not in result


# ---------------------------------------------------------------------------
# Name resolution tests
# ---------------------------------------------------------------------------

class TestNameResolution:
    """Verify that specific known companies resolve correctly."""

    def test_itc(self, pit: PITUniverse):
        assert pit.resolve_scrip_name("I T C Ltd.") == "ITC"

    def test_apollo_hospitals(self, pit: PITUniverse):
        assert pit.resolve_scrip_name("Apollo Hospitals Enterprises Ltd.") == "APOLLOHOSP"

    def test_satyam_to_techm(self, pit: PITUniverse):
        assert pit.resolve_scrip_name("Satyam Computer Services Ltd.") == "TECHM"

    def test_vedanta_rename(self, pit: PITUniverse):
        assert pit.resolve_scrip_name("Sesa Sterlite Ltd.") == "VEDL"

    def test_adani_gas_rename(self, pit: PITUniverse):
        assert pit.resolve_scrip_name("Adani Gas Ltd.") == "ATGL"

    def test_berger_paints(self, pit: PITUniverse):
        assert pit.resolve_scrip_name("Berger Paints India Ltd.") == "BERGEPAINT"

    def test_titan_rename(self, pit: PITUniverse):
        assert pit.resolve_scrip_name("Titan Industries Ltd.") == "TITAN"

    def test_cadila_to_zydus(self, pit: PITUniverse):
        assert pit.resolve_scrip_name("Cadila Healthcare Ltd.") == "ZYDUSLIFE"

    def test_mindtree_merge(self, pit: PITUniverse):
        assert pit.resolve_scrip_name("MindTree Ltd.") == "LTIM"

    def test_carrier_trailing_space(self, pit: PITUniverse):
        """Trailing space in XLS should still resolve."""
        assert pit.resolve_scrip_name("Carrier Aircon Ltd. ") == "CARRIER"

    def test_escorts(self, pit: PITUniverse):
        assert pit.resolve_scrip_name("Escorts Ltd.") == "ESCORTS"

    def test_pvr_inox_merge(self, pit: PITUniverse):
        assert pit.resolve_scrip_name("PVR Ltd.") == "PVRINOX"

    def test_niit_tech_to_coforge(self, pit: PITUniverse):
        assert pit.resolve_scrip_name("NIIT Technologies Ltd.") == "COFORGE"

    def test_karnataka_bank(self, pit: PITUniverse):
        assert pit.resolve_scrip_name("Karnataka Bank Ltd.") == "KTKBANK"

    def test_welspun(self, pit: PITUniverse):
        assert pit.resolve_scrip_name("Welspun India Ltd.") == "WELSPUNLIV"


# ---------------------------------------------------------------------------
# Coverage gate — must be 100%
# ---------------------------------------------------------------------------

class TestResolutionCoverage:
    def test_full_coverage(self, pit: PITUniverse):
        """§2.1 requires complete resolution for the PIT log to be valid."""
        r = pit.resolution_report
        assert r.coverage == 1.0, (
            f"Coverage {r.coverage:.1%}, unresolved: {r.unresolved_names[:10]}"
        )

    def test_no_unresolved(self, pit: PITUniverse):
        assert pit.resolution_report.unresolved == 0

    def test_total_events(self, pit: PITUniverse):
        """IndexInclExcl.xls Nifty 500 sheet has 2495 rows."""
        assert len(pit.events) == 2495


# ---------------------------------------------------------------------------
# Event log structure
# ---------------------------------------------------------------------------

class TestEventLog:
    def test_events_sorted_chronologically(self, pit: PITUniverse):
        dates = [e.date for e in pit.events]
        assert dates == sorted(dates)

    def test_first_event_is_1998_08_01(self, pit: PITUniverse):
        assert pit.events[0].date == date(1998, 8, 1)

    def test_last_event_is_2020(self, pit: PITUniverse):
        assert pit.events[-1].date.year == 2020

    def test_all_actions_are_add_or_remove(self, pit: PITUniverse):
        for e in pit.events:
            assert e.action in ("ADD", "REMOVE")

    def test_event_log_df_shape(self, pit: PITUniverse):
        df = pit.event_log_df()
        assert len(df) == 2495
        assert set(df.columns) == {"date", "symbol", "action", "scrip_name"}


# ---------------------------------------------------------------------------
# membership_on_date() semantics
# ---------------------------------------------------------------------------

class TestMembershipOnDate:
    def test_initial_composition_close_to_500(self, pit: PITUniverse):
        """First event batch is ~500 inclusions on 1998-08-01."""
        members = pit.membership_on_date(date(1998, 8, 1))
        # Should be close to 500 (some names may map to same symbol)
        assert 480 <= len(members) <= 500

    def test_membership_within_expected_range(self, pit: PITUniverse):
        """Nifty 500 membership count should be between 400-500 at any
        point in the dataset — the index targets 500 constituents."""
        for d in [date(2005, 1, 1), date(2010, 6, 15),
                  date(2015, 3, 1), date(2019, 12, 31)]:
            members = pit.membership_on_date(d)
            assert 400 <= len(members) <= 510, (
                f"Members on {d}: {len(members)} — outside expected range"
            )

    def test_add_then_remove_removes_member(self, pit: PITUniverse):
        """Find a symbol that was added then removed and verify it's gone."""
        # ABG Shipyard was added and later removed
        sym = "ABGSHIP"
        events_for_sym = [e for e in pit.events if e.symbol == sym]
        if len(events_for_sym) >= 2:
            add_date = events_for_sym[0].date
            remove_date = events_for_sym[-1].date
            if events_for_sym[-1].action == "REMOVE":
                from datetime import timedelta
                assert sym in pit.membership_on_date(
                    add_date + timedelta(days=1)
                )
                assert sym not in pit.membership_on_date(
                    remove_date + timedelta(days=1)
                )

    def test_ever_members_superset_of_any_date(self, pit: PITUniverse):
        """ever_members() must be a superset of membership at any date."""
        ever = pit.ever_members()
        for d in [date(2005, 1, 1), date(2015, 1, 1)]:
            members = pit.membership_on_date(d)
            assert members.issubset(ever)

    def test_ever_members_count(self, pit: PITUniverse):
        """Should be substantially more than 500 (many companies rotated)."""
        assert len(pit.ever_members()) > 800


# ---------------------------------------------------------------------------
# Spot-check specific membership events
# ---------------------------------------------------------------------------

class TestSpotChecks:
    """Hand-verified membership events from known NSE index circulars."""

    def test_reliance_always_member(self, pit: PITUniverse):
        """Reliance Industries has been in Nifty 500 continuously."""
        for d in [date(2005, 1, 1), date(2010, 1, 1), date(2020, 1, 1)]:
            members = pit.membership_on_date(d)
            assert "RELIANCE" in members, f"RELIANCE not in members on {d}"

    def test_tcs_present_in_later_years(self, pit: PITUniverse):
        """TCS listed in 2004, should be in Nifty 500 from mid-2000s."""
        members_2010 = pit.membership_on_date(date(2010, 1, 1))
        assert "TCS" in members_2010

    def test_itc_in_index(self, pit: PITUniverse):
        """ITC has been in Nifty 500 since inception."""
        members = pit.membership_on_date(date(1999, 1, 1))
        assert "ITC" in members
