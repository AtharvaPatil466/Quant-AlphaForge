"""Tests for ingest.yfinance_loader."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from ingest import yfinance_loader as YF


# ---------------------------------------------------------------------------
# Fake yfinance fetcher
# ---------------------------------------------------------------------------

def _make_fake_history(start: str, n_days: int = 100, seed: int = 7) -> pd.DataFrame:
    """Build a yfinance-shaped DataFrame for tests."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start, periods=n_days, freq="B")
    close = 100 + rng.normal(0, 1, n_days).cumsum()
    df = pd.DataFrame({
        "Open": close - 0.1, "High": close + 0.5, "Low": close - 0.5,
        "Close": close, "Adj Close": close, "Volume": rng.integers(1e6, 1e7, n_days),
        "Dividends": 0.0, "Stock Splits": 0.0,
    }, index=dates)
    df.index.name = "Date"
    return df


def _fake_fetcher_for(start_map: dict[str, str], n_days: int = 100):
    """Build a fake `fetcher` that returns synthetic history per ticker."""
    def fetcher(ticker: str, period: str):
        if ticker in start_map:
            return _make_fake_history(start_map[ticker], n_days=n_days)
        return pd.DataFrame()
    return fetcher


# ---------------------------------------------------------------------------
# TICKERS registry
# ---------------------------------------------------------------------------

def test_tickers_registry_has_four_entries():
    assert set(YF.TICKERS.keys()) == {"SPY", "^VIX", "SVXY", "VXX"}


def test_tickers_have_expected_first_dates():
    assert YF.TICKERS["SPY"].expected_first_date == date(1993, 1, 29)
    assert YF.TICKERS["^VIX"].expected_first_date == date(1990, 1, 2)
    assert YF.TICKERS["SVXY"].expected_first_date == date(2011, 10, 4)
    # Per §17 ADDENDUM — VXX yfinance gap.
    assert YF.TICKERS["VXX"].expected_first_date == date(2018, 1, 25)


# ---------------------------------------------------------------------------
# output_path
# ---------------------------------------------------------------------------

def test_output_path_normalizes_caret_in_vix(tmp_path):
    p = YF.output_path(tmp_path, "^VIX")
    assert p == tmp_path / "etps" / "vix_yf.parquet"


def test_output_path_for_etps(tmp_path):
    assert YF.output_path(tmp_path, "SPY") == tmp_path / "etps" / "spy.parquet"
    assert YF.output_path(tmp_path, "SVXY") == tmp_path / "etps" / "svxy.parquet"
    assert YF.output_path(tmp_path, "VXX") == tmp_path / "etps" / "vxx.parquet"


# ---------------------------------------------------------------------------
# download_ticker
# ---------------------------------------------------------------------------

def test_download_ticker_writes_parquet_with_normalized_columns(tmp_path):
    fetcher = _fake_fetcher_for({"SPY": "1993-01-29"}, n_days=50)
    r = YF.download_ticker("SPY", tmp_path, fetcher=fetcher)
    assert r.ok
    assert r.rows == 50
    df = pd.read_parquet(r.path)
    # Column names normalized to lowercase + underscores.
    expected = {"open", "high", "low", "close", "adj_close", "volume",
                "dividends", "stock_splits"}
    assert expected.issubset(set(df.columns))


def test_download_ticker_unknown_returns_error(tmp_path):
    r = YF.download_ticker("FAKE", tmp_path, fetcher=lambda *a, **k: None)
    assert not r.ok
    assert r.error is not None
    assert "unknown" in r.error.lower()


def test_download_ticker_empty_history_returns_error(tmp_path):
    fetcher = lambda *a, **k: pd.DataFrame()  # noqa: E731
    r = YF.download_ticker("SPY", tmp_path, fetcher=fetcher)
    assert not r.ok
    assert "empty" in (r.error or "").lower()


def test_download_ticker_meets_expected_first_when_old_data(tmp_path):
    fetcher = _fake_fetcher_for({"SPY": "1993-01-29"}, n_days=50)
    r = YF.download_ticker("SPY", tmp_path, fetcher=fetcher)
    assert r.meets_expected_first


