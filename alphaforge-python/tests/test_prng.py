"""
PRNG parity tests — assert Python mulberry32 matches JS output exactly.

The expected values below are from the implementation plan Section 8.
When these match, all downstream data generation is trustworthy.
"""

import pytest
from data.prng import Mulberry32, hash_string, normal_random


# ── Reference values from JS mulberry32(42) ──────────────────────────────────
# Plan Section 8: first 5 calls
JS_PRNG_SEED42_EXPECTED = [
    0.6011037519201636,
    0.4482905589975417,
    0.8524657934904099,
    0.6697340414393693,
    0.1748138987459242,
]


class TestMulberry32:
    def test_first_five_values_seed_42(self):
        """Parity: first 5 values from mulberry32(42) must match JS exactly."""
        rng = Mulberry32(42)
        for i, expected in enumerate(JS_PRNG_SEED42_EXPECTED):
            actual = rng()
            assert actual == pytest.approx(expected, abs=1e-15), (
                f"Call {i+1}: expected {expected}, got {actual}"
            )

    def test_deterministic(self):
        """Same seed produces identical sequence."""
        rng1 = Mulberry32(42)
        rng2 = Mulberry32(42)
        for _ in range(100):
            assert rng1() == rng2()

    def test_different_seeds_differ(self):
        """Different seeds produce different sequences."""
        rng1 = Mulberry32(42)
        rng2 = Mulberry32(99)
        values1 = [rng1() for _ in range(10)]
        values2 = [rng2() for _ in range(10)]
        assert values1 != values2

    def test_output_range(self):
        """All outputs must be in [0, 1)."""
        rng = Mulberry32(42)
        for _ in range(10000):
            v = rng()
            assert 0.0 <= v < 1.0

    def test_1000_values_no_nan(self):
        """No NaN or Inf in 1000 consecutive calls."""
        rng = Mulberry32(42)
        for _ in range(1000):
            v = rng()
            assert v == v  # NaN check
            assert abs(v) < float("inf")


class TestHashString:
    def test_known_tickers(self):
        """hash_string must be deterministic and non-negative."""
        for ticker in ["AAPL", "MSFT", "NVDA", "GOOGL"]:
            h = hash_string(ticker)
            assert h >= 0
            # Same input, same output
            assert hash_string(ticker) == h

    def test_different_strings_differ(self):
        assert hash_string("AAPL") != hash_string("MSFT")

    def test_empty_string(self):
        assert hash_string("") == 0


class TestNormalRandom:
    def test_deterministic(self):
        """Same seed produces identical normal random sequence."""
        rng1 = Mulberry32(42)
        rng2 = Mulberry32(42)
        for _ in range(100):
            assert normal_random(rng1) == normal_random(rng2)

    def test_distribution_sanity(self):
        """Mean near 0, stddev near 1 for large sample."""
        rng = Mulberry32(42)
        values = [normal_random(rng) for _ in range(10000)]
        m = sum(values) / len(values)
        var = sum((v - m) ** 2 for v in values) / len(values)
        assert abs(m) < 0.05, f"Mean too far from 0: {m}"
        assert abs(var - 1.0) < 0.1, f"Variance too far from 1: {var}"
