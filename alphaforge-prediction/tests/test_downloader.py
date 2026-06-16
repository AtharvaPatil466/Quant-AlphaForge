"""Unit tests for ingest.downloader — entry reconstruction, build_row, run loop.

All network access is via a FakeSession-backed KalshiClient; no live calls.
"""
from __future__ import annotations

import json

import pytest

from ingest import schema as S
from ingest.kalshi_client import KalshiClient, KalshiClientConfig
from ingest.downloader import (
    Downloader, DownloadConfig, Checkpoint, IngestRow,
    reconstruct_entry, settlement_value_from, write_rows_parquet,
    ENTRY_LEAD_SECONDS,
)
from tests.conftest import FakeResponse, FakeSession, make_market, make_event, make_candle


# ---------------------------------------------------------------------------
# Entry-price reconstruction (§4) — pure logic, no network
# ---------------------------------------------------------------------------

def test_reconstruct_entry_picks_last_trade_before_lead():
    close_s = 100_000
    target = close_s - ENTRY_LEAD_SECONDS  # 96400
    candles = [
        make_candle(target - 120, "0.30"),     # before lead, traded
        make_candle(target - 60, "0.32"),      # last trade at/before lead -> chosen
        make_candle(target + 60, "0.40"),      # AFTER lead (look-ahead) -> ignored for primary
    ]
    snap = reconstruct_entry(candles, close_s)
    assert snap is not None
    assert snap.entry_price == pytest.approx(0.32)
    assert snap.snapshot_ts_s == target - 60
    assert snap.used_fallback is False
    assert snap.snapshot_ts_s < close_s


def test_reconstruct_entry_skips_no_trade_buckets():
    close_s = 100_000
    target = close_s - ENTRY_LEAD_SECONDS
    candles = [
        make_candle(target - 120, "0.25"),               # traded
        make_candle(target - 30, None, previous_dollars="0.25"),  # no trade
    ]
    snap = reconstruct_entry(candles, close_s)
    assert snap.entry_price == pytest.approx(0.25)
    assert snap.snapshot_ts_s == target - 120


def test_reconstruct_entry_fallback_when_no_trade_before_lead():
    close_s = 100_000
    target = close_s - ENTRY_LEAD_SECONDS
    # Only trade is AFTER the lead target but still before close -> fallback.
    candles = [
        make_candle(target + 100, "0.55"),
        make_candle(close_s - 10, "0.60"),    # last pre-close trade
    ]
    snap = reconstruct_entry(candles, close_s)
    assert snap is not None
    assert snap.used_fallback is True
    assert snap.entry_price == pytest.approx(0.60)
    assert snap.snapshot_ts_s == close_s - 10
    assert snap.snapshot_ts_s < close_s


def test_reconstruct_entry_none_when_never_traded():
    close_s = 100_000
    candles = [make_candle(close_s - 50, None, previous_dollars="0.5")]
    assert reconstruct_entry(candles, close_s) is None
    assert reconstruct_entry([], close_s) is None


def test_reconstruct_entry_rejects_snapshot_at_or_after_close():
    close_s = 100_000
    candles = [make_candle(close_s, "0.5")]   # snapshot exactly at close -> rejected
    assert reconstruct_entry(candles, close_s) is None


def test_reconstruct_entry_records_quotes():
    close_s = 100_000
    target = close_s - ENTRY_LEAD_SECONDS
    candles = [make_candle(target - 60, "0.30", yes_bid="0.28", yes_ask="0.33")]
    snap = reconstruct_entry(candles, close_s)
    assert snap.yes_bid == pytest.approx(0.28)
    assert snap.yes_ask == pytest.approx(0.33)


# ---------------------------------------------------------------------------
# settlement_value_from
# ---------------------------------------------------------------------------

def test_settlement_value_prefers_api_field():
    assert settlement_value_from({"settlement_value_dollars": "1.0000", "result": "no"}) == 1.0


def test_settlement_value_infers_from_result():
    assert settlement_value_from({"settlement_value_dollars": None, "result": "yes"}) == 1.0
    assert settlement_value_from({"settlement_value_dollars": "", "result": "no"}) == 0.0


# ---------------------------------------------------------------------------
# Checkpoint
# ---------------------------------------------------------------------------

