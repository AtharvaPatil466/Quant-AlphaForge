# Backtest Engine Consolidation — Design Memo

**Phase:** Tier 1, Phase 2
**Status:** Design locked 2026-04-26, pre-implementation
**Owner:** Atharva Patil
**Lifecycle:** Implementation must conform to this memo; deviations
require updating this document first.

---

## 1. The framing the original plan assumed (and got wrong)

The Tier 1 plan said: *"collapse the two engines onto a single
canonical event-driven engine, eliminating the ρ=0.93 disagreement."*
Implicit assumption: there are **two** engines doing the **same job**
slightly differently, and they should merge into **one**.

**Survey finding (this session):** there are three engines, doing three
*different* jobs. The headline research artifacts that drive Tier 1
(`factor_study.py`, `capacity_study.py`) **don't use any of them** —
they have their own panel-based backtest paths. MARL also doesn't use
any of them. The "ρ=0.93 reconciliation gap" is between two engines
that the critical-path Tier 1 work doesn't actually call.

Reframing: the consolidation is mostly a **scope-and-clarity** problem,
not a numerical-correctness problem. The right move is to *delete or
rename* the duplication, not to merge it.

---

## 2. The three engines, what they do, who uses them

### `backtest/engine.py` — `run_synthetic_backtest`
- **Job:** JS-parity demo on Mulberry32 PRNG synthetic data.
- **Architecture:** vectorized panel sweep over a synthetic dataset.
  Daily returns clipped at ±20%, factor-boost term, holding-period
  rebalances, simple `tx_cost_bps` post-hoc deduction.
- **Real callers (non-self, non-test):**
  - `api/routes/backtest.py` (the synthetic backtest API endpoint)
  - `optimizer/mean_variance.py` (imports `BacktestConfig` as a *type
    alias* only — does not call `run_synthetic_backtest`)
- **Test callers:**
  - `tests/test_backtest.py` (functional tests)
  - `tests/test_parity.py` (numerical parity to 10 decimal places vs JS)
  - `tests/test_fuzz.py` (property tests)
- **Constraint that protects this engine:** `tests/test_parity.py`
  requires bit-for-bit JS reproducibility on the synthetic substrate.
  EventDrivenEngine *cannot* satisfy this without breaking its own
  architectural rules (no look-ahead, next-bar fills, per-fill costs).
  The synthetic engine therefore must stay as a separate module.

### `backtest/real_engine.py` — `run_real_backtest`
- **Job:** the *same factor backtest semantics* as `engine.py`, but
  against real OHLCV from the parquet store instead of synthetic data.
- **Architecture:** holding-period rebalances, decision-bar-close fills
  (no next-bar slip), per-rebalance flat tx-cost deduction, no per-fill
  cash accounting.
- **Documented bugs** (from `research/out/engine_reconciliation.md`):
  - Same-bar fills (no next-bar slip)
  - Daily ±20% clamp inherited from synthetic engine — meaningless on
    real data and induces drift on extreme days
  - Per-rebalance flat tx-cost deduction (not per-fill cash cost)
  - Factor index off-by-one (`MomentumFactor.compute_js` uses one
    lookback window, `MomentumLongShort` strategy uses the academically
    correct one — they disagree by one bar)
- **Real callers (non-self, non-test):**
  - `api/routes/backtest.py` (the real-data backtest API endpoint)
- **Test callers:** none (no tests for this engine — itself a problem)
- **Reconciliation status:** ρ=0.93 daily-return correlation against
  `EventDrivenEngine` on the same data. The gap is *not* a small
  numerical residual; the engines disagree fundamentally on
  fill-timing, cost accounting, and factor lookback. **There is no
  defensible methodology for reconciling them — `real_engine` is
  architecturally wrong on the dimensions where it disagrees.**

### `backtest/event_driven/` — `EventDrivenEngine`
- **Job:** the architecturally-correct backtest engine. Enforces no
  look-ahead via `BarHistory` raises, requires next-bar timestamps for
  fills, charges per-fill cash costs, has Portfolio as the single
  source of truth for cash/positions/NAV.
