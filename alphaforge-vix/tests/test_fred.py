"""Tests for ingest.fred."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd
import pytest

from ingest import fred as F


# Realistic FRED CSV header + a few rows (real format).
_REAL_FRED_CSV = b"""DATE,DGS3MO
2024-01-02,5.40
2024-01-03,5.41
2024-01-04,5.42
2024-01-05,5.43
2024-01-08,5.39
2024-01-09,.
2024-01-10,5.42
""" + b"# pad" * 50  # pad over the 200-byte sanity threshold


@dataclass
class _Resp:
    status_code: int
    content: bytes = b""


@dataclass
class FakeSession:
    queue: list[_Resp] = field(default_factory=list)
    calls: int = 0

    def get(self, url, headers=None, timeout=None):
        self.calls += 1
        if self.queue:
            return self.queue.pop(0)
        raise __import__("requests").exceptions.ReadTimeout("default timeout")


# ---------------------------------------------------------------------------
# output_path
# ---------------------------------------------------------------------------

def test_output_path_layout(tmp_path):
    assert F.output_path(tmp_path) == tmp_path / "rates" / "DGS3MO.csv"


# ---------------------------------------------------------------------------
# download_dgs3mo
# ---------------------------------------------------------------------------

def test_download_200_with_real_format_succeeds(tmp_path, monkeypatch):
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda s: None)
    sess = FakeSession(queue=[_Resp(200, _REAL_FRED_CSV)])
    r = F.download_dgs3mo(tmp_path, session=sess, max_attempts=3)
    assert r.ok
    assert r.rows == 7  # 7 rows in the fixture (one is missing-value ".")


def test_download_403_terminates_immediately(tmp_path):
    sess = FakeSession(queue=[_Resp(403)])
    r = F.download_dgs3mo(tmp_path, session=sess, max_attempts=3)
    assert not r.ok
    assert "permanent" in (r.error or "").lower()
    assert sess.calls == 1  # no retry on 403


def test_download_404_terminates_immediately(tmp_path):
    sess = FakeSession(queue=[_Resp(404)])
    r = F.download_dgs3mo(tmp_path, session=sess, max_attempts=3)
    assert not r.ok
    assert sess.calls == 1


def test_download_timeout_retries_then_fails(tmp_path, monkeypatch):
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda s: None)
    import requests
    sess = FakeSession(queue=[])  # all calls will raise ReadTimeout
    r = F.download_dgs3mo(tmp_path, session=sess, max_attempts=3)
    assert not r.ok
    assert sess.calls == 3


def test_download_timeout_then_success(tmp_path, monkeypatch):
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda s: None)
    sess = FakeSession(queue=[_Resp(200, _REAL_FRED_CSV)])
    # Wrap the get method to fail the first call, then succeed.
    original_get = sess.get
    call_count = [0]

    def flaky_get(url, headers=None, timeout=None):
        call_count[0] += 1
        if call_count[0] == 1:
            import requests
            raise requests.exceptions.ReadTimeout("transient")
        return original_get(url)

    sess.get = flaky_get
    r = F.download_dgs3mo(tmp_path, session=sess, max_attempts=3)
    assert r.ok


def test_download_garbage_body_is_rejected(tmp_path, monkeypatch):
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda s: None)
    # 200 OK but body is HTML — should NOT be accepted.
    garbage = b"<html><body>error</body></html>" + b"pad" * 100
    sess = FakeSession(queue=[_Resp(200, garbage)] * 3)
    r = F.download_dgs3mo(tmp_path, session=sess, max_attempts=3)
    assert not r.ok


# ---------------------------------------------------------------------------
# parse_dgs3mo
# ---------------------------------------------------------------------------

def test_parse_returns_decimal_rates(tmp_path):
    csv = tmp_path / "DGS3MO.csv"
    csv.write_bytes(b"DATE,DGS3MO\n2024-01-02,5.40\n2024-01-03,4.50\n")
    s = F.parse_dgs3mo(csv)
    # 5.40% → 0.054
    assert s.iloc[0] == pytest.approx(0.054)
    assert s.iloc[1] == pytest.approx(0.045)
    assert s.name == "rate_annual"


def test_parse_treats_dot_as_missing(tmp_path):
    csv = tmp_path / "DGS3MO.csv"
    csv.write_bytes(b"DATE,DGS3MO\n2024-01-02,5.40\n2024-01-03,.\n2024-01-04,5.42\n")
    s = F.parse_dgs3mo(csv)
    assert pd.isna(s.iloc[1])
    assert s.iloc[2] == pytest.approx(0.0542)


def test_parse_accepts_alt_column_names(tmp_path):
    """Some FRED endpoints use 'observation_date' instead of 'DATE'."""
    csv = tmp_path / "DGS3MO.csv"
    csv.write_bytes(b"observation_date,DGS3MO\n2024-01-02,5.40\n")
    s = F.parse_dgs3mo(csv)
    assert len(s) == 1
    assert s.iloc[0] == pytest.approx(0.054)


# ---------------------------------------------------------------------------
# Fallback series
# ---------------------------------------------------------------------------

def test_fallback_series_two_regimes():
    s = F.build_fallback_series(date(2020, 1, 1), date(2024, 12, 31))
    pre_2022 = s[s.index < pd.Timestamp("2022-01-01")]
    post_2022 = s[s.index >= pd.Timestamp("2022-01-01")]
    assert (pre_2022 == F.FALLBACK_ANNUAL_RATE_PRE_2022).all()
    assert (post_2022 == F.FALLBACK_ANNUAL_RATE_POST_2022).all()


def test_fallback_series_overrides_take_effect():
    s = F.build_fallback_series(
        date(2020, 1, 1), date(2024, 12, 31),
        pre_2022_rate=0.001, post_2022_rate=0.10,
    )
    assert s.iloc[0] == 0.001
    assert s.loc[pd.Timestamp("2024-06-03")] == 0.10


def test_annualized_to_daily_matches_compounding():
    s = pd.Series([0.05], index=[pd.Timestamp("2024-01-02")])
    daily = F.annualized_to_daily(s)
    expected = (1.05) ** (1 / 252.0) - 1.0
    assert daily.iloc[0] == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Live network smoke
# ---------------------------------------------------------------------------

@pytest.mark.network
def test_live_dgs3mo_download(tmp_path):
    """May fail from sandbox per spike test. Skip-on-failure is acceptable;
    failure is informative (records the issue) but doesn't block Phase 0."""
    r = F.download_dgs3mo(tmp_path, timeout=90, max_attempts=2)
    # We don't require this to pass — but if it does, validate the shape.
    if r.ok:
        df = F.parse_dgs3mo(r.path)
        assert len(df) > 1000  # decades of T-bill data
    else:
        pytest.skip(f"FRED unreachable from this environment: {r.error}")
