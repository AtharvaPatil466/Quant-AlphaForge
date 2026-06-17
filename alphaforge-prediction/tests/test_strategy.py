"""Unit tests for signals.strategy — the Phase 2 rule layer (pure, no network).

Covers: RuleSpec / BucketRule invariants, the §6 fee model, open-market
extraction, and select_orders picking the right contracts on synthetic open
markets for a given rule.
"""
from __future__ import annotations

import math

import pytest

from signals.strategy import (
    DEFAULT_RULE_SPEC, DIR_BACK, DIR_FADE, SIDE_NO, SIDE_YES, BucketRule,
    OpenMarket, RuleSpec, extract_open_market, fee_dollars, select_orders,
)


# ---------------------------------------------------------------------------
# Fee model (§6 — frozen schedule)
# ---------------------------------------------------------------------------

def test_fee_general_rate_cent_ceiling():
    # roundup(0.07 * C * P * (1-P)) to the cent. At P=0.5, C=100:
    # 0.07*100*0.25 = 1.75 -> $1.75 exactly.
    assert fee_dollars(0.5, 100) == pytest.approx(1.75)


def test_fee_rounds_up_to_cent():
    # P=0.10, C=1: 0.07*1*0.1*0.9 = 0.0063 -> ceil to $0.01.
    assert fee_dollars(0.10, 1) == pytest.approx(0.01)
    # A genuinely zero fee stays 0 (no contracts).
    assert fee_dollars(0.10, 0) == 0.0


def test_fee_symmetric_in_p():
    assert fee_dollars(0.15, 50) == pytest.approx(fee_dollars(0.85, 50))


def test_fee_sp_nasdaq_half_rate():
    full = fee_dollars(0.5, 1000)
    half = fee_dollars(0.5, 1000, sp_nasdaq=True)
    assert half == pytest.approx(full / 2.0)


def test_fee_doubled_stress():
    base = fee_dollars(0.5, 1000)
    stress = fee_dollars(0.5, 1000, multiplier=2.0)
    assert stress == pytest.approx(2.0 * base)


def test_fee_clamps_price():
    assert fee_dollars(-0.2, 10) == 0.0   # P clamped to 0 -> 0 fee
    assert fee_dollars(1.5, 10) == 0.0    # P clamped to 1 -> 0 fee


# ---------------------------------------------------------------------------
# BucketRule / RuleSpec invariants
# ---------------------------------------------------------------------------

def test_bucket_rule_side_mapping():
    assert BucketRule(0.0, 0.15, DIR_FADE).side == SIDE_NO
    assert BucketRule(0.85, 1.0, DIR_BACK).side == SIDE_YES


def test_bucket_rule_rejects_bad_band_and_direction():
    with pytest.raises(ValueError):
        BucketRule(0.5, 0.5, DIR_FADE)
    with pytest.raises(ValueError):
        BucketRule(0.1, 0.2, "sideways")


def test_bucket_contains_left_closed_vs_open():
    b = BucketRule(0.0, 0.15, DIR_FADE)
    # Left-closed includes the lower edge (0c contract).
    assert b.contains(0.0, left_closed=True)
    assert not b.contains(0.0, left_closed=False)
    assert b.contains(0.15, left_closed=False)   # upper edge inclusive
    assert not b.contains(0.16, left_closed=False)
    assert not b.contains(float("nan"), left_closed=True)


def test_rulespec_requires_buckets_and_positive_stake():
    with pytest.raises(ValueError):
        RuleSpec(name="x", provisional=True, buckets=())
    with pytest.raises(ValueError):
        RuleSpec(name="x", provisional=True,
                 buckets=(BucketRule(0.0, 0.15, DIR_FADE),),
                 max_stake_contracts=0)


def test_rulespec_matching_bucket_lowest_left_closed():
    rule = DEFAULT_RULE_SPEC
    # 0c falls in the longshot bucket (lowest -> left-closed).
    b0 = rule.matching_bucket(0.0)
    assert b0 is not None and b0.direction == DIR_FADE
    # Mid prices match no bucket.
    assert rule.matching_bucket(0.5) is None
    # 90c -> favorite bucket.
    bf = rule.matching_bucket(0.90)
    assert bf is not None and bf.direction == DIR_BACK


def test_rulespec_round_trip_dict():
    d = DEFAULT_RULE_SPEC.to_dict()
    rebuilt = RuleSpec.from_dict(d)
    assert rebuilt.to_dict() == d
    assert rebuilt.name == DEFAULT_RULE_SPEC.name


