"""FastAPI server for execution monitoring."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from storage.database import get_connection
from storage.trade_log import get_orders, get_snapshots

app = FastAPI(title="AlphaForge Execution", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_DB_PATH: str | None = None
_HALT_FILE = Path(".halt")


def set_db_path(path: str) -> None:
    global _DB_PATH
    _DB_PATH = path


# ── Status ─────────────────────────────────────────────────


@app.get("/status")
def status() -> Dict[str, Any]:
    halted = _HALT_FILE.exists()
    halt_reason = _HALT_FILE.read_text().strip() if halted else ""

    conn = get_connection(_DB_PATH)
    snaps = get_snapshots(conn, limit=1)
    conn.close()

    if snaps:
        last = snaps[-1]
        return {
            "status": "halted" if halted else "running",
            "halted": halted,
            "halt_reason": halt_reason,
            "last_date": last["date"],
            "nav": last["nav"],
            "sharpe": last["sharpe_to_date"],
        }
    return {"status": "no_data", "halted": halted, "halt_reason": halt_reason}


# ── Portfolio ──────────────────────────────────────────────


@app.get("/portfolio")
def portfolio() -> Dict[str, Any]:
    conn = get_connection(_DB_PATH)
    snaps = get_snapshots(conn, limit=1)
    conn.close()
    if not snaps:
        return {}
    return snaps[-1]


@app.get("/portfolio/history")
def portfolio_history(days: int = 252) -> List[Dict[str, Any]]:
    conn = get_connection(_DB_PATH)
    snaps = get_snapshots(conn, limit=days)
    conn.close()
    return snaps


# ── Trades ─────────────────────────────────────────────────


@app.get("/trades")
def trades(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    conn = get_connection(_DB_PATH)
    result = get_orders(conn, from_date, to_date)
    conn.close()
    return result


# ── Halt / Resume ──────────────────────────────────────────


class HaltRequest(BaseModel):
    reason: str = "Manual halt"


@app.post("/halt")
def halt(req: HaltRequest) -> Dict[str, str]:
    _HALT_FILE.write_text(req.reason)
    return {"status": "halted", "reason": req.reason}


@app.post("/resume")
def resume() -> Dict[str, str]:
    if _HALT_FILE.exists():
        _HALT_FILE.unlink()
    return {"status": "resumed"}
