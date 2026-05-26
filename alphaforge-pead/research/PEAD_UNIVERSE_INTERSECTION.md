# PEAD Universe Intersection Report

Eligibility filter from `research/PEAD_DESIGN.md` §2.4:

- PIT membership × XBRL availability × OHLCV coverage × ≥8 quarters

## Headline counts

| Filter | Firm count |
|---|---:|
| PIT universe (total) | 771 |
| Has XBRL coverage (Company Facts JSON returned) | 747 |
| Has OHLCV parquet on disk | 654 |
| Has BOTH XBRL and OHLCV | 634 |
| Has ≥8 quarters of clean Diluted-continuing EPS | 723 |
| **Eligible (all four filters)** | **614** |

**Total eligible firm-quarters: 26,908.**

## Exclusion-reason breakdown

Mutually exclusive, evaluated in order: no_xbrl_coverage → no_ohlcv_coverage → under_min_quarters → eligible.

| Reason | Count |
|---|---:|
| no_xbrl_coverage | 24 |
| eligible | 614 |
| no_ohlcv_coverage | 113 |
| under_min_quarters(8) | 20 |

## Substitution rate (Diluted-continuing → Diluted fallback)

- Primary concept rows: 6,305
- Fallback concept rows: 20,603
- Substitution rate: **76.57%**

(Pre-committed acceptable bound: <15%. See `PEAD_DESIGN.md` §2.3.)

## Eligible sample (first 20)

| CIK | Ticker | Quarters |
|---|---|---:|
| 0000001800 | ABT | 51 |
| 0000002488 | AMD | 51 |
| 0000002969 | APD | 52 |
| 0000004127 | SWKS | 50 |
| 0000004904 | AEP | 50 |
| 0000004962 | AXP | 45 |
| 0000004977 | AFL | 54 |
| 0000005272 | AIG | 53 |
| 0000005513 | UNM | 52 |
| 0000006201 | AAL | 51 |
| 0000006281 | ADI | 41 |
| 0000006769 | APA | 33 |
| 0000006951 | AMAT | 50 |
| 0000007084 | ADM | 54 |
| 0000008670 | ADP | 52 |
| 0000009389 | BALL | 55 |
| 0000010456 | BAX | 53 |
| 0000010795 | BDX | 49 |
| 0000011199 | AMCR | 28 |
| 0000011544 | WRB | 51 |