- **Real callers (non-self, non-test):** none yet outside research.
- **Test callers:**
  - `tests/test_event_driven_core.py`
  - `tests/test_event_driven_engine.py`
- **Status:** the canonical engine for any real-data backtest going
  forward. Phase 4-5 factor combination work will hang off this.

---

## 3. The decision

| Engine | Disposition |
|---|---|
| `backtest/engine.py` (`run_synthetic_backtest`) | **Keep, rename, restrict.** Move to `backtest/synthetic_demo.py`. Update `__init__.py` to make clear this is a JS-parity demo, not a research engine. Tests stay. API route stays (the JS frontend still calls it). |
| `backtest/real_engine.py` (`run_real_backtest`) | **Delete.** Architecturally wrong on costs, fills, and factor windows. `api/routes/backtest.py` is the only non-self caller; migrate it to a thin EventDrivenEngine adapter. |
| `backtest/event_driven/` | **Promote to canonical.** Becomes the only real-data backtest path. |

### Why not "merge real_engine into event_driven"

Because `real_engine` has *no defensible behavior on the dimensions
where it disagrees with EventDrivenEngine* — its same-bar fills, daily
clamp, and per-rebalance flat costs are bugs from the synthetic-engine
inheritance, not deliberate research choices. There is nothing to
preserve. Merging would mean importing the bugs.

### Why not "delete engine.py too"

Because the JS-parity test suite (`test_parity.py`) is a real
regression gate for the JS frontend, and EventDrivenEngine cannot
produce JS-parity output without breaking its own architecture. The
synthetic engine has a *different job* (parity demo) from the
event-driven engine (correct research backtest). They aren't
redundant; they're misnamed.

---

## 4. Migration plan, caller by caller

### `api/routes/backtest.py`
- **Synthetic route**: keep calling `run_synthetic_backtest` from the
  renamed `synthetic_demo` module. No semantic change.
- **Real-data route**: write a thin adapter
  `run_real_backtest_via_event_driven(config, end_date) -> BacktestResult`
  that:
  - Loads real history via `data.real_dataset.load_real_history`
    (unchanged)
  - Builds a `DataHandler` from the panel
  - Picks a `MomentumLongShort` (or generalized factor strategy) per
    `config.factor_name`
  - Builds `EventDrivenEngine` with `EngineConfig(rebalance_freq=
    config.holding_period, ...)`
  - Runs, then converts the `EngineRunResult.portfolio.nav_history`
    into a `BacktestResult`-shaped dict for the API response
- The API route's response schema does NOT change. The caller (JS
  frontend, third-party clients) sees the same shape.

### `optimizer/mean_variance.py`
- Imports `BacktestConfig` as a type alias for portfolio-construction
  config — does not actually call any backtest function. No-op
  migration: just update the import path after the rename.

### `tests/test_backtest.py`, `test_parity.py`, `test_fuzz.py`
- Update imports from `backtest.engine` → `backtest.synthetic_demo`.
  Tests stay.

### `research/engine_reconciliation.py`, `engine_diff.py`, `factor_study_engine_recon.py`, `score_diff.py`
- These are *historical artifacts* documenting the now-resolved
  reconciliation question. **Do not delete them** — they are the
  audit trail for *why* `real_engine.py` was retired. Add a banner
  comment to each pointing at this design memo and the
  `_session*_audit.json` artifacts that document the decision.
- The reconciliation scripts will fail to import once `real_engine.py`
  is deleted. That's correct — they're frozen. Mark them
  `pytest.skip`-equivalent (rename to `_archived_*.py` or move to a
  `research/_archived/` subdir).

### Downstream — `factor_study.py`, `capacity_study.py`, MARL
- **Not affected by this consolidation.** These never used the three
  engines in question. They use their own panel-based backtest paths
  and are explicit about it.

### Tests that don't exist yet
- `tests/test_engine_consolidation.py` — single test that asserts
  `backtest.real_engine` does not exist (`ImportError` expected) and
  that `backtest.synthetic_demo` exists. The "I deleted it on purpose"
  regression gate.

