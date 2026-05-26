"""Tests for ingest.cboe — CBOE VIX index downloader.

Two test modes:
  - Fake-session tests (default) — no live network, deterministic.
  - Live smoke (marked `network`) — hits cboe.com for one symbol to catch
    URL drift. Skipped by default; run with `pytest -m network`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
import pytest

from ingest import cboe


# ---------------------------------------------------------------------------
# Fake requests.Session
# ---------------------------------------------------------------------------

@dataclass
class _Resp:
    status_code: int
    content: bytes = b""


@dataclass
class FakeSession:
    """Returns scripted responses keyed by URL. Tracks call order."""
    responses: dict[str, list[_Resp]] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def get(self, url: str, headers=None, timeout=None):
        self.calls.append(url)
        queue = self.responses.get(url, [])
        if not queue:
            return _Resp(status_code=599, content=b"unscripted")
        return queue.pop(0)


# Mirror the real CBOE schema. DATE in MM/DD/YYYY.
# Fixtures must exceed the 200-byte sanity threshold in download_index.
def _build_vix_csv(start_year: int = 1990, n_rows: int = 10) -> bytes:
    """Build a synthetic CBOE-format CSV with n_rows data rows."""
    lines = [b"DATE,OPEN,HIGH,LOW,CLOSE"]
    for i in range(n_rows):
        month = (i % 12) + 1
        day = (i % 28) + 1
        lines.append(
            f"{month:02d}/{day:02d}/{start_year},"
            f"{17.0 + i * 0.1:.6f},"
            f"{17.5 + i * 0.1:.6f},"
            f"{16.5 + i * 0.1:.6f},"
            f"{17.0 + i * 0.1:.6f}".encode()
        )
    return b"\n".join(lines) + b"\n"


_VIX_CSV = _build_vix_csv(1990, 10)        # ~480 bytes — well over 200
_VIX3M_CSV = _build_vix_csv(2009, 10)


# ---------------------------------------------------------------------------
# URL + path construction
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sym,suffix", [
    ("VIX", "VIX_History.csv"),
    ("VIX1D", "VIX1D_History.csv"),
    ("VIX9D", "VIX9D_History.csv"),
    ("VIX3M", "VIX3M_History.csv"),
    ("VIX6M", "VIX6M_History.csv"),
])
def test_url_for_each_symbol(sym, suffix):
    url = cboe.url_for(sym)
    assert url.endswith(suffix)
    assert "cdn.cboe.com" in url


def test_url_for_unknown_symbol_raises():
    with pytest.raises(ValueError, match="unknown CBOE symbol"):
        cboe.url_for("VXST")


def test_output_path_layout(tmp_path):
    p = cboe.output_path(tmp_path, "VIX3M")
    assert p == tmp_path / "vix_indices" / "VIX3M.csv"


# ---------------------------------------------------------------------------
# _atomic_write
# ---------------------------------------------------------------------------

def test_atomic_write_creates_parents(tmp_path):
    target = tmp_path / "deeper" / "nest" / "out.csv"
    sha = cboe._atomic_write(target, b"DATE,CLOSE\n01/01/2024,15.0\n")
    assert target.read_bytes().startswith(b"DATE,CLOSE")
    # sha is hex; length 64.
    assert len(sha) == 64


def test_atomic_write_overwrites_existing(tmp_path):
    target = tmp_path / "out.csv"
    target.write_bytes(b"old")
    cboe._atomic_write(target, b"new")
    assert target.read_bytes() == b"new"
    assert not (tmp_path / "out.csv.tmp").exists()


# ---------------------------------------------------------------------------
# download_index — fake session
# ---------------------------------------------------------------------------

def test_download_index_200_writes_atomically(tmp_path):
    url = cboe.url_for("VIX")
    sess = FakeSession({url: [_Resp(200, _VIX_CSV)]})
    r = cboe.download_index("VIX", tmp_path, session=sess)
    assert r.ok
    assert r.status == 200
    assert r.attempts == 1
    target = cboe.output_path(tmp_path, "VIX")
    assert target.read_bytes() == _VIX_CSV


def test_download_index_403_raises_halted(tmp_path):
    url = cboe.url_for("VIX1D")
    sess = FakeSession({url: [_Resp(403)]})
    with pytest.raises(cboe.HaltedError, match="403"):
        cboe.download_index("VIX1D", tmp_path, session=sess)


def test_download_index_404_raises_halted(tmp_path):
    url = cboe.url_for("VIX9D")
    sess = FakeSession({url: [_Resp(404)]})
    with pytest.raises(cboe.HaltedError):
        cboe.download_index("VIX9D", tmp_path, session=sess)


def test_download_index_5xx_retries_then_fails(tmp_path, monkeypatch):
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda s: None)
    url = cboe.url_for("VIX3M")
    sess = FakeSession({url: [_Resp(503), _Resp(503), _Resp(503)]})
    r = cboe.download_index("VIX3M", tmp_path, session=sess)
    assert not r.ok
    assert r.attempts == 3
    assert sess.calls.count(url) == 3


def test_download_index_5xx_then_success(tmp_path, monkeypatch):
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda s: None)
    url = cboe.url_for("VIX")
    sess = FakeSession({url: [_Resp(503), _Resp(200, _VIX_CSV)]})
    r = cboe.download_index("VIX", tmp_path, session=sess)
    assert r.ok
    assert r.attempts == 2


def test_download_index_200_but_garbage_body_raises_halted(tmp_path):
    """If CBOE returns 200 with HTML / unexpected body, we don't write it."""
    url = cboe.url_for("VIX")
    sess = FakeSession({url: [_Resp(200, b"<html><body>error</body></html>" * 50)]})
    with pytest.raises(cboe.HaltedError, match="doesn't look like a CBOE"):
        cboe.download_index("VIX", tmp_path, session=sess)