def test_checkpoint_resume(tmp_path):
    p = tmp_path / "_ingest_checkpoint.jsonl"
    cp = Checkpoint(p)
    cp.append(IngestRow("A", "written", None, "2026-06-16T00:00:00Z"))
    cp.append(IngestRow("B", "failed", "boom", "2026-06-16T00:00:00Z"))
    cp2 = Checkpoint(p)               # reload from disk
    assert cp2.is_done("A") is True
    assert cp2.is_done("B") is False  # failed rows retried
    assert cp2.is_done("C") is False
    assert cp2.count("written") == 1


# ---------------------------------------------------------------------------
# write_rows_parquet
# ---------------------------------------------------------------------------

def test_write_rows_parquet_round_trip(tmp_path):
    import pandas as pd

    rows = [{
        "ticker": "A", "event_ticker": "E", "series_ticker": "S", "category": "Crypto",
        "market_type": "binary", "open_time": 1, "close_time": 100,
        "settlement_ts": 110, "result": "yes", "settlement_value": 1.0,
        "entry_price": 0.5, "implied_prob": 0.5, "entry_snapshot_ts": 50,
        "yes_bid": 0.49, "yes_ask": 0.51, "volume_fp": 10.0,
    }]
    out = tmp_path / "part-00000.parquet"
    n = write_rows_parquet(rows, out)
    assert n == 1
    df = pd.read_parquet(out)
    assert list(df.columns) == list(S.COLUMNS)
    assert df.loc[0, "result"] == "yes"


# ---------------------------------------------------------------------------
# End-to-end run loop against a fake API
# ---------------------------------------------------------------------------

def _build_router(markets_page, events, candles_by_ticker):
    def router(url, params):
        if url.endswith("/markets"):
            return FakeResponse(200, _json=markets_page)
        if "/events/" in url:
            et = url.rsplit("/", 1)[-1]
            return FakeResponse(200, _json=events.get(et, make_event(et)))
        if "/candlesticks" in url:
            # url: .../series/{s}/markets/{ticker}/candlesticks
            tkr = url.split("/markets/")[1].split("/candlesticks")[0]
            return FakeResponse(200, _json={"ticker": tkr, "candlesticks": candles_by_ticker.get(tkr, [])})
        return FakeResponse(404, _json={"error": {"message": "unrouted"}})
    return router


def _downloader(tmp_path, router) -> Downloader:
    client = KalshiClient(KalshiClientConfig(rate_limit_seconds=0.0), session=FakeSession(router=router))
    cfg = DownloadConfig(output_root=tmp_path, limit_per_page=10, max_pages=1, flush_every=100)
    return Downloader(cfg, client=client)


def test_run_writes_volume_bearing_resolved(tmp_path):
    close_iso = "2026-06-16T08:00:00Z"
    close_s = S.iso_to_ns(close_iso) // 1_000_000_000
    target = close_s - ENTRY_LEAD_SECONDS
    markets_page = {
        "markets": [
            make_market("TRADED", event_ticker="E1", volume_fp="500", close_time=close_iso),
            make_market("ZEROVOL", event_ticker="E1", volume_fp="0", close_time=close_iso),
            make_market("UNRESOLVED", event_ticker="E1", status="active", result="", volume_fp="9", close_time=close_iso),
        ],
        "cursor": "",
    }
    events = {"E1": make_event("E1", "SER1", "Sports")}
    candles = {"TRADED": [make_candle(target - 60, "0.12", yes_bid="0.10", yes_ask="0.14")]}
    dl = _downloader(tmp_path, _build_router(markets_page, events, candles))
    stats = dl.run()

    assert stats["written"] == 1
    assert stats["skipped_no_volume"] == 1
    assert stats["skipped_unresolved"] == 1

    df = __import__("pandas").read_parquet(tmp_path / "processed" / "resolved" / "part-00000.parquet")
    assert len(df) == 1
    r = df.iloc[0]
    assert r["ticker"] == "TRADED"
    assert r["category"] == "Sports"
    assert r["series_ticker"] == "SER1"
    assert float(r["entry_price"]) == pytest.approx(0.12)
    assert float(r["implied_prob"]) == pytest.approx(0.12)
    assert int(r["entry_snapshot_ts"]) < int(r["close_time"])


