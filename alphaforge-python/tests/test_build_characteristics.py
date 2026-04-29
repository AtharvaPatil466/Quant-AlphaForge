"""Tests for Phase 3 SEC characteristics builder."""

from __future__ import annotations

import pandas as pd
import pytest

from research import build_characteristics as bc


def _companyfacts_fixture() -> dict:
    return {
        "facts": {
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "units": {
                        "shares": [
                            {"form": "10-Q", "end": "2018-09-29", "filed": "2018-11-05", "val": 8.0},
                            {"form": "10-K", "end": "2018-12-31", "filed": "2019-03-15", "val": 8.0},
                            {"form": "10-Q", "end": "2019-06-29", "filed": "2019-08-01", "val": 9.0},
                            {"form": "10-Q", "end": "2019-12-28", "filed": "2020-01-31", "val": 10.0},
                            {"form": "10-K", "end": "2019-12-31", "filed": "2020-03-15", "val": 10.0},
                            {"form": "10-K/A", "end": "2019-12-31", "filed": "2020-04-15", "val": 11.0},
                        ]
                    }
                }
            },
            "us-gaap": {
                "StockholdersEquity": {
                    "units": {
                        "USD": [
                            {"form": "10-K", "end": "2018-12-31", "filed": "2019-03-15", "val": 80.0},
                            {"form": "10-K", "end": "2019-12-31", "filed": "2020-03-15", "val": 100.0},
                            {"form": "10-K/A", "end": "2019-12-31", "filed": "2020-04-15", "val": 120.0},
                        ]
                    }
                },
                "DeferredTaxAssetsLiabilitiesNet": {
                    "units": {
                        "USD": [
                            {"form": "10-K", "end": "2018-12-31", "filed": "2019-03-15", "val": 8.0},
                            {"form": "10-K/A", "end": "2019-12-31", "filed": "2020-04-15", "val": 10.0},
                        ]
                    }
                },
                "PreferredStockValue": {
                    "units": {
                        "USD": [
                            {"form": "10-K", "end": "2018-12-31", "filed": "2019-03-15", "val": 4.0},
                            {"form": "10-K/A", "end": "2019-12-31", "filed": "2020-04-15", "val": 6.0},
                        ]
                    }
                },
                "Assets": {
                    "units": {
                        "USD": [
                            {"form": "10-K", "end": "2018-12-31", "filed": "2019-03-15", "val": 160.0},
                            {"form": "10-K", "end": "2019-12-31", "filed": "2020-03-15", "val": 200.0},
                            {"form": "10-K/A", "end": "2019-12-31", "filed": "2020-04-15", "val": 220.0},
                        ]
                    }
                },
                "Revenues": {
                    "units": {
                        "USD": [
                            {"form": "10-K", "end": "2018-12-31", "filed": "2019-03-15", "val": 100.0},
                            {"form": "10-K/A", "end": "2019-12-31", "filed": "2020-04-15", "val": 140.0},
                        ]
                    }
                },
                "CostOfGoodsSold": {
                    "units": {
                        "USD": [
                            {"form": "10-K", "end": "2018-12-31", "filed": "2019-03-15", "val": 50.0},
                            {"form": "10-K/A", "end": "2019-12-31", "filed": "2020-04-15", "val": 70.0},
                        ]
                    }
                },
                "SellingGeneralAndAdministrativeExpense": {
                    "units": {
                        "USD": [
                            {"form": "10-K", "end": "2018-12-31", "filed": "2019-03-15", "val": 20.0},
                            {"form": "10-K/A", "end": "2019-12-31", "filed": "2020-04-15", "val": 30.0},
                        ]
                    }
                },
                "InterestExpenseAndDebtExpense": {
                    "units": {
                        "USD": [
                            {"form": "10-K", "end": "2018-12-31", "filed": "2019-03-15", "val": 5.0},
                            {"form": "10-K/A", "end": "2019-12-31", "filed": "2020-04-15", "val": 7.0},
                        ]
                    }
                },
            }
        }
    }


class TestExtractAnnualSeries:
    def test_uses_filing_date_and_preserves_amendment_updates(self):
        facts = _companyfacts_fixture()
        out = bc.extract_annual_series(facts, bc.TAGS["equity"])
        assert list(out.index) == [
            pd.Timestamp("2019-03-15"),
            pd.Timestamp("2020-03-15"),
            pd.Timestamp("2020-04-15"),
        ]
        assert list(out.values) == [80.0, 100.0, 120.0]

    def test_reads_shares_from_dei_namespace(self):
        facts = _companyfacts_fixture()
        out = bc.extract_share_frame(facts)
        assert list(out["val"]) == [8.0, 8.0, 9.0, 10.0, 10.0, 11.0]


class TestBuildTickerCharacteristics:
    def test_characteristics_use_ff_annual_timing_and_june_formation_inputs(self, monkeypatch):
        prices = pd.Series(
            [8.0, 12.0, 14.0, 10.0, 10.0, 15.0],
            index=pd.to_datetime(["2018-12-31", "2019-06-30", "2019-12-31", "2020-03-31", "2020-04-30", "2020-06-30"]),
        )
        monkeypatch.setattr(bc, "load_month_end_prices", lambda ticker: prices)
        monkeypatch.setattr(bc, "fetch_company_facts", lambda cik: _companyfacts_fixture())

        out = bc.build_ticker_characteristics("AAPL", "0000320193")

        assert list(out["date"]) == [
            pd.Timestamp("2019-06-30"),
            pd.Timestamp("2019-12-31"),
            pd.Timestamp("2020-03-31"),
            pd.Timestamp("2020-04-30"),
            pd.Timestamp("2020-06-30"),
        ]

        jun19 = out[out["date"] == pd.Timestamp("2019-06-30")].iloc[0]
        mar20 = out[out["date"] == pd.Timestamp("2020-03-31")].iloc[0]
        apr20 = out[out["date"] == pd.Timestamp("2020-04-30")].iloc[0]
        jun20 = out[out["date"] == pd.Timestamp("2020-06-30")].iloc[0]

        assert jun19["market_cap"] == pytest.approx(96.0)
        assert jun19["book_to_market"] == pytest.approx((80.0 + 8.0 - 4.0) / 64.0)
        assert jun19["profitability"] == pytest.approx((100.0 - 50.0 - 20.0 - 5.0) / (80.0 + 8.0 - 4.0))
        assert pd.isna(jun19["investment"])

        assert mar20["market_cap"] == pytest.approx(100.0)
        assert mar20["book_to_market"] == pytest.approx((80.0 + 8.0 - 4.0) / 64.0)
        assert mar20["profitability"] == pytest.approx((100.0 - 50.0 - 20.0 - 5.0) / (80.0 + 8.0 - 4.0))
        assert pd.isna(mar20["investment"])

        assert apr20["market_cap"] == pytest.approx(110.0)
        assert apr20["book_to_market"] == pytest.approx((80.0 + 8.0 - 4.0) / 64.0)
        assert apr20["profitability"] == pytest.approx((100.0 - 50.0 - 20.0 - 5.0) / (80.0 + 8.0 - 4.0))
        assert pd.isna(apr20["investment"])

        assert jun20["market_cap"] == pytest.approx(165.0)
        assert jun20["book_to_market"] == pytest.approx((120.0 + 10.0 - 6.0) / 154.0)
        assert jun20["profitability"] == pytest.approx((140.0 - 70.0 - 30.0 - 7.0) / (120.0 + 10.0 - 6.0))
        assert jun20["investment"] == pytest.approx((220.0 / 160.0) - 1.0)
