"""
Correlation module tests — matrix symmetry, IC bounds, turnover validity.
"""

import pytest
import numpy as np

from correlation import (
    compute_correlation_matrix,
    compute_ic,
    compute_turnover,
    compute_correlation_result,
)
from data.synthetic import generate_dataset
from factors.registry import JS_FACTOR_NAMES


@pytest.fixture
def tech_dataset():
    return generate_dataset("Technology", 252, 42)


class TestCorrelationMatrix:
    def test_shape(self, tech_dataset):
        matrix = compute_correlation_matrix(tech_dataset, 252)
        n = len(JS_FACTOR_NAMES)
        assert len(matrix) == n
        assert all(len(row) == n for row in matrix)

    def test_diagonal_is_one(self, tech_dataset):
        matrix = compute_correlation_matrix(tech_dataset, 252)
        for i in range(len(JS_FACTOR_NAMES)):
            assert matrix[i][i] == pytest.approx(1.0)

    def test_symmetric(self, tech_dataset):
        matrix = compute_correlation_matrix(tech_dataset, 252)
        n = len(matrix)
        for i in range(n):
            for j in range(n):
                assert matrix[i][j] == pytest.approx(matrix[j][i], abs=1e-10)

    def test_bounded(self, tech_dataset):
        matrix = compute_correlation_matrix(tech_dataset, 252)
        for row in matrix:
            for val in row:
                assert -1.0 <= val <= 1.0


class TestIC:
    def test_length(self, tech_dataset):
        ic = compute_ic(tech_dataset, 252)
        assert len(ic) == len(JS_FACTOR_NAMES)

    def test_bounded(self, tech_dataset):
        ic = compute_ic(tech_dataset, 252)
        for val in ic:
            assert -1.0 <= val <= 1.0

    def test_finite(self, tech_dataset):
        ic = compute_ic(tech_dataset, 252)
        for val in ic:
            assert np.isfinite(val)


class TestTurnover:
    def test_length(self, tech_dataset):
        turnover = compute_turnover(tech_dataset, 252)
        assert len(turnover) == len(JS_FACTOR_NAMES)

    def test_range(self, tech_dataset):
        """Turnover values should be in [0.15, 0.70] per JS logic."""
        turnover = compute_turnover(tech_dataset, 252)
        for val in turnover:
            assert 0.1 <= val <= 0.8  # generous bounds

    def test_deterministic(self, tech_dataset):
        t1 = compute_turnover(tech_dataset, 252)
        t2 = compute_turnover(tech_dataset, 252)
        assert t1 == t2


class TestCorrelationResult:
    def test_full_result(self):
        result = compute_correlation_result("Technology", 252)
        assert len(result.matrix) == len(JS_FACTOR_NAMES)
        assert len(result.ic) == len(JS_FACTOR_NAMES)
        assert len(result.turnover) == len(JS_FACTOR_NAMES)
        assert result.factors == list(JS_FACTOR_NAMES)
