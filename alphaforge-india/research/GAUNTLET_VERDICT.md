# Gauntlet Verdict — CLOSED FAILED

_Generated 2026-05-20T08:39:04Z_
_INDIA_DESIGN.md SHA-256: `3b397262d5799f7fe6b583b9c97d8eee6d07852611ec8c046a7c717ca1b031b9`_

**Trials evaluated:** 22
**DSR deflation denominator:** 22 (pre-committed; cancelled FII/DII still counted per §17 ADDENDUM)
**Survivors (all 5 gates):** 0
**Conditional (Gates 1-4 pass, Gate 5 fail):** 0

## Substrate #6 (India) — CLOSED FAILED at Phase 3

0 trials pass all 5 gates and 0 trials pass even the first four. Substrate is closed per §12.

## Per-trial gauntlet outcomes

| Trial | Family | G1 DSR | G2 CI | G3 Sign | G4 Cost | G5 Regime | Verdict |
|---|---|:-:|:-:|:-:|:-:|:-:|---|
| `deliv_pct_L10_Q5_H5` | delivery_pct | ✗ | ✓ | ✗ | ✗ | ✗ | FAIL |
| `deliv_pct_L10_Q5_H10` | delivery_pct | ✗ | ✓ | ✗ | ✗ | ✗ | FAIL |
| `deliv_pct_L10_Q5_H21` | delivery_pct | ✗ | ✓ | ✗ | ✗ | ✗ | FAIL |
| `deliv_pct_L10_Q10_H5` | delivery_pct | ✗ | ✓ | ✗ | ✗ | ✗ | FAIL |
| `deliv_pct_L10_Q10_H10` | delivery_pct | ✗ | ✓ | ✗ | ✗ | ✗ | FAIL |
| `deliv_pct_L10_Q10_H21` | delivery_pct | ✗ | ✗ | ✗ | ✗ | ✗ | FAIL |
| `deliv_pct_L20_Q5_H5` | delivery_pct | ✗ | ✓ | ✗ | ✗ | ✗ | FAIL |
| `deliv_pct_L20_Q5_H10` | delivery_pct | ✗ | ✓ | ✗ | ✗ | ✗ | FAIL |
| `deliv_pct_L20_Q5_H21` | delivery_pct | ✗ | ✗ | ✗ | ✗ | ✗ | FAIL |
| `deliv_pct_L20_Q10_H5` | delivery_pct | ✗ | ✓ | ✗ | ✗ | ✗ | FAIL |
| `deliv_pct_L20_Q10_H10` | delivery_pct | ✗ | ✓ | ✗ | ✗ | ✗ | FAIL |
| `deliv_pct_L20_Q10_H21` | delivery_pct | ✗ | ✗ | ✗ | ✗ | ✗ | FAIL |
| `deliv_pct_L60_Q5_H5` | delivery_pct | ✗ | ✓ | ✗ | ✗ | ✗ | FAIL |
| `deliv_pct_L60_Q5_H10` | delivery_pct | ✗ | ✓ | ✗ | ✗ | ✗ | FAIL |
| `deliv_pct_L60_Q5_H21` | delivery_pct | ✗ | ✗ | ✗ | ✗ | ✗ | FAIL |
| `deliv_pct_L60_Q10_H5` | delivery_pct | ✗ | ✓ | ✗ | ✗ | ✗ | FAIL |
| `deliv_pct_L60_Q10_H10` | delivery_pct | ✗ | ✓ | ✗ | ✗ | ✗ | FAIL |
| `deliv_pct_L60_Q10_H21` | delivery_pct | ✗ | ✗ | ✗ | ✗ | ✗ | FAIL |
| `fo_expiry_pre3_post3` | fo_expiry | — | — | — | — | — | SKIPPED: F&O Phase 3 daily-return construction re |
| `fo_expiry_pre3_post5` | fo_expiry | — | — | — | — | — | SKIPPED: F&O Phase 3 daily-return construction re |
| `fo_expiry_pre5_post3` | fo_expiry | — | — | — | — | — | SKIPPED: F&O Phase 3 daily-return construction re |
| `fo_expiry_pre5_post5` | fo_expiry | — | — | — | — | — | SKIPPED: F&O Phase 3 daily-return construction re |

## Per-trial gate detail

