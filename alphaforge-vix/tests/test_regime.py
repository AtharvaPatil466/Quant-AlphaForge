"""Unit tests for signals/regime.py."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from signals import regime


@pytest.fixture
def synthetic_vix():
    idx = pd.date_range("2010-01-04", periods=250, freq="B")
    # 50 days low (<15), 100 days normal (15-25), 60 days elevated (25-35),
    # 40 days crisis (>=35).
    values = (
        [10.0] * 50
        + [20.0] * 100
        + [30.0] * 60
        + [40.0] * 40
    )
    return pd.Series(values, index=idx)


def test_characterize_bucket_counts(synthetic_vix):
    report = regime.characterize(
        synthetic_vix,
        is_start=synthetic_vix.index.min(),
        is_end=synthetic_vix.index.max(),
    )
    assert report.n_days_total == 250
    by_name = {b.name: b for b in report.buckets}
    assert by_name["low_vol"].n_days == 50
    assert by_name["normal"].n_days == 100
    assert by_name["elevated"].n_days == 60
    assert by_name["crisis"].n_days == 40
    # Fractions sum to 1.
    assert sum(b.fraction for b in report.buckets) == pytest.approx(1.0)


def test_characterize_mean_vix_per_bucket(synthetic_vix):
    report = regime.characterize(
        synthetic_vix,
        is_start=synthetic_vix.index.min(),
        is_end=synthetic_vix.index.max(),
    )
    by_name = {b.name: b for b in report.buckets}
    assert by_name["low_vol"].mean_vix == 10.0
    assert by_name["normal"].mean_vix == 20.0
    assert by_name["elevated"].mean_vix == 30.0
    assert by_name["crisis"].mean_vix == 40.0


def test_characterize_handles_empty_window():
    idx = pd.date_range("2010-01-04", periods=5, freq="B")
    s = pd.Series([20.0] * 5, index=idx)
    out_of_range_start = pd.Timestamp("2020-01-01")
    out_of_range_end = pd.Timestamp("2020-12-31")
    r = regime.characterize(s, is_start=out_of_range_start, is_end=out_of_range_end)
    assert r.n_days_total == 0
    # All buckets reported with 0 days.
    assert {b.name for b in r.buckets} == {"low_vol", "normal", "elevated", "crisis"}


def test_to_dict_serializable(synthetic_vix):
    import json
    r = regime.characterize(
        synthetic_vix,
        is_start=synthetic_vix.index.min(),
        is_end=synthetic_vix.index.max(),
    )
    s = json.dumps(r.to_dict())
    assert "buckets" in s
    assert "per_year_fraction_crisis" in s


def test_bucket_definitions_cover_full_vix_range():
    # The four buckets must collectively cover [0, ∞).
    edges = [(b[1], b[2]) for b in regime.BUCKETS]
    # Each subsequent bucket starts where the prior ended.
    for i in range(1, len(edges)):
        assert edges[i][0] == edges[i - 1][1]
    assert edges[0][0] == 0.0
    assert edges[-1][1] == float("inf")
