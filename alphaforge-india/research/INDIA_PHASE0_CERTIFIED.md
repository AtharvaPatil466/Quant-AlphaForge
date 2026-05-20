# Phase 0 Certification: INCOMPLETE

**Date:** 2026-05-20
**Design Document SHA-256:** `3b397262d5799f7fe6b583b9c97d8eee6d07852611ec8c046a7c717ca1b031b9`

## Exit Criteria Checklist

| Gate | Requirement | Status | Details |
|------|-------------|--------|---------|
| 1. Nifty 500 TRI Correlation | ρ ≥ 0.98 | ⏭️ SKIP | Awaiting full bhavcopy download and TRI index data. |
| 2. Two-Era Bhavcopy Loader | 2004→present Parquet | ❌ FAIL | Missing parquet files for years: [2013, 2014, 2015, 2016, 2017, 2018, 2019] |
| 3. SERIES=EQ Filter | Non-EQ quarantined | ✅ PASS | SERIES=EQ filter enforced at ingest time; non-EQ rows quarantined. |
| 4. ISIN Master & Rename Graph | ≥10 hand-verified renames | ✅ PASS | Validated by test_isin_master.py (107 tests passing, covering historical rename chains). |
| 5. FII/DII Daily Series | CANCELLED | ⏭️ SKIP | CANCELLED per 2026-05-19 ADDENDUM. |
| 6. F&O Expiry Calendar | 0 errors on 50+ dates | ⏭️ SKIP | Awaiting holiday calendar resolution to generate expiry calendar. |
| 7. Holiday Calendar | Empirical cross-check | ⏭️ SKIP | Holiday log exists but cross-check not yet implemented. |
| 8. Delivery % Coverage | ≥ 95% of EQ rows | ⏭️ SKIP | Awaiting full bhavcopy download. |

## Summary
- PASS: 2
- FAIL: 1
- SKIP: 5