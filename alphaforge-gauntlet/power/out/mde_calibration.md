# Gauntlet Power Calibration — Minimum Detectable Effect

Noise substrate: **SPY adj_close (8383 days, real)**. Monte-Carlo reps: 300; bootstrap reps: 250.

Each row injects a constant drift onto block-bootstrapped real return
noise so the *population* annualized Sharpe equals the target, then runs
the canonical detection gauntlet (DSR>0.95 + bootstrap-CI excludes zero +
sign agreement, in BOTH OOS windows) and records the detection rate.

## Minimum detectable true annualized Sharpe

| Config | N trials | OOS len (each) | MDE@50% power | MDE@80% power |
|--------|----------|----------------|---------------|---------------|
| generous (N=1, 10y, no deflation) | 1 | 2520d | **0.69** | **0.93** |
| VIX-like (N=28, 5y windows) | 28 | 1260d | **1.91** | **2.40** |
| VIX-long (N=28, 10y windows) | 28 | 2520d | **1.36** | **1.66** |
| PEAD-like (N=10, ~1.2y OOS) | 10 | 300d | **>3.5** | **>3.5** |

## Power curves (overall detection rate)

### generous (N=1, 10y, no deflation)

| true Sharpe | power | DSR gate | bootstrap gate | sign gate |
|-------------|-------|----------|----------------|-----------|
| 0.25 | 0.03 | 0.04 | 0.04 | 0.70 |
| 0.50 | 0.24 | 0.27 | 0.27 | 0.95 |
| 0.75 | 0.58 | 0.63 | 0.60 | 1.00 |
| 1.00 | 0.88 | 0.91 | 0.88 | 1.00 |
| 1.25 | 0.96 | 0.97 | 0.96 | 1.00 |
| 1.50 | 1.00 | 1.00 | 1.00 | 1.00 |
| 1.75 | 1.00 | 1.00 | 1.00 | 1.00 |
| 2.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| 2.50 | 1.00 | 1.00 | 1.00 | 1.00 |
| 3.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| 3.50 | 1.00 | 1.00 | 1.00 | 1.00 |

### VIX-like (N=28, 5y windows)

| true Sharpe | power | DSR gate | bootstrap gate | sign gate |
|-------------|-------|----------|----------------|-----------|
| 0.25 | 0.00 | 0.00 | 0.02 | 0.59 |
| 0.50 | 0.00 | 0.00 | 0.09 | 0.81 |
| 0.75 | 0.00 | 0.00 | 0.29 | 0.95 |
| 1.00 | 0.02 | 0.02 | 0.59 | 0.99 |
| 1.25 | 0.04 | 0.04 | 0.81 | 1.00 |
| 1.50 | 0.19 | 0.19 | 0.87 | 1.00 |
| 1.75 | 0.36 | 0.36 | 0.93 | 1.00 |
| 2.00 | 0.57 | 0.57 | 0.98 | 1.00 |
| 2.50 | 0.85 | 0.85 | 1.00 | 1.00 |
| 3.00 | 0.95 | 0.95 | 1.00 | 1.00 |
| 3.50 | 0.99 | 0.99 | 1.00 | 1.00 |

### VIX-long (N=28, 10y windows)

| true Sharpe | power | DSR gate | bootstrap gate | sign gate |
|-------------|-------|----------|----------------|-----------|
| 0.25 | 0.00 | 0.00 | 0.04 | 0.70 |
| 0.50 | 0.00 | 0.00 | 0.27 | 0.95 |
| 0.75 | 0.01 | 0.01 | 0.60 | 1.00 |
| 1.00 | 0.10 | 0.10 | 0.88 | 1.00 |
| 1.25 | 0.35 | 0.35 | 0.96 | 1.00 |
| 1.50 | 0.68 | 0.68 | 1.00 | 1.00 |
| 1.75 | 0.86 | 0.86 | 1.00 | 1.00 |
| 2.00 | 0.98 | 0.98 | 1.00 | 1.00 |
| 2.50 | 1.00 | 1.00 | 1.00 | 1.00 |
| 3.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| 3.50 | 1.00 | 1.00 | 1.00 | 1.00 |

### PEAD-like (N=10, ~1.2y OOS)

| true Sharpe | power | DSR gate | bootstrap gate | sign gate |
|-------------|-------|----------|----------------|-----------|
| 0.25 | 0.00 | 0.00 | 0.02 | 0.42 |
| 0.50 | 0.00 | 0.00 | 0.02 | 0.53 |
| 0.75 | 0.00 | 0.00 | 0.11 | 0.74 |
| 1.00 | 0.00 | 0.00 | 0.14 | 0.80 |
| 1.25 | 0.00 | 0.00 | 0.24 | 0.87 |
| 1.50 | 0.01 | 0.01 | 0.37 | 0.92 |
| 1.75 | 0.05 | 0.05 | 0.52 | 0.93 |
| 2.00 | 0.06 | 0.06 | 0.57 | 0.97 |
| 2.50 | 0.16 | 0.16 | 0.74 | 1.00 |
| 3.00 | 0.27 | 0.27 | 0.81 | 1.00 |
| 3.50 | 0.43 | 0.43 | 0.90 | 1.00 |

## What the substrates actually produced (context)

| Substrate | observed OOS Sharpe |
|-----------|---------------------|
| VIX OOS (both windows) | -0.77 .. +0.55 |
| India OOS (all trials) | negative (-0.62 .. -4.94) |
| PEAD OOS point (short window) | +2.29 .. +2.87 (n_obs 80-127d) |
| crypto carry | IC~0.5, Sharpe failed DSR=0.624 |

## Reading this

- The **DSR gate is the binding constraint** — overall power tracks the
  DSR column almost exactly; sign agreement and the bootstrap CI clear
  far earlier.
- Compare each config's MDE@80% to the observed-Sharpe table. If the MDE
  sits far above what the substrates produced, the eight nulls are a
  **real** result, not a blunt instrument — the alpha that exists at
  retail grade is below the detection floor.
- If the MDE looks *implausibly* high (a real fund would trade a true
  Sharpe well below it with leverage + risk management), that is evidence
  the DSR>0.95-deflated-against-N hurdle is **stricter than economically
  necessary** — some closed substrates may have been correct-but-tradeable
  rejections. Either way the number, not intuition, now settles it.
