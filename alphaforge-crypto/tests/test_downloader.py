"""Downloader tests with mocked HTTP — verify pagination, parquet round-trip,
and idempotent resume."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pandas as pd
import pyarrow.parquet as pq

from data.binance_client import BinanceClient
from data.downloader import BinanceDataDownloader
from data.paths import default_paths, funding_path, kline_year_path


HOUR_MS = 3_600_000


def _make_kline_row(open_time_ms: int) -> list:
    close_time = open_time_ms + HOUR_MS - 1
    return [
        open_time_ms, "100", "110", "95", "105", "1000",
        close_time, "100000", 50, "500", "50000", "x",
    ]


def _make_funding_row(time_ms: int, rate: float, symbol: str = "BTCUSDT") -> dict:
    return {
        "symbol": symbol,
        "fundingTime": time_ms,
        "fundingRate": str(rate),
        "markPrice": "42000.0",
    }


def _utc_ms(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp() * 1000)


def test_kline_download_writes_parquet_partitioned_by_year(tmp_path) -> None:
    start = _utc_ms(2024, 1, 1)
    # 5 bars in 2024
    rows = [_make_kline_row(start + i * HOUR_MS) for i in range(5)]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=rows)

    client = BinanceClient(transport=httpx.MockTransport(handler))
    base = tmp_path / "binance"
    dl = BinanceDataDownloader(client, base_dir=base)
    result = dl.sync(["BTCUSDT"], start_date="2024-01-01", end_date="2024-01-02",
                     include_spot=False, include_funding=False)
    client.close()

    assert result.klines_perp_rows["BTCUSDT"] == 5
    path = kline_year_path("BTCUSDT", 2024, "perp", base_dir=base)
    assert path.exists()
    frame = pq.read_table(path).to_pandas()
    assert len(frame) == 5
    assert frame["open_time"].is_monotonic_increasing
    assert list(frame.columns) == [
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trade_count", "taker_buy_base", "taker_buy_quote",
    ]
    assert frame["open"].dtype == "float64"
    assert frame["open_time"].dtype == "int64"


def test_kline_pagination_walks_cursor(tmp_path) -> None:
    """First page returns 1000 rows, second returns 100 → both must be persisted."""
    start = _utc_ms(2024, 1, 1)
    pages: list[list] = []
    pages.append([_make_kline_row(start + i * HOUR_MS) for i in range(1000)])
    pages.append([_make_kline_row(start + (1000 + i) * HOUR_MS) for i in range(100)])

    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        idx = call_count["n"]
        call_count["n"] += 1
        if idx < len(pages):
            return httpx.Response(200, json=pages[idx])
        return httpx.Response(200, json=[])

    client = BinanceClient(transport=httpx.MockTransport(handler))
    base = tmp_path / "binance"
    dl = BinanceDataDownloader(client, base_dir=base)
    result = dl.sync(["BTCUSDT"], start_date="2024-01-01", end_date="2024-12-31",
                     include_spot=False, include_funding=False)
    client.close()

    assert result.klines_perp_rows["BTCUSDT"] == 1100
    assert call_count["n"] == 2  # short page ends pagination


def test_idempotent_resume_skips_already_downloaded(tmp_path) -> None:
    start = _utc_ms(2024, 1, 1)
    all_rows = [_make_kline_row(start + i * HOUR_MS) for i in range(5)]

    pages = {"used": False}

    def first_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=all_rows)

    client = BinanceClient(transport=httpx.MockTransport(first_handler))
    base = tmp_path / "binance"
    dl = BinanceDataDownloader(client, base_dir=base)
    dl.sync(["BTCUSDT"], start_date="2024-01-01", end_date="2024-01-02",
            include_spot=False, include_funding=False)
    client.close()

    # second run: handler returns empty — resume cursor should be past all_rows
    seen_params: dict = {}

    def second_handler(request: httpx.Request) -> httpx.Response:
        seen_params["start"] = request.url.params.get("startTime")
        return httpx.Response(200, json=[])

    client2 = BinanceClient(transport=httpx.MockTransport(second_handler))
    dl2 = BinanceDataDownloader(client2, base_dir=base)
    result = dl2.sync(["BTCUSDT"], start_date="2024-01-01", end_date="2024-01-02",
                      include_spot=False, include_funding=False)
    client2.close()

    assert result.klines_perp_rows["BTCUSDT"] == 0
    # the second-run cursor should be strictly after the last stored open_time
    assert int(seen_params["start"]) >= start + 5 * HOUR_MS


def test_funding_download_writes_whole_history_file(tmp_path) -> None:
    rows = [
        _make_funding_row(_utc_ms(2024, 1, 1), 0.0001),
        _make_funding_row(_utc_ms(2024, 1, 1) + 8 * HOUR_MS, -0.00005),
        _make_funding_row(_utc_ms(2024, 1, 1) + 16 * HOUR_MS, 0.0002),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=rows)

    client = BinanceClient(transport=httpx.MockTransport(handler))
    base = tmp_path / "binance"
    dl = BinanceDataDownloader(client, base_dir=base)
    result = dl.sync(["BTCUSDT"], start_date="2024-01-01", end_date="2024-01-02",
                     include_spot=False, include_perp=False)
    client.close()

    assert result.funding_rows["BTCUSDT"] == 3
    fp = funding_path("BTCUSDT", base_dir=base)
    assert fp.exists()
    frame = pq.read_table(fp).to_pandas()
    assert len(frame) == 3
    assert list(frame.columns) == ["funding_time", "symbol", "funding_rate", "mark_price"]


def test_kline_prefix_backfill_when_existing_data_starts_later(tmp_path) -> None:
    """Regression: if existing on-disk data starts at t2 and the user requests
    history from t1 < t2, the downloader must fetch [t1, t2) instead of jumping
    forward to t2 + interval.

    Hit this on 2026-05-15 when a smoke test populated 2025 BTC data, then a
    longer-range sync silently skipped 2020-2024.
    """
    base = tmp_path / "binance"

    # Step 1: seed the store with a small 2025 window.
    seed_start = _utc_ms(2025, 1, 1)
    seed_rows = [_make_kline_row(seed_start + i * HOUR_MS) for i in range(5)]

    def seed_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=seed_rows)

    client = BinanceClient(transport=httpx.MockTransport(seed_handler))
    dl = BinanceDataDownloader(client, base_dir=base)
    dl.sync(["BTCUSDT"], start_date="2025-01-01", end_date="2025-01-02",
            include_spot=False, include_funding=False)
    client.close()

    # Step 2: now request a longer range, observing what cursor the second
    # client sees. The first call should be the PREFIX walk starting at the
    # original requested start_ms (2020-01-01), not at 2025-01-01.
    earlier_rows = [_make_kline_row(_utc_ms(2020, 1, 1) + i * HOUR_MS) for i in range(3)]
    cursors_seen: list[int] = []

    def second_handler(request: httpx.Request) -> httpx.Response:
        st = request.url.params.get("startTime")
        cursors_seen.append(int(st) if st else -1)
        # serve prefix on first call, empty thereafter
        if len(cursors_seen) == 1:
            return httpx.Response(200, json=earlier_rows)
        return httpx.Response(200, json=[])

    client2 = BinanceClient(transport=httpx.MockTransport(second_handler))
    dl2 = BinanceDataDownloader(client2, base_dir=base)
    dl2.sync(["BTCUSDT"], start_date="2020-01-01", end_date="2025-01-02",
             include_spot=False, include_funding=False)
    client2.close()

    # The first cursor should be 2020-01-01, not the existing-data window.
    assert cursors_seen[0] == _utc_ms(2020, 1, 1), (
        f"prefix backfill should start at 2020-01-01, started at {cursors_seen[0]}"
    )
    # And the 2020 data should be on disk now.
    p2020 = kline_year_path("BTCUSDT", 2020, "perp", base_dir=base)
    assert p2020.exists()
    assert pq.read_table(p2020).num_rows == 3


def test_funding_handles_empty_string_markprice(tmp_path) -> None:
    """Regression: some older funding rows return ``markPrice: ""``.

    Hit this on the live API during the 2020-01-01 backfill — float("") raises
    ValueError, which crashed the sync mid-symbol.
    """
    rows = [
        {"symbol": "BTCUSDT", "fundingTime": _utc_ms(2020, 1, 1),
         "fundingRate": "0.0001", "markPrice": ""},
        {"symbol": "BTCUSDT", "fundingTime": _utc_ms(2020, 1, 1) + 8 * HOUR_MS,
         "fundingRate": "-0.0001", "markPrice": "8000.0"},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=rows)

    client = BinanceClient(transport=httpx.MockTransport(handler))
    base = tmp_path / "binance"
    dl = BinanceDataDownloader(client, base_dir=base)
    result = dl.sync(["BTCUSDT"], start_date="2020-01-01", end_date="2020-01-02",
                     include_spot=False, include_perp=False)
    client.close()

    assert result.funding_rows["BTCUSDT"] == 2
    fp = funding_path("BTCUSDT", base_dir=base)
    frame = pq.read_table(fp).to_pandas()
    assert pd.isna(frame["mark_price"].iloc[0])
    assert frame["mark_price"].iloc[1] == 8000.0


def test_year_boundary_partitioning(tmp_path) -> None:
    end_of_2024 = _utc_ms(2024, 12, 31) + 23 * HOUR_MS  # 2024-12-31 23:00 UTC
    start_of_2025 = _utc_ms(2025, 1, 1)
    rows = [_make_kline_row(end_of_2024), _make_kline_row(start_of_2025)]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=rows)

    client = BinanceClient(transport=httpx.MockTransport(handler))
    base = tmp_path / "binance"
    dl = BinanceDataDownloader(client, base_dir=base)
    dl.sync(["BTCUSDT"], start_date="2024-12-31", end_date="2025-01-02",
            include_spot=False, include_funding=False)
    client.close()

    p2024 = kline_year_path("BTCUSDT", 2024, "perp", base_dir=base)
    p2025 = kline_year_path("BTCUSDT", 2025, "perp", base_dir=base)
    assert p2024.exists() and p2025.exists()
    f2024 = pq.read_table(p2024).to_pandas()
    f2025 = pq.read_table(p2025).to_pandas()
    assert len(f2024) == 1 and len(f2025) == 1