def test_rulespec_freeze_clears_provisional():
    frozen = DEFAULT_RULE_SPEC.freeze(name="survivor-v1")
    assert frozen.provisional is False
    assert frozen.name == "survivor-v1"
    assert DEFAULT_RULE_SPEC.provisional is True   # original untouched


def test_default_rule_is_provisional():
    assert DEFAULT_RULE_SPEC.provisional is True
    assert "provisional" in DEFAULT_RULE_SPEC.name


def test_rulespec_category_eligibility_case_insensitive():
    rule = RuleSpec(name="x", provisional=True,
                    buckets=(BucketRule(0.0, 0.15, DIR_FADE),),
                    categories=frozenset({"Economics"}))
    assert rule.category_eligible("economics")
    assert rule.category_eligible("ECONOMICS")
    assert not rule.category_eligible("Crypto")
    # Empty categories => all eligible.
    rule_all = RuleSpec(name="y", provisional=True,
                        buckets=(BucketRule(0.0, 0.15, DIR_FADE),))
    assert rule_all.category_eligible("anything")


# ---------------------------------------------------------------------------
# Open-market extraction
# ---------------------------------------------------------------------------

def _raw_open(ticker: str, *, last="0.10", yes_bid="0.09", yes_ask="0.11",
              volume_fp="500.0", event_ticker="EVT-1",
              close_time="2026-06-20T08:00:00Z") -> dict:
    return {
        "ticker": ticker,
        "event_ticker": event_ticker,
        "status": "active",
        "last_price_dollars": last,
        "yes_bid_dollars": yes_bid,
        "yes_ask_dollars": yes_ask,
        "volume_fp": volume_fp,
        "close_time": close_time,
        "market_type": "binary",
    }


def test_extract_uses_last_price():
    om = extract_open_market(_raw_open("A", last="0.12"), "S1", "Economics")
    assert om is not None
    assert om.yes_price == pytest.approx(0.12)
    assert om.yes_bid == pytest.approx(0.09)
    assert om.series_ticker == "S1"
    assert om.category == "Economics"
    assert om.close_time > 0


def test_extract_falls_back_to_midpoint_when_no_last():
    om = extract_open_market(
        _raw_open("B", last="", yes_bid="0.20", yes_ask="0.30"), "S1", "Economics")
    assert om is not None
    assert om.yes_price == pytest.approx(0.25)


def test_extract_none_without_any_price():
    raw = _raw_open("C", last="", yes_bid="", yes_ask="")
    assert extract_open_market(raw, "S1", "Economics") is None


# ---------------------------------------------------------------------------
# select_orders — the core selection
# ---------------------------------------------------------------------------

def _om(ticker, price, *, category="Economics", volume=500.0,
        yes_bid=None, yes_ask=None, series="S1") -> OpenMarket:
    if yes_bid is None:
        yes_bid = max(price - 0.01, 0.0)
    if yes_ask is None:
        yes_ask = min(price + 0.01, 1.0)
    return OpenMarket(ticker=ticker, event_ticker="EVT", series_ticker=series,
                      category=category, yes_price=price, yes_bid=yes_bid,
                      yes_ask=yes_ask, volume_fp=volume, close_time=1)


def test_select_orders_fades_longshots_backs_favorites():
    markets = [
        _om("LONG", 0.08),    # longshot -> fade -> NO
        _om("FAV", 0.92),     # favorite -> back -> YES
        _om("MID", 0.50),     # mid -> no order
    ]
    orders = select_orders(markets, DEFAULT_RULE_SPEC)
    by = {o.ticker: o for o in orders}
    assert set(by) == {"FAV", "LONG"}
    assert by["LONG"].side == SIDE_NO
    assert by["LONG"].direction == DIR_FADE
    # NO cost basis = 1 - yes price.
    assert by["LONG"].effective_entry_price == pytest.approx(1.0 - 0.08)
    assert by["FAV"].side == SIDE_YES
    assert by["FAV"].direction == DIR_BACK
    assert by["FAV"].effective_entry_price == pytest.approx(0.92)
    # Sorted by ticker for stable journalling.
    assert [o.ticker for o in orders] == sorted(o.ticker for o in orders)


def test_select_orders_respects_category_filter():
    markets = [
        _om("ELIG", 0.08, category="Economics"),
        _om("MVE", 0.08, category="Exotics"),     # not in DEFAULT categories
    ]
    orders = select_orders(markets, DEFAULT_RULE_SPEC)
    assert [o.ticker for o in orders] == ["ELIG"]


