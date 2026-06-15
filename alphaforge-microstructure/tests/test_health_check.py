"""Tests for the recent-gap-rate alarm added to the collector health check.

The 2026-05/06 stale-process incident churned ~150 reconcile-failure events/hour
for 29 days yet went undetected because the cumulative `gap_events` count looks
identical whether the churn is historical or ongoing. These tests pin the
*recent-rate* signal that distinguishes the two and escalates to CRITICAL while
churn is live.

Only `collector.health_check` is imported (no aiohttp dependency), so this file
runs even where the collector's websocket deps are absent.
"""
import json
import time

from collector import health_check as hc


def _write_gaps(path, ages_seconds, now_epoch):
    """Write a _gaps.jsonl with events at the given ages (seconds before now)."""
    with open(path, "w") as fh:
        for age in ages_seconds:
            ts_ns = int((now_epoch - age) * 1e9)
            fh.write(json.dumps({"reason": "snapshot_reconcile:test",
                                 "ts_ns": ts_ns, "symbol": "BTCUSDT"}) + "\n")


def test_rate_zero_when_all_events_old(tmp_path):
    now = time.time()
    # 500 events, all ~2 hours old -> outside the 1h window -> rate 0.
    _write_gaps(tmp_path / "_gaps.jsonl", [7200 + i for i in range(500)], now)
    rate = hc._recent_gap_event_rate(tmp_path, now)
    assert rate == 0.0


def test_rate_counts_recent_events(tmp_path):
    now = time.time()
    # 30 events in the last 10 minutes -> all within the 1h window -> rate 30/h.
    _write_gaps(tmp_path / "_gaps.jsonl", [i * 20 for i in range(30)], now)
    rate = hc._recent_gap_event_rate(tmp_path, now)
    assert rate == 30.0


def test_rate_distinguishes_old_churn_from_ongoing(tmp_path):
    now = time.time()
    # The incident signature: huge historical pile + nothing recent.
    old = [7200 + i for i in range(100_000)]
    _write_gaps(tmp_path / "_gaps.jsonl", old, now)
    assert hc._gap_event_count(tmp_path) == 100_000      # cumulative looks alarming
    assert hc._recent_gap_event_rate(tmp_path, now) == 0.0  # but it's all old


def test_missing_file_and_unparseable_lines(tmp_path):
    now = time.time()
    assert hc._recent_gap_event_rate(tmp_path, now) == 0.0  # no file
    p = tmp_path / "_gaps.jsonl"
    p.write_text("not json\n" + json.dumps({"ts_ns": int(now * 1e9)}) + "\n" + "\n")
    # one valid recent event, garbage + blank ignored
    assert hc._recent_gap_event_rate(tmp_path, now) == 1.0


def test_run_health_check_critical_on_live_churn(tmp_path):
    now = time.time()
    # 50 events in the last 30 min -> 100/h >> CRIT threshold (20/h).
    _write_gaps(tmp_path / "_gaps.jsonl", [i * 30 for i in range(50)], now)
    r = hc.run_health_check(tmp_path)
    assert r["gap_rate_per_hour"] >= hc.CRIT_GAP_RATE_PER_HOUR
    assert r["status"] == "CRITICAL"
    assert r["exit_code"] == 2


def test_thresholds_ordered():
    assert hc.WARN_GAP_RATE_PER_HOUR < hc.CRIT_GAP_RATE_PER_HOUR
