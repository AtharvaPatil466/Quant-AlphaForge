"""Tests for market calendar."""

from datetime import date

import pytest

from market_calendar import NYSE_HOLIDAYS, is_market_day


class TestMarketCalendar:
    def test_weekday_non_holiday(self):
        assert is_market_day(date(2025, 3, 3)) is True  # Monday

    def test_saturday(self):
        assert is_market_day(date(2025, 3, 1)) is False

    def test_sunday(self):
        assert is_market_day(date(2025, 3, 2)) is False

    def test_new_years_day(self):
        assert is_market_day(date(2025, 1, 1)) is False

    def test_christmas(self):
        assert is_market_day(date(2025, 12, 25)) is False

    def test_thanksgiving(self):
        assert is_market_day(date(2025, 11, 27)) is False

    def test_observed_holiday_2026_july4(self):
        # July 4, 2026 is Saturday → observed on Friday July 3
        assert is_market_day(date(2026, 7, 3)) is False

    def test_day_after_observed_holiday(self):
        # July 6, 2026 (Monday) should be a trading day
        assert is_market_day(date(2026, 7, 6)) is True

    def test_all_holidays_are_non_trading(self):
        for d in NYSE_HOLIDAYS:
            assert is_market_day(d) is False, f"{d} should not be a market day"
