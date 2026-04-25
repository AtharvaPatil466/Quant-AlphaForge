#!/usr/bin/env python3
"""AlphaForge Performance Digest Generator.

Generates a daily Markdown summary of the Momentum and MARL paper strategies.
Designed to be called via cron after both daily executions complete.
"""

import json
import os
import sqlite3
from datetime import date
from typing import Any, Dict


def fetch_latest_snapshot(db_path: str) -> Dict[str, Any]:
    if not os.path.exists(db_path):
        return {}
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        row = cur.execute("SELECT * FROM snapshots ORDER BY date DESC LIMIT 1").fetchone()
        return dict(row) if row else {}


def fetch_rejected_orders(db_path: str, today: str) -> list:
    if not os.path.exists(db_path):
        return []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        # Anything not 'filled' or 'partially_filled' that was submitted today is an alert
        rows = cur.execute(
            "SELECT ticker, side, quantity, status FROM orders WHERE date=? AND status NOT IN ('filled', 'partially_filled', 'open')",
            (today,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_marl_decision() -> dict:
    if not os.path.exists("marl_decisions.jsonl"):
        return {}
    try:
        with open("marl_decisions.jsonl") as f:
            lines = f.readlines()
            if not lines:
                return {}
            # Assume last line is the most recent decision
            return json.loads(lines[-1].strip())
    except Exception:
        return {}


def format_strategy(name: str, snap: dict, rejected: list) -> str:
    if not snap:
        return f"### {name}\nNo data found in database.\n"
    
    ret = f"### {name}\n"
    ret += f"- **NAV**: ${snap.get('nav', 0):,.2f}\n"
    ret += f"- **Today's Return**: {snap.get('daily_return', 0):.2%}\n"
    ret += f"- **Cum Return**: {snap.get('cumulative_return', 0):.2%}\n"
    ret += f"- **Sharpe (YTD)**: {snap.get('sharpe_to_date', 0):.2f}\n"
    ret += f"- **Max Drawdown**: {snap.get('drawdown', 0):.2%}\n"
    ret += f"- **Positions**: {snap.get('n_positions', 0)} active. Weights: {snap.get('weights', '{}')}\n"
    
    if rejected:
        ret += f"- **Alerts**: ⚠️ {len(rejected)} rejected/failed orders.\n"
        for r in rejected:
            ret += f"  - {r['side']} {r['ticker']} {r['quantity']} -> {r['status']}\n"
    else:
        ret += "- **Alerts**: ✅ None.\n"
    return ret + "\n"


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    today = date.today().isoformat()
    
    mom_snap = fetch_latest_snapshot("live_trading.db")
    mom_rej = fetch_rejected_orders("live_trading.db", today)
    
    marl_snap = fetch_latest_snapshot("live_marl.db")
    marl_rej = fetch_rejected_orders("live_marl.db", today)
    marl_log = get_marl_decision()

    out = [f"# AlphaForge Daily Digest — {today}\n"]
    
    out.append(format_strategy("Momentum Strategy", mom_snap, mom_rej))
    
    marl_txt = format_strategy("MARL Strategy", marl_snap, marl_rej)
    if marl_log and marl_log.get("date") == today:
        marl_txt += "#### MARL Decision Logic\n"
        marl_txt += f"- **Action Selected**: {marl_log.get('action_name', 'N/A')}\n"
        probs = marl_log.get('action_probs', {})
        probs_str = ', '.join([f"{k}: {v:.1%}" for k, v in probs.items()])
        marl_txt += f"- **Probabilities**: {probs_str}\n"
        marl_txt += f"- **Obs Buffer Size**: {marl_log.get('obs_norm_buffer_size', 'N/A')} (Needs 63 for maturity)\n"
    out.append(marl_txt)

    # Comparison
    cmom = mom_snap.get("cumulative_return", 0.0) if mom_snap else 0.0
    cmarl = marl_snap.get("cumulative_return", 0.0) if marl_snap else 0.0
    diff = cmarl - cmom
    
    out.append("### Head-to-Head Comparison")
    if cmarl > cmom:
        out.append(f"🏆 **MARL** is leading Momentum by {diff:.2%}.")
    elif cmom > cmarl:
        out.append(f"🏆 **Momentum** is leading MARL by {abs(diff):.2%}.")
    else:
        out.append("⚖️ Both strategies are exactly tied.")

    digest_content = "\n".join(out)
    
    filename = f"daily_digest_{today}.md"
    with open(filename, "w") as f:
        f.write(digest_content)
    with open("latest_digest.md", "w") as f:
        f.write(digest_content)
    
    print(f"Digest generated: {filename}")


if __name__ == "__main__":
    main()
