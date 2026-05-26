# Phase 0 Validation — CERTIFIED

_Generated 2026-05-21T00:47:57Z_
_VIX_DESIGN.md SHA-256: `54e53be92f72e5161a4478cb8e518955d08164bfad0057675278fa2c49367b29`_
_Re-anchored 2026-05-21 after §17.8 ADDENDUM (Phase 3 cash-carry zeroing). Phase 0 PASS/SKIP set unchanged — Phase 0 validates data availability, not signal definitions._
_Prior anchors: `22d468ce...` (initial), `56d745e7...` (post-§17 ADDENDUM), `66a6c45a...` (post-§17.7 ADDENDUM)._

## Summary

- **PASS**: 5
- **WARN**: 0
- **FAIL**: 0
- **SKIP**: 2

## Per-check detail

### term_structure — `PASS`
5/5 indices present, first dates as expected

Metrics:
  - `first_dates`: {'VIX': '1990-01-02', 'VIX1D': '2022-05-13', 'VIX3M': '2009-09-18', 'VIX6M': '2008-01-02', 'VIX9D': '2011-01-04'}
  - `last_date`: 2026-05-19
  - `rows`: 9188

### spy_spike_events — `PASS`
5/5 known volatility-event spikes captured (all PASS)

Metrics:
  - `n_passed`: 5
  - `n_total`: 5
  - `per_spike`: <list of len 5>

### etp_availability — `PASS`
SVXY + VXX coverage as expected per §17 ADDENDUM

Metrics:
  - `svxy_first`: 2011-10-04
  - `svxy_last`: 2026-05-20
  - `svxy_rows`: 3678
  - `svxy_pre_restructuring_rows`: 1609
  - `svxy_post_restructuring_rows`: 2069
  - `vxx_first`: 2018-01-25
  - `vxx_last`: 2026-05-20
  - `vxx_rows`: 2091

### vix_cross_consistency — `PASS`
correlation = 1.0000 over 9158 dates (threshold 0.99)

Metrics:
  - `n_overlap`: 9158
  - `correlation`: 0.999992413726202

### contango_bias — `PASS`
VIX3M ≥ VIX on 92.3% of 4192 days (threshold 70%)

Metrics:
  - `n_overlap`: 4192
  - `contango_fraction`: 0.9227099236641222

### vix_futures_settlements — `SKIP`
REMOVED per §17 ADDENDUM (CBOE moved to paid DataShop).

### fred_dgs3mo — `SKIP`
Optional. May time out from some networks. Falls back to constant rates per §14.7.
