# Corwin-Schultz Calibration — DIVERGENCE FLAGGED (1 window(s) > 10 bp)

_Generated 2026-05-20T08:23:33Z_

**Sample size:** 50 symbols (seed=20260518)
**Parametric half-spread (§6):** 5.0 bp
**Divergence-document threshold (§6):** 10.0 bp

## Per-window summary

| Window | Dates | N with data | Median (bp) | P25 | P75 | Mean | vs §6 5bp | vs 10bp |
|---|---|---:|---:|---:|---:|---:|---|---|
| IS | 2004-01-01 → 2014-12-31 | 30 | **7.09** | 0.00 | 17.21 | 15.41 | ABOVE | below |
| OOS_A | 2015-01-01 → 2019-12-31 | 30 | **20.41** | 4.27 | 28.30 | 21.27 | ABOVE | ABOVE ⚠ |
| OOS_B | 2020-01-01 → 2026-05-18 | 35 | **7.32** | 0.00 | 14.37 | 10.81 | ABOVE | below |

## §6 Documentation Discipline

Per `INDIA_DESIGN.md` §6:

> If Corwin-Schultz shows median > 10 bp on Nifty 500 names, document the divergence the same way Tier 2 documented the 2 bp vs 7-8 bp gap. **Do not recalibrate mid-research** — document and proceed.

Affected windows:
- **OOS_A** (2015-01-01 → 2019-12-31): median 20.41 bp vs parametric 5.0 bp = 4.1× higher

This DIVERGENCE is recorded as documented finding under §14 known limitations. The gauntlet cost model (§6) is **not** modified — §15 hard rules freeze the cost numbers. The cost-doubling Gate 4 stress is the intended robustness check against this risk.

## Sample symbols

50 symbols, seeded so re-runs reproduce: `63MOONS, AAVAS, ADFFOODS, AFTEKINFO, AHMEDFORGE, AJANTPHARM, AJMERA, ALCHEM, AUROPHARMA, BRIGADE` ...