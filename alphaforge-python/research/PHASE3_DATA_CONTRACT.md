# Phase 3 Data Contract

Phase 3 is blocked on two local input files. The code is already in the repo; what remains is staging these files under the contracts below and then running the validation gate.

## Required files

1. Daily reference factor table for `MKT`, `SMB`, `HML`, `RMW`, `CMA`, `UMD`
2. Monthly characteristics table for `market_cap`, `book_to_market`, `profitability`, `investment`

Both files must be local. Nothing in the Phase 3 path fetches these from the network.

## Reference factor file

Accepted formats:
- `.csv`
- `.parquet`

Required columns after normalization:
- `date`
- `MKT`
- `SMB`
- `HML`
- `RMW`
- `CMA`
- `UMD`

Notes:
- Returns must be daily decimal returns, not percentages.
- `MKT-RF` and `MKT_RF` are accepted aliases and normalize to `MKT`.
- The loader accepts either a `date` column or a datetime index.
- Dates are normalized to midnight and timezone stripped.

Header-only template:
- [phase3_reference_template.csv](/Users/atharva/Quant%20Projects/Quant%20Alpha/alphaforge-python/research/templates/phase3_reference_template.csv)

Example:

```csv
date,MKT,SMB,HML,RMW,CMA,UMD
2016-01-04,-0.0152,0.0011,0.0042,-0.0021,0.0007,-0.0035
2016-01-05,0.0029,-0.0004,0.0018,0.0005,-0.0012,0.0021
```

## Characteristics file

Accepted formats:
- `.csv`
- `.parquet`

Required columns after normalization:
- `date`
- `ticker`
- `market_cap`
- `book_to_market`
- `profitability`
- `investment`

Accepted aliases:
- `mkt_cap`, `marketcap`, `size` → `market_cap`
- `book_to_market_ratio`, `bm`, `btm` → `book_to_market`
- `operating_profitability`, `op` → `profitability`
- `asset_growth`, `inv` → `investment`

Notes:
- This is a monthly table, not daily.
- Characteristics are lagged by one rebalance inside the replica builder.
- `ticker` is uppercased by the loader.
- Numeric fields are coerced with `to_numeric(errors="coerce")`, so malformed strings silently become `NaN` and then drop usable coverage.

Header-only template:
- [phase3_characteristics_template.csv](/Users/atharva/Quant%20Projects/Quant%20Alpha/alphaforge-python/research/templates/phase3_characteristics_template.csv)

Example:

```csv
date,ticker,market_cap,book_to_market,profitability,investment
2015-12-31,AAPL,605000000000,0.82,0.218,0.041
2015-12-31,MSFT,439000000000,0.71,0.194,0.037
```

## Validation command

Run from `alphaforge-python/`:

If the raw local files are messy, first normalize them into the canonical
Phase 3 schema:

```bash
python3 research/phase3_stage_inputs.py \
  --reference-in /path/to/raw_reference.csv \
  --characteristics-in /path/to/raw_characteristics.csv
```

Default outputs:
- `research/out/phase3_reference_staged.csv`
- `research/out/phase3_characteristics_staged.csv`

Then sanity-check the staged files:

```bash
python3 research/phase3_check_inputs.py \
  --reference research/out/phase3_reference_staged.csv \
  --characteristics research/out/phase3_characteristics_staged.csv
```

This is the staging sanity check. It validates the local file contracts,
prints date coverage / duplicate / missing-value summaries, and catches
obvious unit mistakes before the full overlap run.

Then run:

```bash
python3 research/phase3_validate_ff5.py \
  --reference research/out/phase3_reference_staged.csv \
  --characteristics research/out/phase3_characteristics_staged.csv
```

The script writes:
- `research/out/phase3_ff5_validation.json`

The gate is:
- every factor among `MKT/SMB/HML/RMW/CMA/UMD` must clear correlation `> 0.85`

If any factor is below `0.85`, Phase 4 is blocked.

## Next command after pass

```bash
ALPHAFORGE_FACTOR_STUDY_RESIDUALIZE=1 \
ALPHAFORGE_REFERENCE_FACTORS=/path/to/reference.csv \
python3 research/factor_study.py
```