### `deliv_pct_L10_Q5_H5`
- **1_DSR** ✗ — DSR_A=0.0000 (SR=-4.798), DSR_B=0.0000 (SR=-4.366), threshold=0.95
- **2_Bootstrap_CI** ✓ — OOS-A CI=[-5.673, -3.994] excl 0, OOS-B CI=[-5.191, -3.557] excl 0
- **3_Sign_Agreement** ✗ — SR_A=-4.798, SR_B=-4.366 — sign disagreement
- **4_Cost_Survival** ✗ — Stressed SR_A=-4.878, SR_B=-4.441 (2× costs: 71.8bp RT + 20.0bp impact)
- **5_Regime_Stress** ✗ — 4-of-4 required: 2008_crisis: SR=0.000 pos_months=0.0% ✗; 2013_taper_tantrum: SR=0.000 pos_months=0.0% ✗; 2020_covid: SR=-2.661 pos_months=36.4% ✗; 2022_rate_cycle: SR=-6.648 pos_months=0.0% ✗

### `deliv_pct_L10_Q5_H10`
- **1_DSR** ✗ — DSR_A=0.0000 (SR=-2.639), DSR_B=0.0000 (SR=-2.273), threshold=0.95
- **2_Bootstrap_CI** ✓ — OOS-A CI=[-3.472, -1.841] excl 0, OOS-B CI=[-3.135, -1.366] excl 0
- **3_Sign_Agreement** ✗ — SR_A=-2.639, SR_B=-2.273 — sign disagreement
- **4_Cost_Survival** ✗ — Stressed SR_A=-2.727, SR_B=-2.356 (2× costs: 71.8bp RT + 20.0bp impact)
- **5_Regime_Stress** ✗ — 4-of-4 required: 2008_crisis: SR=0.000 pos_months=0.0% ✗; 2013_taper_tantrum: SR=0.000 pos_months=0.0% ✗; 2020_covid: SR=-0.976 pos_months=54.5% ✗; 2022_rate_cycle: SR=-4.492 pos_months=16.7% ✗

### `deliv_pct_L10_Q5_H21`
- **1_DSR** ✗ — DSR_A=0.0000 (SR=-1.235), DSR_B=0.0000 (SR=-1.108), threshold=0.95
- **2_Bootstrap_CI** ✓ — OOS-A CI=[-2.092, -0.402] excl 0, OOS-B CI=[-2.113, -0.034] excl 0
- **3_Sign_Agreement** ✗ — SR_A=-1.235, SR_B=-1.108 — sign disagreement
- **4_Cost_Survival** ✗ — Stressed SR_A=-1.327, SR_B=-1.198 (2× costs: 71.8bp RT + 20.0bp impact)
- **5_Regime_Stress** ✗ — 4-of-4 required: 2008_crisis: SR=0.000 pos_months=0.0% ✗; 2013_taper_tantrum: SR=0.000 pos_months=0.0% ✗; 2020_covid: SR=-0.819 pos_months=54.5% ✗; 2022_rate_cycle: SR=-2.137 pos_months=33.3% ✗

### `deliv_pct_L10_Q10_H5`
- **1_DSR** ✗ — DSR_A=0.0000 (SR=-3.872), DSR_B=0.0000 (SR=-3.244), threshold=0.95
- **2_Bootstrap_CI** ✓ — OOS-A CI=[-4.778, -3.042] excl 0, OOS-B CI=[-4.000, -2.461] excl 0
- **3_Sign_Agreement** ✗ — SR_A=-3.872, SR_B=-3.244 — sign disagreement
- **4_Cost_Survival** ✗ — Stressed SR_A=-3.938, SR_B=-3.307 (2× costs: 71.8bp RT + 20.0bp impact)
- **5_Regime_Stress** ✗ — 4-of-4 required: 2008_crisis: SR=0.000 pos_months=0.0% ✗; 2013_taper_tantrum: SR=0.000 pos_months=0.0% ✗; 2020_covid: SR=-1.948 pos_months=54.5% ✗; 2022_rate_cycle: SR=-5.299 pos_months=0.0% ✗

### `deliv_pct_L10_Q10_H10`
- **1_DSR** ✗ — DSR_A=0.0000 (SR=-1.969), DSR_B=0.0000 (SR=-1.561), threshold=0.95
- **2_Bootstrap_CI** ✓ — OOS-A CI=[-2.876, -1.124] excl 0, OOS-B CI=[-2.341, -0.733] excl 0
- **3_Sign_Agreement** ✗ — SR_A=-1.969, SR_B=-1.561 — sign disagreement
- **4_Cost_Survival** ✗ — Stressed SR_A=-2.038, SR_B=-1.626 (2× costs: 71.8bp RT + 20.0bp impact)
- **5_Regime_Stress** ✗ — 4-of-4 required: 2008_crisis: SR=0.000 pos_months=0.0% ✗; 2013_taper_tantrum: SR=0.000 pos_months=0.0% ✗; 2020_covid: SR=-0.657 pos_months=63.6% ✗; 2022_rate_cycle: SR=-3.354 pos_months=16.7% ✗

