"""Unit tests for research.paper_trader — the Phase 2 forward harness.

All network access is via FakeSession-backed KalshiClient; no live calls.
Covers: journal round-trip + resumability, place idempotency, reconcile
net-of-fee P&L on a synthetic resolved set, and scorecard math (Brier / edge)
matching afgauntlet on a known case.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

# afgauntlet sibling sub-project on the path (same bootstrap the harness uses).
_AFG = Path(__file__).resolve().parent.parent.parent / "alphaforge-gauntlet"
if str(_AFG) not in sys.path:
    sys.path.insert(0, str(_AFG))

from afgauntlet.binary import brier_score, bucket_edge_ci   # noqa: E402

from ingest.kalshi_client import KalshiClient, KalshiClientConfig
from signals.strategy import (
    DEFAULT_RULE_SPEC, DIR_BACK, DIR_FADE, SIDE_NO, SIDE_YES, BucketRule,
    PaperOrder, RuleSpec,
)
from research.paper_trader import (
    DEFAULT_TARGET_RESOLVED, Journal, JournalEntry, PaperTrader,
    PaperTraderConfig, build_scorecard, order_to_journal_entry, settle_entry,
)
from tests.conftest import FakeResponse, FakeSession, make_event


def _client(router) -> KalshiClient:
    cfg = KalshiClientConfig(rate_limit_seconds=0.0, max_attempts=3)
    return KalshiClient(cfg, session=FakeSession(router=router))


def _order(ticker, side, eff, *, entry_price=0.10, stake=10,
           direction=DIR_FADE, sp=False) -> PaperOrder:
    return PaperOrder(
        ticker=ticker, event_ticker="EVT", series_ticker="S1",
        category="Economics", side=side, direction=direction,
        entry_price=entry_price, implied_prob=entry_price,
        effective_entry_price=eff, stake_contracts=stake,
        bucket_lo=0.0, bucket_hi=0.15, yes_bid=0.09, yes_ask=0.11,
        volume_fp=500.0, close_time=1, sp_nasdaq=sp, rule_name="test")


# ---------------------------------------------------------------------------
# Journal round-trip + resumability
# ---------------------------------------------------------------------------

def test_journal_round_trip(tmp_path):
    jpath = tmp_path / "journal.jsonl"
    j = Journal(jpath)
    e = order_to_journal_entry(_order("A", SIDE_NO, 0.90))
    j.add_entry(e)
    # Reload from disk -> entry persisted, queryable.
    j2 = Journal(jpath)
    assert j2.has_entry("A")
    assert not j2.has_entry("B")
    assert j2.entries[0].ticker == "A"
    assert j2.entries[0].side == SIDE_NO
    assert j2.open_entries()[0].ticker == "A"


def test_journal_resumability_does_not_duplicate(tmp_path):
    jpath = tmp_path / "journal.jsonl"
    j = Journal(jpath)
    j.add_entry(order_to_journal_entry(_order("A", SIDE_NO, 0.90)))
    # A settlement is appended; on reload both records reconstruct correctly.
    entry = j.entries[0]
    j.add_settlement(settle_entry(entry, "no", 0.0))
    j2 = Journal(jpath)
    assert j2.has_entry("A")
    assert j2.is_settled("A")
    assert j2.open_entries() == []     # settled -> no longer open
    assert len(j2.settlements) == 1


def test_journal_skips_malformed_lines(tmp_path):
    jpath = tmp_path / "journal.jsonl"
    j = Journal(jpath)
    j.add_entry(order_to_journal_entry(_order("A", SIDE_NO, 0.90)))
    with jpath.open("a") as fp:
        fp.write("not json\n")
    j2 = Journal(jpath)   # must not raise
    assert j2.has_entry("A")


# ---------------------------------------------------------------------------
# settle_entry — net-of-fee P&L (§6)
# ---------------------------------------------------------------------------

def test_settle_no_side_wins_on_no_resolution():
    # Faded a longshot at YES=0.10 -> took NO at cost basis 0.90, stake 10.
    entry = order_to_journal_entry(_order("A", SIDE_NO, 0.90, entry_price=0.10))
    rec = settle_entry(entry, "no", 0.0)
    # NO wins: payout 1.0/contract, gross/contract = 1.0 - 0.90 = 0.10.
    assert rec.gross_pnl_per_contract == pytest.approx(0.10)
    # Fee: roundup(0.07 * 10 * 0.10 * 0.90) = roundup(0.063) = $0.07.
    assert rec.fee_dollars == pytest.approx(0.07)
    # Net = 0.10*10 - 0.07 = 0.93.
    assert rec.net_pnl == pytest.approx(0.93)
    # Doubled-fee stress (§6 / SPIKE_NOTES: double the *rate* 0.07->0.14, THEN
    # apply the per-fill cent-ceiling): roundup(0.14*10*0.10*0.90)=roundup(0.126)
    # = $0.13 -> net 0.10*10 - 0.13 = 0.87. (NOT 2*roundup(0.063); the ceiling is
    # applied after the multiplier, matching fee_dollars and test_strategy.)
    assert rec.fee_dollars_2x == pytest.approx(0.13)
    assert rec.net_pnl_2x == pytest.approx(0.87)


def test_settle_no_side_loses_on_yes_resolution():
    entry = order_to_journal_entry(_order("A", SIDE_NO, 0.90, entry_price=0.10))
    rec = settle_entry(entry, "yes", 1.0)
    # NO loses: payout 0, gross/contract = 0 - 0.90 = -0.90.
    assert rec.gross_pnl_per_contract == pytest.approx(-0.90)
    assert rec.net_pnl == pytest.approx(-0.90 * 10 - 0.07)


def test_settle_yes_side_wins_on_yes_resolution():
    # Backed a favorite at YES=0.90 -> took YES at cost basis 0.90, stake 10.
    entry = order_to_journal_entry(
        _order("F", SIDE_YES, 0.90, entry_price=0.90, direction=DIR_BACK))
    rec = settle_entry(entry, "yes", 1.0)
    assert rec.gross_pnl_per_contract == pytest.approx(0.10)
    # Fee uses YES price 0.90: roundup(0.07*10*0.90*0.10) = roundup(0.063)=0.07.
    assert rec.fee_dollars == pytest.approx(0.07)
    assert rec.net_pnl == pytest.approx(0.93)


def test_settle_sp_nasdaq_half_fee():
    entry = order_to_journal_entry(
        _order("S", SIDE_YES, 0.50, entry_price=0.50, direction=DIR_BACK, sp=True))
    rec = settle_entry(entry, "yes", 1.0)
    # Half rate: roundup(0.035*10*0.25) = roundup(0.0875) = $0.09.
    assert rec.fee_dollars == pytest.approx(0.09)


def test_settle_rejects_bad_result():
    entry = order_to_journal_entry(_order("A", SIDE_NO, 0.90))
    with pytest.raises(ValueError):
        settle_entry(entry, "void", 0.0)


# ---------------------------------------------------------------------------
# Scorecard math matches afgauntlet on a known case
# ---------------------------------------------------------------------------

def _entry(ticker, implied_prob, side, eff, stake=10) -> JournalEntry:
    direction = DIR_FADE if side == SIDE_NO else DIR_BACK
    return order_to_journal_entry(
        _order(ticker, side, eff, entry_price=implied_prob,
               stake=stake, direction=direction))


def test_scorecard_brier_and_edge_match_afgauntlet():
    # Build a synthetic resolved set with known implied probs + outcomes.
    # Longshots faded at 0.10 (5 contracts), favorites backed at 0.90 (5).
    entries = []
    settlements = []
    # 8 longshots at implied 0.10: 1 resolves YES, 7 resolve NO
    # (realized YES freq = 0.125 > implied 0.10 here for a deterministic case).
    longshot_outcomes = [1, 0, 0, 0, 0, 0, 0, 0]
    for i, oy in enumerate(longshot_outcomes):
        e = _entry(f"L{i}", 0.10, SIDE_NO, 0.90)
        entries.append(e)
        settlements.append(settle_entry(e, "yes" if oy else "no",
                                        1.0 if oy else 0.0))
    # 8 favorites at implied 0.90: 7 resolve YES, 1 NO.
    favorite_outcomes = [1, 1, 1, 1, 1, 1, 1, 0]
    for i, oy in enumerate(favorite_outcomes):
        e = _entry(f"F{i}", 0.90, SIDE_YES, 0.90)
        entries.append(e)
        settlements.append(settle_entry(e, "yes" if oy else "no",
                                        1.0 if oy else 0.0))

    card = build_scorecard(entries, settlements, target_resolved=4,
                           rule=DEFAULT_RULE_SPEC, seed=7)

    # Reference Brier from afgauntlet on the same aligned arrays.
    predicted = [0.10] * 8 + [0.90] * 8
    outcomes = longshot_outcomes + favorite_outcomes
    ref_brier = brier_score(predicted, outcomes)
    assert card["calibration"]["brier_market_implied"] == pytest.approx(ref_brier)

    # Per-region edge matches bucket_edge_ci exactly (same seed).
    ref_long = bucket_edge_ci(predicted, outcomes, 0.0, 0.15, seed=7)
    assert card["edge"]["longshot"]["edge"] == pytest.approx(ref_long["edge"])
    assert card["edge"]["longshot"]["lo"] == pytest.approx(ref_long["lo"])
    assert card["edge"]["longshot"]["hi"] == pytest.approx(ref_long["hi"])

    ref_fav = bucket_edge_ci(predicted, outcomes, 0.85, 1.0, seed=7)
    assert card["edge"]["favorite"]["edge"] == pytest.approx(ref_fav["edge"])

    # Counts.
    assert card["counts"]["n_placed"] == 16
    assert card["counts"]["n_resolved"] == 16
    assert card["counts"]["n_open"] == 0


def test_scorecard_empty_is_safe():
    card = build_scorecard([], [], target_resolved=10)
    assert card["counts"]["n_resolved"] == 0
    assert math.isnan(card["calibration"]["brier_market_implied"])
    assert card["success_check"]["PHASE2_SUCCESS"] is False


def test_scorecard_success_requires_all_conditions():
    # Construct a powered, FLB-consistent favorite region whose edge CI excludes
    # zero positively and whose net P&L is positive.
    entries, settlements = [], []
    # 60 favorites at implied 0.90, all resolve YES -> realized 1.0 > 0.90.
    # 0.90 lands inside the harness favorite region (0.85, 1.0]; a favorite at
    # 0.80 would fall BELOW the >=85c favorite threshold (design §5 G1 /
    # DEFAULT_RULE_SPEC / FAVORITE_REGION) and produce an empty-region NaN edge.
    for i in range(60):
        e = _entry(f"F{i}", 0.90, SIDE_YES, 0.90, stake=1)
        entries.append(e)
        settlements.append(settle_entry(e, "yes", 1.0))
    card = build_scorecard(entries, settlements, target_resolved=50,
                           rule=DEFAULT_RULE_SPEC, seed=1)
    assert card["edge"]["favorite"]["edge"] > 0
    assert card["edge"]["favorite"]["excludes_zero"] is True
    assert card["success_check"]["edge_ci_excludes_zero"] is True
    assert card["pnl"]["net_pnl"] > 0
    assert card["success_check"]["PHASE2_SUCCESS"] is True


# ---------------------------------------------------------------------------
# PaperTrader.place — open markets -> journalled entries (mocked network)
# ---------------------------------------------------------------------------

def _open_market(ticker, last, *, event_ticker="EVT-1", status="active",
                 yes_bid="0.09", yes_ask="0.11", volume_fp="500.0"):
    return {
        "ticker": ticker, "event_ticker": event_ticker, "status": status,
        "last_price_dollars": last, "yes_bid_dollars": yes_bid,
        "yes_ask_dollars": yes_ask, "volume_fp": volume_fp,
        "close_time": "2026-06-20T08:00:00Z", "market_type": "binary",
    }


def test_place_journals_selected_open_markets(tmp_path):
    def router(url, params):
        if url.endswith("/markets"):
            assert params.get("status") == "open"
            return FakeResponse(200, _json={
                "markets": [
                    _open_market("LONG", "0.08"),    # longshot -> NO
                    _open_market("FAV", "0.92"),     # favorite -> YES
                    _open_market("MID", "0.50"),     # mid -> skip
                ],
                "cursor": "",
            })
        if "/events/" in url:
            return FakeResponse(200, _json=make_event("EVT-1", "S1", "Economics"))
        raise AssertionError(f"unexpected url {url}")

    cfg = PaperTraderConfig(output_root=tmp_path, target_resolved=4)
    trader = PaperTrader(cfg, client=_client(router))
    stats = trader.place()
    assert stats["selected"] == 2
    assert stats["journalled"] == 2

    # Re-running --place is idempotent: same open markets -> nothing new.
    trader2 = PaperTrader(cfg, client=_client(router))
    stats2 = trader2.place()
    assert stats2["journalled"] == 0
    assert stats2["skipped_existing"] == 2


def test_place_dry_run_does_not_write(tmp_path):
    def router(url, params):
        if url.endswith("/markets"):
            return FakeResponse(200, _json={
                "markets": [_open_market("LONG", "0.08")], "cursor": ""})
        if "/events/" in url:
            return FakeResponse(200, _json=make_event("EVT-1", "S1", "Economics"))
        raise AssertionError(url)

    cfg = PaperTraderConfig(output_root=tmp_path, target_resolved=4)
    trader = PaperTrader(cfg, client=_client(router))
    stats = trader.place(dry_run=True)
    assert stats["would_journal"] == 1
    assert stats["journalled"] == 0
    assert not cfg.journal_path.exists()


# ---------------------------------------------------------------------------
# PaperTrader.reconcile — settle resolved + idempotent (mocked network)
# ---------------------------------------------------------------------------

def test_reconcile_settles_resolved_and_is_idempotent(tmp_path):
    cfg = PaperTraderConfig(output_root=tmp_path, target_resolved=2,
                            rule=DEFAULT_RULE_SPEC, seed=3)
    # Seed the journal with two open entries directly.
    j = Journal(cfg.journal_path)
    j.add_entry(_entry("LONG", 0.10, SIDE_NO, 0.90))
    j.add_entry(_entry("FAV", 0.90, SIDE_YES, 0.90))

    # LONG resolves NO (fade wins); FAV still open on first pass.
    resolved_state = {"LONG": ("finalized", "no", "0.0000"),
                      "FAV": ("active", "", "")}

    def router(url, params):
        for tk, (status, result, sv) in resolved_state.items():
            if url.endswith(f"/markets/{tk}"):
                return FakeResponse(200, _json={"market": {
                    "ticker": tk, "status": status, "result": result,
                    "settlement_value_dollars": sv}})
        raise AssertionError(f"unexpected url {url}")

    trader = PaperTrader(cfg, client=_client(router))
    out = trader.reconcile()
    assert out["newly_settled"] == 1
    assert out["still_open"] == 1

    # Re-running with FAV now resolved YES (back wins) settles only the new one.
    resolved_state["FAV"] = ("finalized", "yes", "1.0000")
    trader2 = PaperTrader(cfg, client=_client(router))
    out2 = trader2.reconcile()
    assert out2["newly_settled"] == 1
    assert out2["still_open"] == 0
    assert out2["n_resolved_total"] == 2

    # Third pass: everything settled -> nothing to do (idempotent).
    trader3 = PaperTrader(cfg, client=_client(router))
    out3 = trader3.reconcile()
    assert out3["newly_settled"] == 0
    assert out3["checked"] == 0

    # Scorecard files were written.
    assert cfg.scorecard_md.exists()
    assert cfg.scorecard_json.exists()
    card = json.loads(cfg.scorecard_json.read_text())
    assert card["counts"]["n_resolved"] == 2
    # Both trades won (fade NO + back YES) -> positive net P&L.
    assert card["pnl"]["net_pnl"] > 0
