# Microstructure Phase 1 Gate — Operating Characteristics

Freeze-safe pre-characterization (synthetic null + injected IC; no real
ICs, no book data, contract untouched). Gate = G1(|IC|≥0.03 at peak, both
halves) ∧ G2(sign agree) ∧ G3(peak within ±1). Configs in 1a = 8.
Monte-Carlo reps per cell: 40000.

## 1. Effective sample size collapses with horizon

§4.4 reasons from the raw observation count. But K-horizon returns at
100 ms overlap, so n_eff ≈ N / (K × 10). The IC null SE = 1/√(n_eff−1):

| horizon | 1s | 5s | 30s | 60s | 300s | 900s | 3600s |
|---|---|---|---|---|---|---|---|
| n_eff (design_assumed (§4.4)) | 2,600,000 | 520,000 | 86,667 | 43,333 | 8,667 | 2,889 | 722 |
| n_eff (actual_collected (broken)) | 225,000 | 45,000 | 7,500 | 3,750 | 750 | 250 | 62 |
| IC null SE (design) | 0.001 | 0.001 | 0.003 | 0.005 | 0.011 | 0.019 | 0.037 |

At the 1 h horizon the *design's own* data assumption yields only a few
hundred effective observations — so |IC|≥0.03 is **not** a rare event
under the null there, even though it is ~20σ at the 1 s horizon.

## 2. False-positive rate under the null

| scenario | per-config pass rate | family-wise P(≥1 false survivor / 8 cfg) |
|---|---|---|
| design_assumed (§4.4) | 0.1053 | 0.5893 |
| actual_collected (broken) | 0.4046 | 0.9842 |

## 3. Detection power (true IC peaked at each horizon)

### design_assumed (§4.4)

| true peak IC | 1s | 5s | 30s | 60s | 300s | 900s | 3600s |
|---|---|---|---|---|---|---|---|
| 0.03 | 0.18 | 0.18 | 0.18 | 0.19 | 0.24 | 0.36 | 0.30 |
| 0.05 | 0.68 | 0.68 | 0.68 | 0.67 | 0.64 | 0.75 | 0.57 |

### actual_collected (broken)

| true peak IC | 1s | 5s | 30s | 60s | 300s | 900s | 3600s |
|---|---|---|---|---|---|---|---|
| 0.03 | 0.40 | 0.40 | 0.39 | 0.39 | 0.40 | 0.44 | 0.43 |
| 0.05 | 0.35 | 0.35 | 0.35 | 0.37 | 0.40 | 0.49 | 0.47 |

## 4. How to read the eventual Phase 1 verdict

- §4.4's 'power is overwhelming' is **true at short horizons** (≤30 s)
  and **false at long horizons** (≥300 s), where n_eff is tiny because
  of return overlap — this holds even under the design's own data count.
- Because G1 selects the **peak across all 7 horizons**, the long-horizon
  noise inflates the peak: under the null the gate preferentially mints
  spurious **long-horizon** survivors. G2+G3 (the two-half checks) deflate
  this but do not eliminate it — quantified in §2 above.
- Practical rule for the verdict: a survivor at K ≥ 300 s deserves far
  more skepticism than one at K ≤ 30 s, and ALL survivors should be
  reported with stationary-bootstrap IC CIs (afgauntlet), not the raw
  1/√N intuition. A K ≤ 1 s survivor is already flagged non-exploitable
  at L4 latency by the design's own §7.
- This does not change the frozen gates; it tells you which survivors are
  real and which are autocorrelation artifacts.

## 5. A design observation (for Phase 1.x, not this frozen contract)

G1 selects the peak by **raw |IC|** across 7 horizons whose null SEs differ
~30× (0.001 at 1 s vs 0.037 at 1 h). Picking the argmax of raw |IC| over
heteroskedastic estimates biases the peak toward the noisiest horizon — so
even a genuine short-horizon signal often loses the peak to long-horizon
noise, which both lowers power AND concentrates false positives at long K.
A z-scored peak (|IC| / SE_horizon) would compare like-for-like. This is a
note for any future Phase 1.x contract; it does not alter the current one.

## 6. Modeling caveats (do not over-read the exact percentages)

- n_eff uses the overlap approximation n_eff ≈ N/(K×10); the true IC
  effective-N also depends on the signal's own autocorrelation (set to 1 s
  here) and is approximate. The **direction and order of magnitude are
  robust** (long-horizon SE near/above 0.03 even under the design's data),
  but the exact FWER moves with `horizon_corr_rho` and `signal_autocorr`.
- Halving the deflation (n_eff×2 at 1 h) still leaves SE≈0.026 ≈ the 0.03
  threshold — the leak does not disappear under generous assumptions.
- The broken-collection power table is non-monotone in true IC because at
  n_eff≈62 (1 h) the empirical peak is noise-dominated: pass rate ≈ null
  size regardless of the true signal, i.e. the gate is **non-informative**
  on that data. This is the strongest argument for the recollection the
  Phase 0 recovery already requires.