### `deliv_pct_L10_Q10_H21`
- **1_DSR** ✗ — DSR_A=0.0000 (SR=-1.320), DSR_B=0.0000 (SR=-0.648), threshold=0.95
- **2_Bootstrap_CI** ✗ — OOS-A CI=[-2.251, -0.435] excl 0, OOS-B CI=[-1.582, 0.359] incl 0
- **3_Sign_Agreement** ✗ — SR_A=-1.320, SR_B=-0.648 — sign disagreement
- **4_Cost_Survival** ✗ — Stressed SR_A=-1.393, SR_B=-0.718 (2× costs: 71.8bp RT + 20.0bp impact)
- **5_Regime_Stress** ✗ — 4-of-4 required: 2008_crisis: SR=0.000 pos_months=0.0% ✗; 2013_taper_tantrum: SR=0.000 pos_months=0.0% ✗; 2020_covid: SR=-0.717 pos_months=45.5% ✗; 2022_rate_cycle: SR=-1.556 pos_months=33.3% ✗

### `deliv_pct_L20_Q5_H5`
- **1_DSR** ✗ — DSR_A=0.0000 (SR=-4.938), DSR_B=0.0000 (SR=-4.410), threshold=0.95
- **2_Bootstrap_CI** ✓ — OOS-A CI=[-5.801, -4.156] excl 0, OOS-B CI=[-5.256, -3.542] excl 0
- **3_Sign_Agreement** ✗ — SR_A=-4.938, SR_B=-4.410 — sign disagreement
- **4_Cost_Survival** ✗ — Stressed SR_A=-5.018, SR_B=-4.486 (2× costs: 71.8bp RT + 20.0bp impact)
- **5_Regime_Stress** ✗ — 4-of-4 required: 2008_crisis: SR=0.000 pos_months=0.0% ✗; 2013_taper_tantrum: SR=0.000 pos_months=0.0% ✗; 2020_covid: SR=-2.577 pos_months=27.3% ✗; 2022_rate_cycle: SR=-6.293 pos_months=0.0% ✗

### `deliv_pct_L20_Q5_H10`
- **1_DSR** ✗ — DSR_A=0.0000 (SR=-2.648), DSR_B=0.0000 (SR=-2.365), threshold=0.95
- **2_Bootstrap_CI** ✓ — OOS-A CI=[-3.519, -1.844] excl 0, OOS-B CI=[-3.208, -1.428] excl 0
- **3_Sign_Agreement** ✗ — SR_A=-2.648, SR_B=-2.365 — sign disagreement
- **4_Cost_Survival** ✗ — Stressed SR_A=-2.736, SR_B=-2.449 (2× costs: 71.8bp RT + 20.0bp impact)
- **5_Regime_Stress** ✗ — 4-of-4 required: 2008_crisis: SR=0.000 pos_months=0.0% ✗; 2013_taper_tantrum: SR=0.000 pos_months=0.0% ✗; 2020_covid: SR=-1.164 pos_months=45.5% ✗; 2022_rate_cycle: SR=-3.841 pos_months=16.7% ✗

### `deliv_pct_L20_Q5_H21`
- **1_DSR** ✗ — DSR_A=0.0000 (SR=-1.369), DSR_B=0.0000 (SR=-0.995), threshold=0.95
- **2_Bootstrap_CI** ✗ — OOS-A CI=[-2.240, -0.550] excl 0, OOS-B CI=[-1.984, 0.063] incl 0
- **3_Sign_Agreement** ✗ — SR_A=-1.369, SR_B=-0.995 — sign disagreement
- **4_Cost_Survival** ✗ — Stressed SR_A=-1.460, SR_B=-1.083 (2× costs: 71.8bp RT + 20.0bp impact)
- **5_Regime_Stress** ✗ — 4-of-4 required: 2008_crisis: SR=0.000 pos_months=0.0% ✗; 2013_taper_tantrum: SR=0.000 pos_months=0.0% ✗; 2020_covid: SR=-0.393 pos_months=54.5% ✗; 2022_rate_cycle: SR=-2.380 pos_months=33.3% ✗