def test_run_skips_market_with_no_reconstructable_trade(tmp_path):
    close_iso = "2026-06-16T08:00:00Z"
    close_s = S.iso_to_ns(close_iso) // 1_000_000_000
    markets_page = {"markets": [make_market("NOENTRY", event_ticker="E1", volume_fp="5", close_time=close_iso)], "cursor": ""}
    events = {"E1": make_event("E1", "SER1", "Crypto")}
    candles = {"NOENTRY": [make_candle(close_s - 30, None, previous_dollars="0.4")]}  # never traded
    dl = _downloader(tmp_path, _build_router(markets_page, events, candles))
    stats = dl.run()
    assert stats["written"] == 0
    assert stats["skipped_no_entry"] == 1


def test_run_resumes_and_skips_done(tmp_path):
    close_iso = "2026-06-16T08:00:00Z"
    close_s = S.iso_to_ns(close_iso) // 1_000_000_000
    target = close_s - ENTRY_LEAD_SECONDS
    markets_page = {"markets": [make_market("TRADED", event_ticker="E1", volume_fp="500", close_time=close_iso)], "cursor": ""}
    events = {"E1": make_event("E1", "SER1", "Sports")}
    candles = {"TRADED": [make_candle(target - 60, "0.12")]}
    router = _build_router(markets_page, events, candles)

    dl1 = _downloader(tmp_path, router)
    dl1.run()
    # Second run: same ticker is already checkpointed -> skipped.
    dl2 = _downloader(tmp_path, router)
    stats2 = dl2.run()
    assert stats2["skipped_already_done"] == 1
    assert stats2["written"] == 0


def test_windowed_mode_drops_status_and_sends_close_ts(tmp_path):
    """Historical date-window mode pages without status= and with min/max_close_ts."""
    captured = {"market_params": None}
    close_iso = "2025-03-15T08:00:00Z"
    close_s = S.iso_to_ns(close_iso) // 1_000_000_000
    target = close_s - ENTRY_LEAD_SECONDS

    def router(url, params):
        if url.endswith("/markets"):
            captured["market_params"] = dict(params)
            return FakeResponse(200, _json={"markets": [
                make_market("OLD", event_ticker="E1", volume_fp="5", close_time=close_iso)
            ], "cursor": ""})
        if "/events/" in url:
            return FakeResponse(200, _json=make_event("E1", "SER1", "Politics"))
        if "/candlesticks" in url:
            return FakeResponse(200, _json={"ticker": "OLD",
                "candlesticks": [make_candle(target - 60, "0.07")]})
        return FakeResponse(404, _json={"error": {"message": "x"}})

    client = KalshiClient(KalshiClientConfig(rate_limit_seconds=0.0), session=FakeSession(router=router))
    cfg = DownloadConfig(output_root=tmp_path, max_pages=1,
                         min_close_ts=1_700_000_000, max_close_ts=1_710_000_000)
    dl = Downloader(cfg, client=client)
    stats = dl.run()
    assert stats["written"] == 1
    assert "status" not in captured["market_params"]
    assert captured["market_params"]["min_close_ts"] == 1_700_000_000
    assert captured["market_params"]["max_close_ts"] == 1_710_000_000


def test_event_cache_dedups_lookups(tmp_path):
    """Two markets on the same event → only one /events call."""
    close_iso = "2026-06-16T08:00:00Z"
    close_s = S.iso_to_ns(close_iso) // 1_000_000_000
    target = close_s - ENTRY_LEAD_SECONDS
    markets_page = {"markets": [
        make_market("M1", event_ticker="E1", volume_fp="5", close_time=close_iso),
        make_market("M2", event_ticker="E1", volume_fp="5", close_time=close_iso),
    ], "cursor": ""}
    events = {"E1": make_event("E1", "SER1", "Crypto")}
    candles = {"M1": [make_candle(target - 60, "0.10")], "M2": [make_candle(target - 60, "0.90")]}
    router = _build_router(markets_page, events, candles)
    client = KalshiClient(KalshiClientConfig(rate_limit_seconds=0.0), session=FakeSession(router=router))
    dl = Downloader(DownloadConfig(output_root=tmp_path, max_pages=1), client=client)
    dl.run()
    event_calls = sum(1 for url, _ in client.session.calls if "/events/" in url)
    assert event_calls == 1
