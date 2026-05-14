"""Cross-sectional funding-rate carry study — STUB.

This file intentionally does not implement a study yet. The actual design
should be committed AFTER inspecting the downloaded funding-rate
distribution, not before. The equity gauntlet (Tier 1 + Tier 2) failed in
part because study shape was locked in before the data was understood; this
script's stub is the explicit reminder not to repeat that.

When implementing, the study must include:

1. **Hypothesis (pre-committed before any OOS):**
       Funding rate at time t is positively autocorrelated at short horizons.
       A cross-sectional long-short portfolio formed on `-funding_rate_zscore`
       earns positive returns net of:
         - 8-hour funding cash flows (paid by long-perp, received by short-perp)
         - taker/maker fees on rebalance
         - slippage proportional to participation
         - spot-perp basis carry (when hedging on spot)

2. **Universe:** symbols listed in `data/binance/_manifest.json`.

3. **Sampling:** 8h funding cadence. Rebalance at each funding event using
   information observable strictly before the funding timestamp. No look-ahead.

4. **Signal:** cross-sectional rank of recent funding (rolling median over the
   last K funding events, K to be chosen via purged CV — not in-sample peeking).

5. **Portfolio:** long bottom-quintile funding (receive funding), short
   top-quintile (pay funding) — or vice versa, depending on which direction
   the autocorrelation runs. The sign should not be cherry-picked post hoc.

6. **Honest costs:** the `cost_model.py` analog (not yet written) must:
   - charge realistic Binance taker fees on perp side
   - account for spot-leg fees on hedging
   - book funding payments as a cash flow, not a slippage adjustment
   - assume zero borrow on perp (it's a perp); spot short borrow is real

7. **Statistical hygiene:** carry over from the equity stack —
   stationary-bootstrap Sharpe CIs, Deflated Sharpe across the full trial set
   (every parameter sweep counts as a trial), purged + embargoed CV, OOS
   evaluation on a window committed before the in-sample work is done.

8. **Pre-commit gate:** define DSR threshold + bootstrap-CI excludes-zero
   condition BEFORE looking at the OOS slice.

Until this stub is replaced with a real implementation, callers will see
NotImplementedError.
"""

from __future__ import annotations


def run_carry_study(*args, **kwargs):
    raise NotImplementedError(
        "carry_study.run_carry_study is a stub. Inspect the downloaded funding "
        "distribution first, then implement following the contract in the module "
        "docstring. Do not skip the pre-commit gate."
    )


if __name__ == "__main__":
    raise SystemExit("carry_study is a stub — see module docstring for the contract before implementing.")
