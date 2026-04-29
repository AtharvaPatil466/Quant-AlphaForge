"""Regression gates for the intentional Phase 2 engine consolidation."""

from __future__ import annotations

import importlib


def test_real_engine_module_is_gone_on_purpose():
    try:
        importlib.import_module("backtest.real_engine")
    except ModuleNotFoundError:
        return
    raise AssertionError("backtest.real_engine still exists; Phase 2 retirement regressed")


def test_synthetic_demo_module_still_exists():
    module = importlib.import_module("backtest.synthetic_demo")
    assert hasattr(module, "run_synthetic_backtest")
