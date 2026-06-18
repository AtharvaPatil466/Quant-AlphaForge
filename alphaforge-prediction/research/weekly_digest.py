"""Weekly progress digest for the substrate #10 (Kalshi FLB) forward record.

A LOCAL, hands-off summariser — run weekly by launchd on the user's machine
(`scripts/com.alphaforge.prediction.papertrader.digest.plist`). It reads the
scorecard that the daily `reconcile` job keeps fresh (`data/paper/
paper_scorecard.json`), computes the week-over-week change in resolved count,
writes a short digest, and fires a macOS notification — loud when the §9
decision point is reached (PHASE2_SUCCESS true, or resolved ≥ target).

NOT a cloud routine: the scorecard lives in the local gitignored data/paper/
directory, so a cloud agent could never see it. NOT an LLM call: the scorecard
already holds every number; this is a deterministic read + diff + notify.

It does not run `reconcile` itself (that's the daily launchd job's slow pass over
all open tickers); instead it flags if the scorecard is stale, so a stalled
daily job is visible rather than silently producing a frozen digest.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STALE_AFTER_HOURS = 48.0


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def compute_digest(card: dict[str, Any], prev_state: dict[str, Any] | None,
                   now_iso: str) -> tuple[str, dict[str, Any], bool]:
    """Pure: (digest_text, new_state, is_decision_point) from a scorecard dict.

    `prev_state` is last run's saved state ({"n_resolved", "timestamp"}) or None.
    `is_decision_point` is True when §9 PHASE2_SUCCESS is met OR resolved ≥ target.
    """
    counts = card.get("counts", {})
    n_res = int(counts.get("n_resolved", 0))
    n_placed = int(counts.get("n_placed", 0))
    n_open = int(counts.get("n_open", 0))
    target = int(card.get("target_resolved", 0))
    frac = float(counts.get("fraction_of_target", 0.0))

    prev_n = int(prev_state.get("n_resolved", 0)) if prev_state else 0
    delta = n_res - prev_n

    sc = card.get("success_check", {})
    success = bool(sc.get("PHASE2_SUCCESS", False))
    hit_target = n_res >= target > 0
    decision = success or hit_target

    pnl = card.get("pnl", {})
    cal = card.get("calibration", {})
    edge = card.get("edge", {})
    ls, fav = edge.get("longshot", {}), edge.get("favorite", {})
    rule = card.get("rule", {})

    gen = card.get("generated_at", "?")
    gdt = _parse_iso(gen)
    ndt = _parse_iso(now_iso)
    stale = ""
    if gdt and ndt:
        age_h = (ndt - gdt).total_seconds() / 3600.0
        if age_h > STALE_AFTER_HOURS:
            stale = (f"  WARN: scorecard is {age_h:.0f}h old — the daily reconcile "
                     f"job may have stalled (check data/paper/logs/).")

    def _edge(d: dict) -> str:
        if not d or d.get("n", 0) == 0:
            return "n=0"
        return (f"{float(d.get('edge',0)):+.4f} "
                f"[{float(d.get('lo',0)):+.3f},{float(d.get('hi',0)):+.3f}] "
                f"n={int(d.get('n',0))}"
                f"{' FLB-ok' if d.get('excludes_zero') else ''}")

    lines = [
        "AlphaForge - Substrate #10 (Kalshi FLB) - Weekly Forward Digest",
        f"Generated {now_iso} | scorecard as of {gen}{stale}",
        f"Rule: {rule.get('name','?')} "
        f"({'PROVISIONAL' if rule.get('provisional') else 'frozen'}, "
        f"cap {rule.get('max_days_to_close','-')}d)",
        "",
        f"Progress: resolved {n_res}/{target} ({frac*100:.0f}%)  |  "
        f"{delta:+d} this week  |  placed {n_placed}, open {n_open}",
        f"Net P&L: ${float(pnl.get('net_pnl',0)):+.2f} "
        f"(${float(pnl.get('net_pnl_2x_fee',0)):+.2f} @2x fee)",
        f"Calibration vs market: Brier {float(cal.get('brier_market_implied',0)):.4f} "
        f"(no-skill {float(cal.get('base_rate_brier',0)):.4f}), "
        f"log-loss {float(cal.get('log_loss_market_implied',0)):.4f}",
        f"Edge - longshot {_edge(ls)} | favorite {_edge(fav)}",
        f"S9 success check: PHASE2_SUCCESS = {'YES' if success else 'NO'}  "
        f"(edge_ci_excl0={'Y' if sc.get('edge_ci_excludes_zero') else 'N'}, "
        f"calib_beats_mkt={'Y' if sc.get('calibration_beats_market') else 'N'}, "
        f"n>=target={'Y' if hit_target else 'N'})",
        "",
    ]
    if decision:
        why = "PHASE2_SUCCESS=True" if success else f"resolved {n_res} >= target {target}"
        lines.append(f"*** READ NOW - forward record reached a decision point ({why}). ***")
    else:
        note = ("ACCUMULATING - resolved count is still far below the MDE floor; "
                "treat the edge/CI as noise until n grows toward the target.")
        lines.append(f"Status: {note}")

    new_state = {"n_resolved": n_res, "net_pnl": float(pnl.get("net_pnl", 0.0)),
                 "timestamp": now_iso}
    return "\n".join(lines) + "\n", new_state, decision


def notify(title: str, message: str, *, loud: bool) -> None:
    """Fire a macOS notification (best-effort; no-op if osascript unavailable)."""
    sound = "Sosumi" if loud else "default"
    script = (f'display notification {json.dumps(message)} '
              f'with title {json.dumps(title)} sound name "{sound}"')
    try:
        subprocess.run(["osascript", "-e", script], check=False,
                       capture_output=True, timeout=10)
    except (FileNotFoundError, subprocess.SubprocessError):
        pass


def main(argv: list[str] | None = None) -> int:
    paper = Path("data") / "paper"
    card = load_json(paper / "paper_scorecard.json")
    if card is None:
        print("No scorecard yet at data/paper/paper_scorecard.json — has the "
              "forward run placed/reconciled? (see research/FORWARD_RUN.md)")
        notify("Kalshi FLB - weekly digest", "No scorecard found yet.", loud=False)
        return 1

    now = _utcnow_iso()
    prev = load_json(paper / ".digest_state.json")
    text, state, decision = compute_digest(card, prev, now)

    print(text)
    (paper / "weekly_digest.md").write_text(text)
    with (paper / "weekly_digest_history.jsonl").open("a") as fh:
        fh.write(json.dumps({"at": now, **state, "decision_point": decision}) + "\n")
    (paper / ".digest_state.json").write_text(json.dumps(state, indent=2))

    n_res = card.get("counts", {}).get("n_resolved", 0)
    target = card.get("target_resolved", 0)
    wow = state["n_resolved"] - (prev or {}).get("n_resolved", 0)
    if decision:
        notify("Kalshi FLB - DECISION POINT",
               f"Forward record hit a S9 decision point ({n_res}/{target} resolved). "
               f"Read data/paper/weekly_digest.md.", loud=True)
    else:
        notify("Kalshi FLB - weekly digest",
               f"Accumulating: {n_res}/{target} resolved ({wow:+d} this week).",
               loud=False)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