def test_download_ticker_fails_expected_first_when_new_data(tmp_path):
    """If yfinance only returns post-2020 data for SPY, meets_expected_first
    must be False — flags a data-source issue."""
    fetcher = _fake_fetcher_for({"SPY": "2020-01-02"}, n_days=50)
    r = YF.download_ticker("SPY", tmp_path, fetcher=fetcher)
    assert r.ok
    assert not r.meets_expected_first


def test_download_ticker_handles_yfinance_exception(tmp_path):
    def fetcher(ticker, period):
        raise ConnectionError("yfinance down")
    r = YF.download_ticker("SPY", tmp_path, fetcher=fetcher)
    assert not r.ok
    assert "ConnectionError" in (r.error or "")


# ---------------------------------------------------------------------------
# SVXY regime flag — the critical bit
# ---------------------------------------------------------------------------

def test_download_svxy_tags_regime_correctly(tmp_path):
    # SVXY launched 2011-10-04; restructured 2018-02-27.
    # Synthetic history straddles the boundary.
    rng = np.random.default_rng(1)
    dates = pd.date_range("2017-01-01", "2019-12-31", freq="B")
    close = 100 + rng.normal(0, 1, len(dates)).cumsum()
    fake_hist = pd.DataFrame({
        "Open": close, "High": close, "Low": close, "Close": close,
        "Adj Close": close, "Volume": 1_000_000,
        "Dividends": 0.0, "Stock Splits": 0.0,
    }, index=dates)
    fake_hist.index.name = "Date"

    fetcher = lambda ticker, period: fake_hist if ticker == "SVXY" else pd.DataFrame()  # noqa: E731
    r = YF.download_ticker("SVXY", tmp_path, fetcher=fetcher)
    assert r.ok

    df = pd.read_parquet(r.path)
    assert "regime" in df.columns
    pre = df[df.index < pd.Timestamp(YF.SVXY_RESTRUCTURING_DATE)]
    post = df[df.index >= pd.Timestamp(YF.SVXY_RESTRUCTURING_DATE)]
    assert (pre["regime"] == "pre_restructuring").all()
    assert (post["regime"] == "post_restructuring").all()


def test_download_non_svxy_has_no_regime_column(tmp_path):
    fetcher = _fake_fetcher_for({"SPY": "2010-01-04"})
    r = YF.download_ticker("SPY", tmp_path, fetcher=fetcher)
    df = pd.read_parquet(r.path)
    assert "regime" not in df.columns


# ---------------------------------------------------------------------------
# load_ticker — roundtrip
# ---------------------------------------------------------------------------

def test_load_ticker_roundtrips_index(tmp_path):
    fetcher = _fake_fetcher_for({"SPY": "2010-01-04"}, n_days=30)
    YF.download_ticker("SPY", tmp_path, fetcher=fetcher)
    df = YF.load_ticker("SPY", tmp_path)
    assert isinstance(df.index, pd.DatetimeIndex)
    assert len(df) == 30


def test_load_ticker_raises_when_not_downloaded(tmp_path):
    with pytest.raises(FileNotFoundError):
        YF.load_ticker("SPY", tmp_path)


# ---------------------------------------------------------------------------
# download_all
# ---------------------------------------------------------------------------

def test_download_all_iterates_every_ticker(tmp_path):
    fetcher = _fake_fetcher_for({k: "2015-01-02" for k in YF.TICKERS},
                                 n_days=10)
    results = YF.download_all(tmp_path, fetcher=fetcher)
    assert set(results.keys()) == set(YF.TICKERS.keys())
    assert all(r.ok for r in results.values())


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_main_rejects_unknown_ticker(tmp_path):
    rc = YF.main(["--output-root", str(tmp_path), "--tickers", "SPY,FAKE"])
    assert rc == 2


# ---------------------------------------------------------------------------
# Live smoke (network-dependent)
# ---------------------------------------------------------------------------

@pytest.mark.network
def test_live_smoke_SPY_full_history(tmp_path):
    r = YF.download_ticker("SPY", tmp_path)
    assert r.ok
    assert r.rows > 7000  # SPY launched 1993-01-29; ~33 years → 8000+ rows
    assert r.meets_expected_first


@pytest.mark.network
def test_live_smoke_VXX_post_2018_only(tmp_path):
    """Per §17 ADDENDUM — yfinance VXX starts 2018, not 2009."""
    r = YF.download_ticker("VXX", tmp_path)
    assert r.ok
    # First date should be in 2018, not 2009.
    assert r.first_date.year == 2018