---

## 5. The reconciliation gap — where it goes

The `ρ=0.93` gap was between `EventDrivenEngine` and the about-to-be-
deleted `real_engine`. After this consolidation, **the gap ceases to
exist** because there is only one engine. The audit trail (the report
at `research/out/engine_reconciliation.md` and supporting scripts) is
preserved as historical record of *why* one engine survived.

The future analog of this gap — "is the EventDrivenEngine
result-equivalent to the panel-based path in `factor_study.py`?" — is a
*different* question, addressed by `factor_study_engine_recon.py`
which will be moved to the `_archived` set after Phase 4 builds an
EventDrivenEngine-based factor backtest from scratch.

---

## 6. Test-protection strategy

The full pytest suite (`alphaforge-python/`) currently passes. The
consolidation must preserve that.

Before any code change:
1. Run full suite, record baseline (`pytest tests/ -v --tb=short
   --co`) — count tests per file.
2. Confirm `test_parity.py` passes BEFORE touching anything (it's the
   most fragile — JS-parity to 10 decimal places).

During each migration step:
- After renaming `engine.py` → `synthetic_demo.py`: re-run
  `test_parity.py`, `test_backtest.py`, `test_fuzz.py`. All must pass.
- After deleting `real_engine.py`: re-run full suite. Skipped tests
  for archived research scripts are acceptable.
- After adding the API adapter: hit the API route manually, confirm
  the response shape matches what the JS frontend expects.

If any test fails that wasn't expected to: STOP, do not proceed,
diagnose. The whole point of this memo is to prevent silent
regressions.

---

## 7. Implementation plan — sessions

This memo is session 1 (design only, no code). Subsequent sessions:

- **Session 2** (~3 hrs): rename `engine.py` → `synthetic_demo.py`;
  update all imports across tests + optimizer + API route + research
  scripts. Re-run full suite, all must pass.

- **Session 3** (~4 hrs): write the EventDrivenEngine adapter for the
  real-data API route. Hit the API endpoint manually with curl, verify
  response shape. Add a regression test that exercises the adapter
  against a known-good fixture.

- **Session 4** (~2 hrs): delete `real_engine.py`. Move the four
  research/`engine_*` scripts to `research/_archived/`. Add the
  `test_engine_consolidation.py` "I deleted it on purpose" regression
  gate. Re-run full suite.

- **Session 5** (~2 hrs): update `CLAUDE.md` / `AGENTS.md` /
  `backtest/__init__.py` / `backtest/event_driven/__init__.py`
  docstrings to reflect the new layout. Cross-link this memo from the
  consolidated `__init__.py`.

Total: **~11 hours**, well under the 30-hour Tier 1 plan estimate.
The plan estimate assumed a hard merge; the actual work is
deletion + adapter + rename, which is much cheaper.

---

## 8. Out of scope for this memo

- Re-implementing `factor_study.py`'s panel-based backtest on top of
  EventDrivenEngine. That's Phase 4 work.
- Adding new factor strategies to EventDrivenEngine beyond
  `MomentumLongShort` and `PanelStrategy`. Phase 4-5 will add more.
- Performance benchmarking. EventDrivenEngine is bar-loop based; on
  the PIT 877-ticker universe over 16 years it will be slower than the
  vectorized panel sweep. If this becomes a Phase 4-5 bottleneck, the
  optimization is a separate work item with its own design.

---

## 9. Provenance discipline

The engine_reconciliation.md report (`research/out/`) and the four
`research/engine_*.py` scripts are the historical record of *why*
real_engine was retired. They must be preserved (moved to
`_archived/`, not deleted) so that future-me can answer "wait, why is
there only one engine?" by reading the audit trail.

The pytest fixture `tests/test_engine_consolidation.py` (to be added in
session 4) is the runtime assertion that this design held — that
real_engine truly is gone, that synthetic_demo exists, that the JS
parity tests still pass. Removing or weakening that fixture in the
future requires re-opening this design memo, not just commenting out a
test.