### `deliv_pct_L20_Q10_H5`
- **1_DSR** ✗ — DSR_A=0.0000 (SR=-3.995), DSR_B=0.0000 (SR=-3.344), threshold=0.95
- **2_Bootstrap_CI** ✓ — OOS-A CI=[-4.886, -3.210] excl 0, OOS-B CI=[-4.093, -2.558] excl 0
- **3_Sign_Agreement** ✗ — SR_A=-3.995, SR_B=-3.344 — sign disagreement
- **4_Cost_Survival** ✗ — Stressed SR_A=-4.061, SR_B=-3.407 (2× costs: 71.8bp RT + 20.0bp impact)
- **5_Regime_Stress** ✗ — 4-of-4 required: 2008_crisis: SR=0.000 pos_months=0.0% ✗; 2013_taper_tantrum: SR=0.000 pos_months=0.0% ✗; 2020_covid: SR=-2.145 pos_months=45.5% ✗; 2022_rate_cycle: SR=-4.700 pos_months=8.3% ✗

### `deliv_pct_L20_Q10_H10`
- **1_DSR** ✗ — DSR_A=0.0000 (SR=-2.090), DSR_B=0.0000 (SR=-1.654), threshold=0.95
- **2_Bootstrap_CI** ✓ — OOS-A CI=[-2.990, -1.257] excl 0, OOS-B CI=[-2.496, -0.754] excl 0
- **3_Sign_Agreement** ✗ — SR_A=-2.090, SR_B=-1.654 — sign disagreement
- **4_Cost_Survival** ✗ — Stressed SR_A=-2.158, SR_B=-1.720 (2× costs: 71.8bp RT + 20.0bp impact)
- **5_Regime_Stress** ✗ — 4-of-4 required: 2008_crisis: SR=0.000 pos_months=0.0% ✗; 2013_taper_tantrum: SR=0.000 pos_months=0.0% ✗; 2020_covid: SR=-0.756 pos_months=54.5% ✗; 2022_rate_cycle: SR=-2.795 pos_months=33.3% ✗

### `deliv_pct_L20_Q10_H21`
- **1_DSR** ✗ — DSR_A=0.0000 (SR=-1.063), DSR_B=0.0000 (SR=-0.695), threshold=0.95
- **2_Bootstrap_CI** ✗ — OOS-A CI=[-1.917, -0.261] excl 0, OOS-B CI=[-1.625, 0.318] incl 0
- **3_Sign_Agreement** ✗ — SR_A=-1.063, SR_B=-0.695 — sign disagreement
- **4_Cost_Survival** ✗ — Stressed SR_A=-1.134, SR_B=-0.764 (2× costs: 71.8bp RT + 20.0bp impact)
- **5_Regime_Stress** ✗ — 4-of-4 required: 2008_crisis: SR=0.000 pos_months=0.0% ✗; 2013_taper_tantrum: SR=0.000 pos_months=0.0% ✗; 2020_covid: SR=-0.727 pos_months=63.6% ✗; 2022_rate_cycle: SR=-1.681 pos_months=33.3% ✗

### `deliv_pct_L60_Q5_H5`
- **1_DSR** ✗ — DSR_A=0.0000 (SR=-4.939), DSR_B=0.0000 (SR=-4.413), threshold=0.95
- **2_Bootstrap_CI** ✓ — OOS-A CI=[-5.790, -4.165] excl 0, OOS-B CI=[-5.235, -3.578] excl 0
- **3_Sign_Agreement** ✗ — SR_A=-4.939, SR_B=-4.413 — sign disagreement
- **4_Cost_Survival** ✗ — Stressed SR_A=-5.018, SR_B=-4.490 (2× costs: 71.8bp RT + 20.0bp impact)
- **5_Regime_Stress** ✗ — 4-of-4 required: 2008_crisis: SR=0.000 pos_months=0.0% ✗; 2013_taper_tantrum: SR=0.000 pos_months=0.0% ✗; 2020_covid: SR=-2.684 pos_months=36.4% ✗; 2022_rate_cycle: SR=-6.039 pos_months=0.0% ✗

### `deliv_pct_L60_Q5_H10`
- **1_DSR** ✗ — DSR_A=0.0000 (SR=-2.657), DSR_B=0.0000 (SR=-2.201), threshold=0.95
- **2_Bootstrap_CI** ✓ — OOS-A CI=[-3.517, -1.848] excl 0, OOS-B CI=[-3.091, -1.295] excl 0
- **3_Sign_Agreement** ✗ — SR_A=-2.657, SR_B=-2.201 — sign disagreement
- **4_Cost_Survival** ✗ — Stressed SR_A=-2.743, SR_B=-2.284 (2× costs: 71.8bp RT + 20.0bp impact)
- **5_Regime_Stress** ✗ — 4-of-4 required: 2008_crisis: SR=0.000 pos_months=0.0% ✗; 2013_taper_tantrum: SR=0.000 pos_months=0.0% ✗; 2020_covid: SR=-0.833 pos_months=45.5% ✗; 2022_rate_cycle: SR=-3.735 pos_months=8.3% ✗

