"""Unit tests for ISINMaster.

Verifies name matching, forward/backward rename tracing, and ISIN lookup.
"""
from __future__ import annotations

from datetime import date
import pytest

from universe.isin_master import ISINMaster


@pytest.fixture(scope="module")
def isin_master() -> ISINMaster:
    """Load the real ISINMaster for testing."""
    return ISINMaster(
        equity_l_path="../EQUITY_L.csv",
        symbolchange_path="../symbolchange.csv"
    )


def test_isin_master_initialization(isin_master: ISINMaster) -> None:
    """Check that lists were populated from real files."""
    assert len(isin_master.symbol_to_isin) > 1000
    assert len(isin_master.forward_renames) > 800


def test_isin_master_normalize_name(isin_master: ISINMaster) -> None:
    """Verify name normalization rules."""
    norm = isin_master._normalize_name("3M India Limited")
    assert norm == "3M INDIA LTD"
    
    norm2 = isin_master._normalize_name("3M India Ltd.")
    assert norm2 == "3M INDIA LTD"
    
    norm3 = isin_master._normalize_name("  CADILA HEALTHCARE   ltd.  ")
    assert norm3 == "CADILA HEALTHCARE LTD"


def test_single_step_rename(isin_master: ISINMaster) -> None:
    """Verify single-step rename CADILAHC -> ZYDUSLIFE on 2022-03-07."""
    rename_date = date(2022, 3, 7)
    
    # Before change
    assert isin_master.get_active_symbol("CADILAHC", date(2022, 3, 6)) == "CADILAHC"
    # On/After change
    assert isin_master.get_active_symbol("CADILAHC", date(2022, 3, 7)) == "ZYDUSLIFE"
    assert isin_master.get_active_symbol("CADILAHC", date(2025, 1, 1)) == "ZYDUSLIFE"

    # Tracing backward
    assert isin_master.get_active_symbol("ZYDUSLIFE", date(2022, 3, 6)) == "CADILAHC"
    assert isin_master.get_active_symbol("ZYDUSLIFE", date(2022, 3, 7)) == "ZYDUSLIFE"


def test_multi_step_rename(isin_master: ISINMaster) -> None:
    """Verify multi-step rename SCANDENT -> CAMBRIDGE (2006-07-17) -> XCHANGING (2012-06-25)."""
    # SCANDENT era
    assert isin_master.get_active_symbol("SCANDENT", date(2005, 1, 1)) == "SCANDENT"
    assert isin_master.get_active_symbol("CAMBRIDGE", date(2005, 1, 1)) == "SCANDENT"
    assert isin_master.get_active_symbol("XCHANGING", date(2005, 1, 1)) == "SCANDENT"
    
    # CAMBRIDGE era
    assert isin_master.get_active_symbol("SCANDENT", date(2010, 1, 1)) == "CAMBRIDGE"
    assert isin_master.get_active_symbol("CAMBRIDGE", date(2010, 1, 1)) == "CAMBRIDGE"
    assert isin_master.get_active_symbol("XCHANGING", date(2010, 1, 1)) == "CAMBRIDGE"
    
    # XCHANGING era
    assert isin_master.get_active_symbol("SCANDENT", date(2015, 1, 1)) == "XCHANGING"
    assert isin_master.get_active_symbol("CAMBRIDGE", date(2015, 1, 1)) == "XCHANGING"
    assert isin_master.get_active_symbol("XCHANGING", date(2015, 1, 1)) == "XCHANGING"


def test_long_chain_rename(isin_master: ISINMaster) -> None:
    """Verify five-symbol rename chain for Yaari Digital:

    IBWSL -> SORILHOLD (2017-04-18) -> IBULISL (2008-06-08) -> YAARII (2020-12-08) -> YAARI (2021-12-15).
    """
    # Before first change
    assert isin_master.get_active_symbol("IBWSL", date(2016, 1, 1)) == "IBWSL"
    
    # In SORILHOLD era
    assert isin_master.get_active_symbol("IBWSL", date(2017, 5, 1)) == "SORILHOLD"
    
    # In IBULISL era
    assert isin_master.get_active_symbol("IBWSL", date(2019, 1, 1)) == "IBULISL"
    
    # In YAARII era
    assert isin_master.get_active_symbol("IBWSL", date(2021, 1, 1)) == "YAARII"
    
    # In YAARI era
    assert isin_master.get_active_symbol("IBWSL", date(2022, 1, 1)) == "YAARI"
    
    # Query YAARI in the past
    assert isin_master.get_active_symbol("YAARI", date(2016, 1, 1)) == "IBWSL"


def test_isin_resolution(isin_master: ISINMaster) -> None:
    """Verify ISIN lookup for current and old symbols."""
    # Current symbol in EQUITY_L
    assert isin_master.get_isin("3MINDIA") == "INE470A01017"
    
    # Old symbol should resolve to the current symbol's ISIN
    assert isin_master.get_isin("BIRLA3M") == "INE470A01017"
    
    # Another old symbol ZEUSTRUST or similar
    assert isin_master.get_isin("CADILAHC") == "INE010B01027"  # Zydus Lifesciences
    
    # Non-existent symbol
    assert isin_master.get_isin("NONEXISTENT") is None