# ---------------------------------------------------------------------------
# parse_index
# ---------------------------------------------------------------------------

def test_parse_index_returns_date_indexed(tmp_path):
    p = tmp_path / "VIX.csv"
    p.write_bytes(_VIX_CSV)
    df = cboe.parse_index(p)
    assert list(df.columns) == ["open", "high", "low", "close"]
    assert df.index.name == "date"
    assert df.index[0] == pd.Timestamp("1990-01-01")
    assert len(df) == 10
    assert df["close"].iloc[0] == pytest.approx(17.0)


def test_parse_index_handles_iso_dates(tmp_path):
    p = tmp_path / "alt.csv"
    p.write_bytes(b"DATE,OPEN,HIGH,LOW,CLOSE\n2024-01-08,15.0,16.0,14.5,15.5\n")
    df = cboe.parse_index(p)
    assert df.index[0] == pd.Timestamp("2024-01-08")


def test_parse_index_strips_column_whitespace(tmp_path):
    p = tmp_path / "VIX.csv"
    p.write_bytes(b" DATE , OPEN , HIGH , LOW , CLOSE \n01/02/1990,17,17,17,17\n")
    df = cboe.parse_index(p)
    assert "open" in df.columns


def test_parse_index_rejects_missing_columns(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_bytes(b"FOO,BAR\n1,2\n")
    with pytest.raises(ValueError, match="missing columns"):
        cboe.parse_index(p)


def test_parse_index_drops_unparseable_dates(tmp_path):
    p = tmp_path / "VIX.csv"
    p.write_bytes(
        b"DATE,OPEN,HIGH,LOW,CLOSE\n"
        b"01/02/1990,17,17,17,17\n"
        b"BADDATE,99,99,99,99\n"
        b"01/03/1990,18,18,18,18\n"
    )
    df = cboe.parse_index(p)
    assert len(df) == 2  # bad row dropped


# ---------------------------------------------------------------------------
# build_term_structure_panel
# ---------------------------------------------------------------------------

def test_build_term_structure_combines_all_present(tmp_path):
    # Stage VIX and VIX3M only.
    (tmp_path / "vix_indices").mkdir()
    (tmp_path / "vix_indices" / "VIX.csv").write_bytes(_VIX_CSV)
    (tmp_path / "vix_indices" / "VIX3M.csv").write_bytes(_VIX3M_CSV)

    panel = cboe.build_term_structure_panel(tmp_path)
    assert "VIX" in panel.columns
    assert "VIX3M" in panel.columns
    # The panel reindexes to the UNION of dates from both files.
    assert pd.Timestamp("1990-01-01") in panel.index
    assert pd.Timestamp("2009-01-01") in panel.index
    # On 1990 dates (in VIX, not in VIX3M fixture), VIX3M is NaN.
    assert pd.isna(panel.loc[pd.Timestamp("1990-01-01"), "VIX3M"])
    # On 2009 dates (in VIX3M, not in our tiny VIX fixture), VIX is NaN.
    assert pd.isna(panel.loc[pd.Timestamp("2009-01-01"), "VIX"])


def test_build_term_structure_raises_when_nothing_downloaded(tmp_path):
    with pytest.raises(FileNotFoundError, match="no CBOE index files"):
        cboe.build_term_structure_panel(tmp_path)


def test_build_term_structure_skips_missing_symbols(tmp_path, caplog):
    """If only VIX has been downloaded, the panel still builds with VIX
    and warns about the others."""
    (tmp_path / "vix_indices").mkdir()
    (tmp_path / "vix_indices" / "VIX.csv").write_bytes(_VIX_CSV)
    panel = cboe.build_term_structure_panel(tmp_path)
    assert list(panel.columns) == ["VIX"]
    assert len(panel) == 10


# ---------------------------------------------------------------------------
# download_all
# ---------------------------------------------------------------------------

def test_download_all_iterates_all_symbols(tmp_path, monkeypatch):
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda s: None)
    responses = {
        cboe.url_for(s): [_Resp(200, _VIX_CSV)] for s in cboe.SYMBOLS
    }
    sess = FakeSession(responses)
    results = cboe.download_all(tmp_path, session=sess, rate_limit_seconds=0.0)
    assert set(results.keys()) == set(cboe.SYMBOLS)
    assert all(r.ok for r in results.values())


# ---------------------------------------------------------------------------
# main (CLI)
# ---------------------------------------------------------------------------

def test_main_rejects_unknown_symbol(tmp_path):
    rc = cboe.main([
        "--output-root", str(tmp_path),
        "--symbols", "VIX,FAKE",
    ])
    assert rc == 2


# ---------------------------------------------------------------------------
# Live smoke (network-dependent; opt-in)
# ---------------------------------------------------------------------------

@pytest.mark.network
def test_live_smoke_VIX_download(tmp_path):
    """Hits cboe.com for one symbol. Skip by default. Run with -m network."""
    r = cboe.download_index("VIX", tmp_path)
    assert r.ok, f"live CBOE VIX download failed: status={r.status} error={r.error}"
    df = cboe.parse_index(r.path, symbol="VIX")
    assert len(df) > 8000  # 1990 → present is ~8800 trading days
    assert df.index.min() <= pd.Timestamp("1990-12-31")
