"""Smoke tests for the collector entrypoint wiring (collector/run_collector.py).

These guard the `main()` startup path — the part NOT exercised by driving `_run`
directly. A 2026-06-24 regression shipped a `NameError: name 'time' is not
defined` in `_configure_logging` (the `import time` was dropped during a refactor)
that every unit test missed because they configured logging themselves; only the
real launchd path called `_configure_logging`, so it crash-looped under the
supervisor. This module exercises that path so the class of bug fails in CI.
"""

from __future__ import annotations

from pathlib import Path

import collector.run_collector as rc


def test_module_imports_with_all_referenced_names():
    """Importing the module and touching its public entry must not NameError."""
    assert callable(rc.main)
    assert callable(rc._configure_logging)


def test_configure_logging_creates_a_logfile(tmp_path: Path):
    """The exact path that crash-looped under launchd: build the timestamped log
    filename and open the handlers. Must run clean and produce a log file."""
    log_dir = tmp_path / "logs"
    rc._configure_logging(log_dir)
    written = list(log_dir.glob("collector_*.log"))
    assert len(written) == 1, f"expected one collector log, found {written}"


def test_constructs_both_data_sources():
    """The two sources wired into _run must both construct without error."""
    from collector.binance_ws import BinanceFuturesCollector
    from collector.rest_trade_poller import RestTradePoller

    assert BinanceFuturesCollector(symbol="BTCUSDT").symbol == "BTCUSDT"
    assert RestTradePoller(symbol="BTCUSDT").symbol == "BTCUSDT"