def test_select_orders_volume_filter():
    markets = [
        _om("ZERO", 0.08, volume=0.0),    # §7: volume_fp > 0 required
        _om("OK", 0.08, volume=1.0),
    ]
    orders = select_orders(markets, DEFAULT_RULE_SPEC)
    assert [o.ticker for o in orders] == ["OK"]


def test_select_orders_require_quote():
    markets = [_om("NOQUOTE", 0.08, yes_bid=float("nan"), yes_ask=float("nan"))]
    orders = select_orders(markets, DEFAULT_RULE_SPEC)
    assert orders == []
    # A rule that does not require a quote keeps it.
    rule = RuleSpec(name="nq", provisional=True,
                    buckets=DEFAULT_RULE_SPEC.buckets,
                    categories=DEFAULT_RULE_SPEC.categories,
                    require_quote=False)
    orders2 = select_orders(markets, rule)
    assert [o.ticker for o in orders2] == ["NOQUOTE"]


def test_select_orders_stake_and_min_volume_from_rule():
    rule = RuleSpec(name="r", provisional=True,
                    buckets=(BucketRule(0.0, 0.15, DIR_FADE),),
                    categories=frozenset({"Economics"}),
                    max_stake_contracts=3, min_volume_fp=100.0)
    markets = [
        _om("LOWVOL", 0.08, volume=50.0),    # below min_volume_fp -> dropped
        _om("OKVOL", 0.08, volume=150.0),
    ]
    orders = select_orders(markets, rule)
    assert [o.ticker for o in orders] == ["OKVOL"]
    assert orders[0].stake_contracts == 3


def test_select_orders_sp_nasdaq_flag():
    rule = RuleSpec(name="r", provisional=True,
                    buckets=(BucketRule(0.85, 1.0, DIR_BACK),),
                    categories=frozenset(),
                    sp_nasdaq_series_prefixes=("KXINX",))
    markets = [
        _om("SPX", 0.90, series="KXINXY-26", category="Financials"),
        _om("OTHER", 0.90, series="KXWEATHER", category="Weather"),
    ]
    orders = {o.ticker: o for o in select_orders(markets, rule)}
    assert orders["SPX"].sp_nasdaq is True
    assert orders["OTHER"].sp_nasdaq is False


def test_select_orders_empty_input():
    assert select_orders([], DEFAULT_RULE_SPEC) == []


# ---------------------------------------------------------------------------
# Time-to-close cap (provisional forward tuning)
# ---------------------------------------------------------------------------

def _open_market(ticker, *, close_time, price=0.10, category="Economics"):
    return OpenMarket(ticker=ticker, event_ticker="E", series_ticker="S",
                      category=category, yes_price=price, yes_bid=price - 0.01,
                      yes_ask=price + 0.01, volume_fp=500.0, close_time=close_time)


def test_select_orders_time_to_close_cap():
    from dataclasses import replace
    now = 1_700_000_000_000_000_000
    day = 86_400 * 1_000_000_000
    near = _open_market("NEAR", close_time=now + 10 * day)
    far = _open_market("FAR", close_time=now + 400 * day)
    past = _open_market("PAST", close_time=now - day)
    capped = replace(DEFAULT_RULE_SPEC, max_days_to_close=45)
    # Cap set → only the near-term market is entered; far-future + past excluded.
    assert {o.ticker for o in select_orders([near, far, past], capped, now_ns=now)} == {"NEAR"}
    # No cap (default None) → close_time is ignored entirely (prior behaviour).
    nocap = {o.ticker for o in select_orders([near, far, past], DEFAULT_RULE_SPEC, now_ns=now)}
    assert {"NEAR", "FAR", "PAST"} <= nocap


def test_rulespec_max_days_to_close_round_trips():
    from dataclasses import replace
    r = replace(DEFAULT_RULE_SPEC, max_days_to_close=45.0)
    assert RuleSpec.from_dict(r.to_dict()).max_days_to_close == 45.0
    # Default rule is uncapped, and that survives a round-trip.
    assert DEFAULT_RULE_SPEC.max_days_to_close is None
    assert RuleSpec.from_dict(DEFAULT_RULE_SPEC.to_dict()).max_days_to_close is None


def test_forward_rule_json_has_time_cap():
    import json
    import pathlib
    p = pathlib.Path(__file__).resolve().parent.parent / "research" / "forward_rule.json"
    spec = RuleSpec.from_dict(json.loads(p.read_text()))
    assert spec.max_days_to_close is not None and spec.max_days_to_close > 0