### `deliv_pct_L60_Q5_H21`
- **1_DSR** ✗ — DSR_A=0.0000 (SR=-1.350), DSR_B=0.0000 (SR=-0.861), threshold=0.95
- **2_Bootstrap_CI** ✗ — OOS-A CI=[-2.179, -0.538] excl 0, OOS-B CI=[-1.833, 0.146] incl 0
- **3_Sign_Agreement** ✗ — SR_A=-1.350, SR_B=-0.861 — sign disagreement
- **4_Cost_Survival** ✗ — Stressed SR_A=-1.440, SR_B=-0.950 (2× costs: 71.8bp RT + 20.0bp impact)
- **5_Regime_Stress** ✗ — 4-of-4 required: 2008_crisis: SR=0.000 pos_months=0.0% ✗; 2013_taper_tantrum: SR=0.000 pos_months=0.0% ✗; 2020_covid: SR=-0.204 pos_months=45.5% ✗; 2022_rate_cycle: SR=-1.606 pos_months=41.7% ✗

### `deliv_pct_L60_Q10_H5`
- **1_DSR** ✗ — DSR_A=0.0000 (SR=-3.980), DSR_B=0.0000 (SR=-3.352), threshold=0.95
- **2_Bootstrap_CI** ✓ — OOS-A CI=[-4.895, -3.130] excl 0, OOS-B CI=[-4.204, -2.497] excl 0
- **3_Sign_Agreement** ✗ — SR_A=-3.980, SR_B=-3.352 — sign disagreement
- **4_Cost_Survival** ✗ — Stressed SR_A=-4.044, SR_B=-3.415 (2× costs: 71.8bp RT + 20.0bp impact)
- **5_Regime_Stress** ✗ — 4-of-4 required: 2008_crisis: SR=0.000 pos_months=0.0% ✗; 2013_taper_tantrum: SR=0.000 pos_months=0.0% ✗; 2020_covid: SR=-1.523 pos_months=36.4% ✗; 2022_rate_cycle: SR=-4.921 pos_months=0.0% ✗

### `deliv_pct_L60_Q10_H10`
- **1_DSR** ✗ — DSR_A=0.0000 (SR=-2.111), DSR_B=0.0000 (SR=-1.632), threshold=0.95
- **2_Bootstrap_CI** ✓ — OOS-A CI=[-3.013, -1.236] excl 0, OOS-B CI=[-2.510, -0.733] excl 0
- **3_Sign_Agreement** ✗ — SR_A=-2.111, SR_B=-1.632 — sign disagreement
- **4_Cost_Survival** ✗ — Stressed SR_A=-2.179, SR_B=-1.698 (2× costs: 71.8bp RT + 20.0bp impact)
- **5_Regime_Stress** ✗ — 4-of-4 required: 2008_crisis: SR=0.000 pos_months=0.0% ✗; 2013_taper_tantrum: SR=0.000 pos_months=0.0% ✗; 2020_covid: SR=0.100 pos_months=54.5% ✗; 2022_rate_cycle: SR=-2.868 pos_months=16.7% ✗

### `deliv_pct_L60_Q10_H21`
- **1_DSR** ✗ — DSR_A=0.0000 (SR=-0.945), DSR_B=0.0000 (SR=-0.620), threshold=0.95
- **2_Bootstrap_CI** ✗ — OOS-A CI=[-1.817, -0.086] excl 0, OOS-B CI=[-1.563, 0.375] incl 0
- **3_Sign_Agreement** ✗ — SR_A=-0.945, SR_B=-0.620 — sign disagreement
- **4_Cost_Survival** ✗ — Stressed SR_A=-1.013, SR_B=-0.689 (2× costs: 71.8bp RT + 20.0bp impact)
- **5_Regime_Stress** ✗ — 4-of-4 required: 2008_crisis: SR=0.000 pos_months=0.0% ✗; 2013_taper_tantrum: SR=0.000 pos_months=0.0% ✗; 2020_covid: SR=0.343 pos_months=63.6% ✓; 2022_rate_cycle: SR=-0.926 pos_months=33.3% ✗
