"""Spot-perp basis study — STUB.

Same stub-first discipline as `carry_study.py`. The hypothesis to test (when
this is implemented):

1. **Hypothesis (pre-committed before any OOS):**
       The percentage basis `(perp_mark - spot_mark) / spot_mark` is a forward
       indicator of either:
         (a) the next 8-hour funding rate, or
         (b) the next K-bar cross-sectional return ranking.

   If (a), the basis is just a noisy estimate of funding and the strategy is
   indistinguishable from the carry study. If (b), there's an additional spot
   return-predictability layer that funding-rate carry alone wouldn't capture.

2. **Substrate:** spot 1h close + perp 1h close from the local parquet store.

3. **Sampling alignment:** spot and perp 1h bars are aligned by `open_time`.
   Basis is computed at the bar close; predictions are made for the next bar's
   close — strictly no look-ahead.

4. **Signal:** cross-sectional rank of basis at time t predicts cross-sectional
   return rank at t+1 (or longer horizons in a CV-selected window).

5. **Costs:** same honest model as the carry study.

6. **Statistical hygiene:** same hygiene as carry_study. DSR + bootstrap CI +
   purged CV. Every horizon and lookback counts as a trial for deflation.

7. **Pre-commit gate:** pre-committed before any OOS evaluation.

Until this stub is replaced, callers will see NotImplementedError.
"""

from __future__ import annotations


def run_basis_study(*args, **kwargs):
    raise NotImplementedError(
        "basis_study.run_basis_study is a stub. See module docstring for the contract."
    )


if __name__ == "__main__":
    raise SystemExit("basis_study is a stub — see module docstring for the contract before implementing.")
