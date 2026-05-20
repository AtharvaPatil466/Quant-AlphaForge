"""Unit tests for ingest.downloader.

Every test runs against a FakeSession; no live NSE traffic. Tests cover:
  - URL construction
  - Source selection per era boundary
  - Atomic write
  - Checkpoint append + resume
  - Retry + backoff
  - 403/429 halt protocol
  - 404 → holiday log when ALL sources miss
  - weekday_range skips weekends
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pytest

# Make the sub-project importable without install.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.downloader import (  # noqa: E402
    Checkpoint, CheckpointRow, DownloadConfig, Downloader, HaltedError,
    HolidayLog, Result, Source, atomic_write_bytes, legacy_url, mto_url,
    output_path, sources_for_date, unified_url, weekday_range,
)


# ---------------------------------------------------------------------------
# Fake requests.Session
# ---------------------------------------------------------------------------

@dataclass
class _Resp:
    status_code: int
    content: bytes = b""


@dataclass
class FakeSession:
    """Returns a scripted response per URL. Records call order."""
    responses: dict[str, list[_Resp]] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def get(self, url: str, headers=None, timeout=None):
        self.calls.append(url)
        queue = self.responses.get(url, [])
        if not queue:
            return _Resp(status_code=599, content=b"unscripted")
        return queue.pop(0)


# ---------------------------------------------------------------------------
# URL + path construction
# ---------------------------------------------------------------------------

def test_legacy_url_format():
    u = legacy_url(date(2008, 4, 1))
    assert u.endswith("/2008/APR/cm01APR2008bhav.csv.zip")


def test_mto_url_format():
    u = mto_url(date(2008, 4, 1))
    assert u.endswith("/MTO_01042008.DAT")


def test_unified_url_format():
    u = unified_url(date(2024, 1, 8))
    assert u.endswith("/sec_bhavdata_full_08012024.csv")


def test_output_path_layout(tmp_path: Path):
    p = output_path(tmp_path, Source.LEGACY, date(2024, 1, 8))
    assert p == tmp_path / "bhavcopy" / "2024" / "01" / "cm08JAN2024bhav.csv.zip"


# ---------------------------------------------------------------------------
# Source selection
# ---------------------------------------------------------------------------

def test_sources_for_date_pre_era():
    # Well before boundary → legacy + MTO only.
    s = sources_for_date(date(2010, 6, 15))
    assert s == [Source.LEGACY, Source.MTO]


def test_sources_for_date_post_era():
    # Well after boundary → unified only.
    s = sources_for_date(date(2024, 6, 15))
    assert s == [Source.UNIFIED]


def test_sources_for_date_overlap():
    # Inside ±60d of boundary → all three (cross-check window).
    s = sources_for_date(date(2020, 2, 15))
    assert set(s) == {Source.LEGACY, Source.MTO, Source.UNIFIED}


# ---------------------------------------------------------------------------
# Atomic write
# ---------------------------------------------------------------------------

def test_atomic_write_creates_parent_dirs(tmp_path: Path):
    target = tmp_path / "deeper" / "nest" / "out.bin"
    sha = atomic_write_bytes(target, b"hello world")
    assert target.read_bytes() == b"hello world"
    # sha256("hello world") = b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9
    assert sha == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"


def test_atomic_write_no_partial_on_existing_target(tmp_path: Path):
    target = tmp_path / "out.bin"
    target.write_bytes(b"old contents")
    atomic_write_bytes(target, b"new contents")
    assert target.read_bytes() == b"new contents"
    # tmp file should not be left behind.
    assert not (tmp_path / "out.bin.tmp").exists()


# ---------------------------------------------------------------------------
# Checkpoint
# ---------------------------------------------------------------------------

def _row(d: date, source: Source, result: Result, **kw) -> CheckpointRow:
    base = dict(
        date=d.isoformat(), source=source.value, result=result.value,
        status=200 if result is Result.OK else (404 if result is Result.NOT_FOUND else 500),
        bytes=0, sha256=None, attempts=1, completed_at="2026-05-18T00:00:00Z",
    )
    base.update(kw)
    return CheckpointRow(**base)


def test_checkpoint_append_and_reload(tmp_path: Path):
    cp_path = tmp_path / "cp.jsonl"
    cp = Checkpoint(cp_path)
    cp.append(_row(date(2024, 1, 8), Source.UNIFIED, Result.OK,
                   bytes=12345, sha256="abcd"))
    # Reload from disk; state must persist.
    cp2 = Checkpoint(cp_path)
    assert cp2.is_done(date(2024, 1, 8), Source.UNIFIED)
    assert not cp2.is_done(date(2024, 1, 9), Source.UNIFIED)


def test_checkpoint_failed_is_retriable(tmp_path: Path):
    cp_path = tmp_path / "cp.jsonl"
    cp = Checkpoint(cp_path)
    cp.append(_row(date(2024, 1, 8), Source.UNIFIED, Result.FAILED))
    # FAILED is NOT terminal — must be retried on resume.
    cp2 = Checkpoint(cp_path)
    assert not cp2.is_done(date(2024, 1, 8), Source.UNIFIED)


def test_checkpoint_not_found_is_terminal(tmp_path: Path):
    cp_path = tmp_path / "cp.jsonl"
    cp = Checkpoint(cp_path)
    cp.append(_row(date(2024, 1, 8), Source.LEGACY, Result.NOT_FOUND))
    cp2 = Checkpoint(cp_path)
    assert cp2.is_done(date(2024, 1, 8), Source.LEGACY)


def test_checkpoint_halted_is_terminal(tmp_path: Path):
    cp_path = tmp_path / "cp.jsonl"
    cp = Checkpoint(cp_path)
    cp.append(_row(date(2024, 1, 8), Source.UNIFIED, Result.HALTED, status=403))
    # Halted is recorded as done so we don't bang on a banned IP repeatedly.
    cp2 = Checkpoint(cp_path)
    assert cp2.is_done(date(2024, 1, 8), Source.UNIFIED)


def test_checkpoint_malformed_line_skipped(tmp_path: Path):
    cp_path = tmp_path / "cp.jsonl"
    cp_path.write_text('{"date":"2024-01-08","source":"unified","result":"ok",'
                       '"status":200,"bytes":1,"sha256":"x","attempts":1,'
                       '"completed_at":"t"}\n'
                       'this is not json\n')
    cp = Checkpoint(cp_path)
    assert cp.is_done(date(2024, 1, 8), Source.UNIFIED)


# ---------------------------------------------------------------------------
# HolidayLog
# ---------------------------------------------------------------------------

def test_holiday_log_records_once(tmp_path: Path):
    path = tmp_path / "h.jsonl"
    hl = HolidayLog(path)
    hl.record(date(2024, 1, 26), [Source.UNIFIED])
    hl.record(date(2024, 1, 26), [Source.UNIFIED])  # idempotent
    lines = [l for l in path.read_text().splitlines() if l.strip()]
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["date"] == "2024-01-26"
    assert obj["weekday"] == "Friday"


# ---------------------------------------------------------------------------
# Downloader.fetch_one
# ---------------------------------------------------------------------------

def _cfg(tmp_path: Path) -> DownloadConfig:
    return DownloadConfig(
        output_root=tmp_path,
        rate_limit_seconds=0.0,  # no throttle in tests
        timeout_seconds=5,
    )


def test_fetch_one_200_writes_atomically(tmp_path: Path):
    cfg = _cfg(tmp_path)
    sess = FakeSession({unified_url(date(2024, 1, 8)): [_Resp(200, b"OHLCV,..."), ]})
    dl = Downloader(cfg, session=sess)
    row = dl.fetch_one(date(2024, 1, 8), Source.UNIFIED)
    assert row.result == Result.OK.value
    assert row.status == 200
    assert row.attempts == 1
    out = output_path(tmp_path, Source.UNIFIED, date(2024, 1, 8))
    assert out.read_bytes() == b"OHLCV,..."


def test_fetch_one_404_terminal(tmp_path: Path):
    cfg = _cfg(tmp_path)
    sess = FakeSession({legacy_url(date(2012, 10, 24)): [_Resp(404)]})
    dl = Downloader(cfg, session=sess)
    row = dl.fetch_one(date(2012, 10, 24), Source.LEGACY)
    assert row.result == Result.NOT_FOUND.value
    assert row.attempts == 1
    # Only one call — 404 does not retry.
    assert len(sess.calls) == 1


def test_fetch_one_403_halt(tmp_path: Path):
    cfg = _cfg(tmp_path)
    sess = FakeSession({mto_url(date(2010, 6, 15)): [_Resp(403)]})
    dl = Downloader(cfg, session=sess)
    row = dl.fetch_one(date(2010, 6, 15), Source.MTO)
    assert row.result == Result.HALTED.value
    assert row.status == 403
    # No retry for halt statuses.
    assert len(sess.calls) == 1


def test_fetch_one_5xx_retries_then_fails(tmp_path: Path, monkeypatch):
    # Avoid real sleeps during backoff.
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda s: None)
    cfg = _cfg(tmp_path)
    url = unified_url(date(2024, 1, 8))
    sess = FakeSession({url: [_Resp(503), _Resp(503), _Resp(503)]})
    dl = Downloader(cfg, session=sess)
    row = dl.fetch_one(date(2024, 1, 8), Source.UNIFIED)
    assert row.result == Result.FAILED.value
    assert row.attempts == 3
    assert sess.calls.count(url) == 3


def test_fetch_one_5xx_then_success(tmp_path: Path, monkeypatch):
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda s: None)
    cfg = _cfg(tmp_path)
    url = unified_url(date(2024, 1, 8))
    sess = FakeSession({url: [_Resp(503), _Resp(200, b"data")]})
    dl = Downloader(cfg, session=sess)
    row = dl.fetch_one(date(2024, 1, 8), Source.UNIFIED)
    assert row.result == Result.OK.value
    assert row.attempts == 2


# ---------------------------------------------------------------------------
# Downloader.fetch_date (multi-source orchestration)
# ---------------------------------------------------------------------------

def test_fetch_date_post_era_uses_unified_only(tmp_path: Path):
    cfg = _cfg(tmp_path)
    d = date(2024, 6, 15)
    sess = FakeSession({unified_url(d): [_Resp(200, b"data")]})
    dl = Downloader(cfg, session=sess)
    rows = dl.fetch_date(d)
    assert len(rows) == 1
    assert rows[0].source == Source.UNIFIED.value
    # No calls to legacy/MTO URLs.
    assert all("unified" not in u or "sec_bhavdata_full" in u for u in sess.calls)


def test_fetch_date_pre_era_uses_legacy_and_mto(tmp_path: Path):
    cfg = _cfg(tmp_path)
    d = date(2010, 6, 15)
    sess = FakeSession({
        legacy_url(d): [_Resp(200, b"PK\x03\x04zip-data")],
        mto_url(d): [_Resp(200, b"mto-data")],
    })
    dl = Downloader(cfg, session=sess)
    rows = dl.fetch_date(d)
    assert {r.source for r in rows} == {Source.LEGACY.value, Source.MTO.value}
    assert all(r.result == Result.OK.value for r in rows)


def test_fetch_date_all_404_records_holiday(tmp_path: Path):
    cfg = _cfg(tmp_path)
    d = date(2012, 10, 24)  # Dussehra 2012
    sess = FakeSession({
        legacy_url(d): [_Resp(404)],
        mto_url(d): [_Resp(404)],
    })
    dl = Downloader(cfg, session=sess)
    rows = dl.fetch_date(d)
    assert all(r.result == Result.NOT_FOUND.value for r in rows)
    # Holiday log should contain this date.
    hpath = tmp_path / "processed" / "_holidays.jsonl"
    assert hpath.exists()
    lines = [json.loads(l) for l in hpath.read_text().splitlines() if l.strip()]
    assert any(o["date"] == d.isoformat() for o in lines)


def test_fetch_date_partial_404_no_holiday(tmp_path: Path):
    """If even one source returns 200, the date is NOT a holiday."""
    cfg = _cfg(tmp_path)
    d = date(2010, 6, 15)
    sess = FakeSession({
        legacy_url(d): [_Resp(200, b"PKdata")],
        mto_url(d): [_Resp(404)],
    })
    dl = Downloader(cfg, session=sess)
    dl.fetch_date(d)
    hpath = tmp_path / "processed" / "_holidays.jsonl"
    if hpath.exists():
        lines = [l for l in hpath.read_text().splitlines() if l.strip()]
        assert not any(json.loads(l)["date"] == d.isoformat() for l in lines)


def test_fetch_date_halt_raises_and_records(tmp_path: Path):
    cfg = _cfg(tmp_path)
    d = date(2010, 6, 15)
    sess = FakeSession({legacy_url(d): [_Resp(403)]})
    dl = Downloader(cfg, session=sess)
    with pytest.raises(HaltedError):
        dl.fetch_date(d)
    # The halt row IS appended to the checkpoint so we don't re-bang on resume.
    cp = Checkpoint(tmp_path / "processed" / "_download_checkpoint.jsonl")
    assert cp.is_done(d, Source.LEGACY)


def test_fetch_date_resume_skips_completed(tmp_path: Path):
    cfg = _cfg(tmp_path)
    d = date(2024, 6, 15)
    # Pre-populate the checkpoint as if a prior run succeeded.
    cp = Checkpoint(tmp_path / "processed" / "_download_checkpoint.jsonl")
    cp.append(_row(d, Source.UNIFIED, Result.OK, bytes=100, sha256="x"))
    sess = FakeSession({})  # unscripted — would 599 if hit
    dl = Downloader(cfg, session=sess)
    rows = dl.fetch_date(d)
    assert rows == []  # nothing fetched this call
    assert sess.calls == []


# ---------------------------------------------------------------------------
# weekday_range
# ---------------------------------------------------------------------------

def test_weekday_range_skips_weekends():
    out = weekday_range(date(2024, 1, 5), date(2024, 1, 9))  # Fri..Tue
    assert out == [date(2024, 1, 5), date(2024, 1, 8), date(2024, 1, 9)]


def test_weekday_range_empty_when_start_after_end():
    assert weekday_range(date(2024, 1, 9), date(2024, 1, 5)) == []


def test_weekday_range_single_weekend_day():
    # Sat-Sat → no weekdays.
    assert weekday_range(date(2024, 1, 6), date(2024, 1, 7)) == []


# ---------------------------------------------------------------------------
# Downloader.run aggregate
# ---------------------------------------------------------------------------

def test_run_aggregates_stats(tmp_path: Path):
    cfg = _cfg(tmp_path)
    d1 = date(2024, 6, 14)  # Fri — weekday
    d2 = date(2024, 6, 17)  # Mon — weekday
    sess = FakeSession({
        unified_url(d1): [_Resp(200, b"data1")],
        unified_url(d2): [_Resp(404)],  # synthetic holiday for testing
    })
    dl = Downloader(cfg, session=sess)
    stats = dl.run([d1, d2])
    assert stats["dates_processed"] == 2
    assert stats["ok"] == 1
    assert stats["not_found"] == 1
    assert stats["failed"] == 0
    assert "halted" not in stats
