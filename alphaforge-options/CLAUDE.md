# alphaforge-options — Sub-Project Context

**Status as of 2026-05-26:** Substrate #9 (VRP Iron Condor via SPY Options). **CLOSED FAILED at Phase 1 (2026-05-26).** Phase 0 CERTIFIED. Phase 1 EXECUTED. Full verdict: `research/PHASE1_VERDICT.md`.

This is the **ninth substrate** in the AlphaForge research program. Eight prior substrates:
- #1-#2: Equity Tier 1/2 — CLOSED FAILED
- #3: Crypto carry — CLOSED FAILED
- #4: Microstructure — IN PROGRESS (Phase 0 accumulating, earliest Phase 1: 2026-06-17)
- #5: PEAD — CLOSED FAILED
- #6: India — CLOSED FAILED
- #7: VIX/VRP via SVXY ETPs (§9.1 sizing) — CLOSED FAILED (Mode D → Mode A)
- #8: VIX/VRP via SVXY ETPs (20× sizing) — CLOSED FAILED (Sharpe invariant to scaling)

## Why This Substrate is Different from #7 and #8

Substrates #7 and #8 proved that **linear scaling of the SVXY ETP position does not change the Sharpe ratio** — mean and std both scale by k, so k cancels. The iron condor produces a fundamentally different P&L structure:
- **Theta decay** (quadratic, not linear) — options lose value even if the underlying doesn't move
- **Bounded payoff** — max loss per cycle = wing_width − net_premium (defined at entry)
- **Higher win rate** — profits when SPY stays within ±1σ (roughly 68-72% of monthly cycles)
- **VRP harvested via IV−RV gap directly**, not through futures roll yield

The 6-trial DSR denominator (vs 28 in #7/#8) is the other structural difference: with 6 pre-committed trials, a raw OOS Sharpe of ~0.85-1.0 clears DSR > 0.95, vs ~1.8-2.0 needed at 28 trials.

## Pre-Commit Anchor

**`research/SUBSTRATE9_DESIGN.md` SHA-256:** `2840a7750658e706a663cc38e5ff67bbd58a2b16ab47b4295279f32977f4c22a`

Any edit to `SUBSTRATE9_DESIGN.md` invalidates this hash. Phase 1 orchestrator and Phase 3 master runner must recompute and refuse to execute on mismatch.

## Strategy Class

- **Edge type:** structural premium harvest (NOT predictive)
- **Instrument:** SPY iron condor (sell 16Δ put + call, buy 5Δ put + call)
- **DTE:** open at 30-45 DTE, roll at 21 DTE
- **Sizing:** 20% NAV notional (auto-deleverage to 10% when VIX ≥ 30)
- **Tail risk:** DEFINED — max loss per cycle = wing_width − premium ≈ $12.50/share at VIX=20
- **Execution for Phase 4:** IBKR paper trading (opened 2026-05-26), `ib_insync` API

## Directory Structure (to be built)

```
data/                          ← symlinks to alphaforge-vix/data/ (read-only reuse)

ingest/
  bs_pricer.py                 ← Black-Scholes pricer, delta-targeting, premium computation (§4)
  realized_vol.py              ← wrapper around Substrate #7's realized_vol module

signals/
  vrp_filter.py                ← VRP_t = VIX_t − realized_vol_t(21d), entry filter logic

gauntlet/
  backtest.py                  ← monthly cycle-based backtest kernel (6 trials)
  stats.py                     ← DSR, bootstrap CI, Cornish-Fisher (reuse from #7 where possible)
  tail_risk.py                 ← Gate 5 drawdown per stress period, Gate 6 CF-Sharpe
  residualization.py           ← §8 four-factor OLS with HC0 SEs
  costs.py                     ← §7 options cost model (bid-ask + commission + stress widening)
  run_gauntlet.py              ← master runner, SHA-anchored

execution/
  ibkr_broker.py               ← IBKR paper trading via ib_insync (Phase 4 only)

tests/

research/
  SUBSTRATE9_DESIGN.md         ← THE CONTRACT (SHA 2840a775...)
  SUBSTRATE9_PHASE0_CERTIFIED.md ← Phase 0 cert (filed 2026-05-26)
  phase0_certify.py            ← Phase 0 orchestrator (to be built)
  phase1_run.py                ← Phase 1 orchestrator (to be built)
  run_gauntlet.py              ← Phase 3 master runner (to be built)
```

## 6 Pre-Committed Trials

| Trial | Short Δ | Long Δ | VRP filter | VIX filter |
|-------|---------|--------|------------|------------|
| T1 (base) | 16Δ | 5Δ | VRP > 0 | None |
| T2 | 16Δ | 5Δ | VRP > 2 | None |
| T3 | 16Δ | 5Δ | VRP > 0 | VIX < 30 |
| T4 | 20Δ | 5Δ | VRP > 0 | None |
| T5 | 16Δ | 10Δ | VRP > 0 | None |
| T6 | 16Δ | 5Δ | VRP > 2 | VIX < 30 |

DSR deflation denominator = **6**. No additions permitted after Phase 1.

## Data Sources (all from Substrate #7, read-only)

- `alphaforge-vix/data/etps/SPY.parquet` — SPY OHLCV 1990-01-02 → present
- `alphaforge-vix/data/vix_indices/` — VIX index 1990-01-02 → present
- `alphaforge-vix/ingest/fred.py` — DGS3MO risk-free rate with fallback constants

## Commands (to be added as modules are built)

```bash
cd alphaforge-options
python3 -m pytest tests/ -v --tb=short

# Phase 0 (already certified — re-run to re-verify)
python3 -m research.phase0_certify

# Phase 1 (unblocked as of 2026-05-26)
python3 -m research.phase1_run -v

# Phase 3 (blocked until Phase 1 verdict filed)
python3 -m gauntlet.run_gauntlet
```

## Reading Order for New Sessions

1. `research/SUBSTRATE9_DESIGN.md` — the contract
2. `research/SUBSTRATE9_PHASE0_CERTIFIED.md` — Phase 0 certification
3. `alphaforge-vix/research/GAUNTLET_VERDICT.md` — Substrate #7 verdict (why ETPs failed)
4. `alphaforge-vix/research/SUBSTRATE8_VERDICT.md` — Substrate #8 verdict (why sizing didn't help)
5. This `CLAUDE.md`
6. Top-level `/CLAUDE.md` for the broader substrate landscape
