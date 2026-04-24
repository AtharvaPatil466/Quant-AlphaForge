# AlphaForge

A quantitative research platform for cross-sectional and portfolio-level
equity signals. Built as a disciplined end-to-end pipeline — data ingest,
factor/strategy research, deflation-aware statistical evaluation, honest
cost modeling, and a paper-trading execution loop — on a 50-ticker US
large-cap universe (2016-2025).

The goal is an **honest research artifact**: not to claim alpha that is
not there, but to demonstrate the methodology a quant researcher should
apply before claiming it.

See [`RESEARCH_WRITEUP.md`](RESEARCH_WRITEUP.md) for the full narrative.

---

## Quickstart

```bash
git clone <this-repo> alphaforge && cd alphaforge

# Install each sub-project's deps
cd alphaforge-python   && pip install -r requirements.txt && cd ..
cd alphaforge-marl     && pip install -r requirements.txt && cd ..
cd alphaforge-execution && pip install -r requirements.txt && cd ..

# Run the full test matrix (~690 tests)
make tests

# Populate the market-data parquet store from yfinance (one-off, ~15 min)
cd alphaforge-python && python3 sync_market_data.py && cd ..

# Rebuild every headline research report
make all
```

Headline reports land in `alphaforge-python/research/out/`,
`alphaforge-marl/research/out/`, and `alphaforge-execution/research/out/`.

---

## Repo layout

```
alphaforge-python/     # Research engine — data, factors, backtest, optimizer
  data/market/         #   Parquet store (gitignored — regenerable)
  factors/             #   11 factor implementations
  strategies/          #   Portfolio-level strategies (TSMOM, pairs)
  research/            #   Honest-costs research scripts + reports
  backtest/ optimizer/ scanner/ correlation/

alphaforge-marl/       # Multi-agent RL — NSGA-II + PPO + MAML + HMM bandit
  env/ agents/ evolution/ bandit/ training/
  research/            #   marl_rigor.py, ablation_ladder.py

alphaforge-execution/  # Live paper trading system
  execution/ strategy/ risk/ portfolio/ storage/
  research/            #   slippage_reconciliation.py

index.html + *.js      # Vanilla JS frontend, no build step

Makefile               # make factor-study | capacity-study | tsmom-study |
                       #      pairs-study | marl-rigor | ablation-ladder | all

RESEARCH_WRITEUP.md    # Full research narrative
SEEDS.md               # Per-component deterministic seed manifest
.github/workflows/     # CI: test matrix + headline-metric drift diff
```

Each sub-project has its own `CLAUDE.md` / `AGENTS.md` with detailed
architecture notes.

---

## What is implemented

### Research methodology

- **11 cross-sectional factors**: Momentum (12-1), Mean Reversion (5d),
  Volume Surge, RSI Divergence, Earnings Drift, Low Volatility,
  Amihud Illiquidity, Idiosyncratic Volatility, Residual Reversal (5d),
  Risk-Managed Momentum, Long-Horizon Reversal.
- **2 portfolio strategies**: Time-Series Momentum (Moskowitz-Ooi-Pedersen),
  cointegration-based Pairs Trading (Engle-Granger).
- **Honest cost model**: square-root market impact (k · √participation),
  Corwin-Schultz bid-ask spread, annualized borrow fee with HTB overrides.
- **Deflation-aware stats**: Deflated Sharpe Ratio (Bailey-López de Prado),
  Hansen SPA, White's Reality Check, purged + embargoed k-fold CV
  (López de Prado).
- **Sector-neutral variant** and **held-out OOS window** (2024-2025 with
  21-day embargo) run alongside every factor.
- **Capacity curve** under the square-root impact model; regime-conditional
  Sharpe; OHLCV-only crowding proxies.

### MARL evaluation

- Walk-forward validation on real data with strict temporal isolation.
- `marl_rigor.py` deflates Sharpe against the full search history.
- `ablation_ladder.py` runs paired stationary-bootstrap Sharpe-difference
  tests across configurations (equal-weight / single-agent PPO /
  MARL variants).

### Execution

- Paper broker (local) and Alpaca broker (live paper).
- Full kill-switch: 6 triggers (max DD, single-day loss, consecutive
  losing days, realized slippage median, cumulative fill-error drag,
  minimum liquid tickers) + 3-stage unwind ladder + pager file with
  operator `ACK:` re-arm.
- Slippage reconciliation: realized-vs-simulated fill-error reporting
  with self-contained KS test and cumulative NAV drag.

### Reproducibility

- Every headline artifact regenerable via `make`.
- Per-component deterministic seeds documented in [`SEEDS.md`](SEEDS.md).
- GitHub Actions: test matrix + headline-metric drift diff on every push.

---

## Honest limitations

The writeup's § 6 has the full list. The big ones:

- **Survivorship bias**: today's surviving large-caps, not point-in-time.
- **Small universe**: 50 tickers → quintile buckets of 10 names.
- **No borrow-fee heterogeneity**: flat 25 bp/yr general-collateral.
- **No TAQ-calibrated impact**: square-root k = 15 bps is a literature default.
- **No fundamentals**: value/quality approximated from OHLCV only.
- **Results not yet produced on live-synced data**: the framework is
  complete; `make all` must be run to populate the writeup with real
  numbers.

These are explicitly called out, not hidden. Fixing them requires data
subscriptions (CRSP/Norgate, IBKR stock loan, TAQ) that are outside the
scope of a public repo.

---

## Not financial advice

This is a research project, not a trading recommendation. Live paper
trading in `alphaforge-execution` is for methodology validation only.
See [`LICENSE`](LICENSE) for the full disclaimer.
