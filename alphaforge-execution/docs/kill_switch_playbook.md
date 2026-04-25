# Kill-Switch Playbook

This document describes the kill-switch configuration for AlphaForge
Execution, what triggers it, how the unwind happens, and who is on the
hook to respond.

Configuration lives under the `kill_switch:` section of
`configs/execution_config.yaml`.

---

## 1. Triggers

The switch is evaluated at the end of each trading day in
`execution/daily_loop.py` *after* `log_snapshot()` commits to SQLite.
Any single trigger firing halts the next session.

| Trigger | Default | What it catches |
|---|---|---|
| `max_drawdown_pct` | 0.15 | Peak-to-trough NAV decline exceeds threshold. |
| `single_day_loss_pct` | 0.05 | One-day portfolio loss — catches blowups even when DD limit hasn't hit. |
| `consecutive_losing_days` | 10 | Slow bleed that DD alone might miss. |
| `realized_slippage_median_bps` | 50 | Execution quality has degraded materially. |
| `realized_cum_drag_vs_nav_pct` | 0.02 | Fill-error has eaten >2% of NAV since the strategy started. |
| `min_liquid_tickers` | 3 | Universe illiquidity event (e.g., circuit-breaker day). |

These are conservative defaults — tune per strategy AUM.

---

## 2. Unwind Ladder

Once a trigger fires the strategy does NOT market-sell the entire book
at once (would compound impact cost on the very day something bad
happened). Instead it ramps down on the schedule in `unwind_ladder`:

| Phase | Time since halt | Target flat fraction |
|---|---|---|
| Immediate | 0 h | 25 % |
| Short | +4 h | 50 % |
| Next close | +24 h | 100 % |

Entries into new positions are disabled the entire time. Existing
unfilled orders are cancelled before the first unwind tranche.

---

## 3. Who Gets Paged

A pager file (default `alphaforge_execution_pager.log`) is appended to
on every halt event. A SQLite row is written to the `snapshots` table
with `n_positions` set to -1 to make kill-switch days easy to filter.

Wire your own actual pager (PagerDuty, Slack, SMS) on top of these
two local artifacts — Execution intentionally does not call out to the
network from its core loop.

---

## 4. Re-Arming

The switch auto-clears at the start of the next trading day **only if**:

- `consecutive_losing_days` trigger is no longer active,
- `realized_cum_drag_vs_nav_pct` has not grown further,
- An operator has acknowledged the `pager_file` event by appending a
  line starting with `ACK:` (manual gate — prevents the system from
  silently re-entering after a blowup).

If any condition is unmet, the halt persists into the next session. A
human must confirm before capital starts moving again.

---

## 5. Testing the Playbook

The helper `research/slippage_reconciliation.py` will surface two of the
triggers (median slippage and cumulative drag). Run it nightly against
the production SQLite database; a non-zero `cumulative_drag_usd` that
keeps climbing is a leading indicator that a halt is coming.
