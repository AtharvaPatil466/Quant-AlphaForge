"""
Scanner tests — output shape, signal classification, and sorting.
"""

import pytest

from scanner.scanner import scan_universe, SignalRow


class TestScanner:
    def test_default_scan(self):
        results = scan_universe()
        assert len(results) > 0
        assert all(isinstance(r, SignalRow) for r in results)

    def test_sorted_by_composite(self):
        results = scan_universe(sector="Technology", lookback=252)
        composites = [r.composite for r in results]
        assert composites == sorted(composites, reverse=True)

    def test_signal_values(self):
        results = scan_universe(sector="Technology", lookback=252)
        for r in results:
            assert r.signal in ("LONG", "SHORT", "NEUTRAL")

    def test_factor_scores_present(self):
        results = scan_universe(sector="Technology", lookback=252)
        for r in results:
            assert "Momentum (12-1)" in r.factor_scores
            assert "Mean Reversion (5d)" in r.factor_scores

    def test_composite_range(self):
        results = scan_universe(sector="All", lookback=252)
        for r in results:
            assert -100 <= r.composite <= 100

    def test_empty_sector(self):
        results = scan_universe(sector="Bogus", lookback=252)
        assert len(results) == 0

    def test_deterministic(self):
        r1 = scan_universe(sector="Technology", lookback=252)
        r2 = scan_universe(sector="Technology", lookback=252)
        assert [r.composite for r in r1] == [r.composite for r in r2]

    def test_min_score_filter(self):
        all_results = scan_universe(sector="Technology", lookback=252)
        filtered = scan_universe(sector="Technology", lookback=252, min_score=10.0)
        assert len(filtered) <= len(all_results)
        for r in filtered:
            assert abs(r.composite) >= 10.0

    def test_signal_filter(self):
        results = scan_universe(sector="All", lookback=252, signal_filter="LONG")
        for r in results:
            assert r.signal == "LONG"
