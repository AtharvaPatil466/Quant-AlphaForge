"""SQLite database setup and access."""

from __future__ import annotations

import sqlite3
from pathlib import Path

_DEFAULT_DB = Path(__file__).parent.parent / "alphaforge_execution.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    order_id     TEXT PRIMARY KEY,
    date         TEXT NOT NULL,
    ticker       TEXT NOT NULL,
    side         TEXT NOT NULL,
    quantity     REAL NOT NULL,
    fill_price   REAL,
    fill_quantity REAL,
    status       TEXT NOT NULL,
    slippage_bps REAL,
    tx_cost      REAL,
    submitted_at TEXT,
    filled_at    TEXT
);

CREATE TABLE IF NOT EXISTS snapshots (
    date              TEXT PRIMARY KEY,
    nav               REAL NOT NULL,
    daily_return      REAL,
    cumulative_return REAL,
    drawdown          REAL,
    sharpe_to_date    REAL,
    long_exposure     REAL,
    short_exposure    REAL,
    cash              REAL,
    n_positions       INTEGER,
    weights           TEXT
);

CREATE TABLE IF NOT EXISTS signals (
    date       TEXT NOT NULL,
    ticker     TEXT NOT NULL,
    mom_5d     REAL,
    mom_21d    REAL,
    mean_rev   REAL,
    composite  REAL,
    rank       INTEGER,
    PRIMARY KEY (date, ticker)
);
"""


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = str(db_path or _DEFAULT_DB)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn
