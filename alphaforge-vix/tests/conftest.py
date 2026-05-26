"""Shared test config for alphaforge-vix.

`@pytest.mark.network` tests hit live CBOE / yfinance / FRED endpoints.
Skipped by default — run with `pytest -m network` to enable.
"""
import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "network: tests that require live network access (CBOE, yfinance, FRED)",
    )


def pytest_collection_modifyitems(config, items):
    # Skip `@pytest.mark.network` tests unless explicitly selected.
    selected_markers = config.getoption("-m") or ""
    if "network" in selected_markers:
        return  # user opted in
    skip_network = pytest.mark.skip(
        reason="network tests skipped by default; use `pytest -m network` to enable"
    )
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip_network)
