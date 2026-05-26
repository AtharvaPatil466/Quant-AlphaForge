# AlphaForge Microstructure Research Plan

---

## Framing the Pivot

Before the plan: one thing to internalize clearly. Everything that failed in Tier 1, Tier 2, and crypto carry failed because **signal content was real but costs destroyed it at the portfolio level**. Microstructure flips this relationship entirely. You are no longer trying to survive costs — you are trying to *earn* the spread. The cost model is no longer the enemy; it becomes part of the alpha mechanism itself.

This also means your statistical gauntlet changes completely. DSR deflation against a trial set, FF5+UMD residualization, monthly IC decay — none of these apply directly. The equivalent discipline exists, but it looks different. The plan below defines what that equivalent looks like.

---

## Phase 0 — Data Infrastructure

**Objective:** Have clean, validated, continuously accumulating L2 + trade tape data before a single line of signal code is written. Nothing in Phase 1 or beyond is unblocked until this is done.

**What you need:**

A persistent data collection process running 24/7 against Binance's public WebSocket feeds. Two streams simultaneously — the L2 order book delta stream and the aggregated trade tape stream. These are the two primitive data sources from which every microstructure signal is derived.

The L2 delta stream gives you incremental book updates at 100ms granularity. From these deltas you reconstruct a local order book mirror — a full representation of the top 20 bid and ask price levels at every point in time. This local book mirror is your primary data structure.

The trade tape gives you every aggressor-side fill: price, size, direction, and timestamp. This is the raw material for trade flow signals.

**What you store:**

Every 100ms snapshot of the reconstructed book — best bid, best ask, mid, spread, and the full top 20 levels on each side. Every trade event with its aggressor side flagged. Both streams timestamped to nanosecond precision from the exchange.

**Instrument selection:**

Start with one instrument only. BTC-USDT perpetual on Binance. Most liquid, cleanest data, lowest noise floor. Add instruments only after Phase 1 signal validation is complete on BTC.

**Validation before moving on:**

Before touching signal code, verify three things on your collected data. First, that your local book reconstruction matches Binance's periodic full snapshot (they publish these as a sanity check mechanism — your reconstructed book should match to the tick). Second, that your trade tape timestamps align correctly with your book snapshots — the temporal ordering must be exact. Third, that you have no gaps longer than one second in your data feed, and that gaps are logged explicitly so you can exclude them from research.

**Minimum accumulation before Phase 1:** 30 days. 90 days preferred. Start collecting immediately and let it run while you design the signal layer.

---

## Phase 1 — Signal Research

**Objective:** Identify whether any microstructure signal has genuine predictive power at any horizon on your collected data, before committing to a strategy design.

**The core research output of Phase 1 is a single chart:** IC versus holding horizon, for each signal, computed on your historical snapshots. This chart tells you whether you have anything worth building a strategy around, and at what timescale.

**Signal family 1 — Order Book Imbalance (OBI)**

The foundational microstructure signal. Computed as the ratio of bid-side depth to total depth at the top N price levels. Captures the directional pressure in the resting queue. When bids are heavy relative to asks, price tends to move up over the next few seconds — market orders hitting the ask deplete it faster than the bid.

You compute this at multiple depth levels independently: top 1 level, top 5 levels, top 10 levels, top 20 levels. These will have different IC profiles and different decay rates. The decay analysis tells you which depth is most informative and at what horizon.

**Signal family 2 — Microprice**

A weighted mid-price that accounts for queue imbalance. Instead of the simple arithmetic mid between best bid and best ask, the microprice weights the mid toward whichever side has less depth — because that side will deplete faster. It is a better predictor of the next transaction price than the raw mid.

This is your baseline price reference for all signal construction. Everything else is measured relative to microprice, not raw mid.

**Signal family 3 — Trade Flow Imbalance (TFI)**

The net signed volume of aggressor-side trades over a rolling window. Buys minus sells, in notional terms. This captures momentum in actual transactions rather than resting quotes, and tends to have predictive power at slightly longer horizons than OBI — minutes rather than seconds.

You compute this over multiple window lengths independently: 10 seconds, 30 seconds, 60 seconds, 5 minutes. Again, the decay analysis tells you which window is informative.

**Signal family 4 — Spread Dynamics**

The bid-ask spread itself is a signal. A widening spread indicates uncertainty or low liquidity — market makers are pulling back. A narrowing spread indicates confidence. Changes in spread predict short-term volatility and are useful as a filter on your other signals rather than a standalone predictor.

**The decay analysis — what you're actually measuring:**

For each signal, for each parameter configuration, you compute the Spearman rank correlation between the signal value at time T and the return from T to T+K, across all 100ms snapshots in your dataset. You do this for K equal to 1 second, 5 seconds, 30 seconds, 1 minute, 5 minutes, 15 minutes, 1 hour.

The resulting IC-versus-horizon curve tells you three things. First, whether the signal has any predictive power at all — IC consistently above 0.02 in absolute value is meaningful at this frequency. Second, at what horizon the predictive power peaks — this sets your target holding period. Third, how quickly the signal decays — a sharp decay means you need fast execution; a slow decay gives you more time.

**Pre-commitment equivalent of DSR:**

Before running the decay analysis, write down your pass criteria. A signal passes Phase 1 if it shows IC greater than 0.03 at its peak horizon, the IC is stable across at least two non-overlapping time windows in your dataset, and the sign is consistent — the signal points in the same direction in both halves of your data. This is your DSR equivalent. If nothing passes, Phase 2 does not begin. Same discipline as Tier 1 and Tier 2, different parameters.

---

## Phase 2 — Strategy Design

**Objective:** Take the signal or signals that passed Phase 1 and design a complete position management strategy around them. This is where you decide how to trade, not just what to predict.

**Position management logic:**

Unlike your factor strategies, you are not constructing a portfolio and rebalancing monthly. You are managing a single position in a single instrument that you enter and exit continuously throughout the trading day. The strategy has four decisions to make continuously: whether to enter, how large to be, when to exit, and whether to be passive (post a limit order) or aggressive (hit the market).

Each of these decisions is driven by your signal values and a set of pre-committed thresholds. The entry threshold, exit threshold, maximum inventory limit, and passive/aggressive decision rule are all defined before backtesting begins. You do not tune them after seeing the backtest results.

**Inventory risk — the new risk dimension:**

This is the concept that has no equivalent in your factor work. When you hold a position in a microstructure strategy, you are exposed to the risk that the price moves against you before you can exit. This is inventory risk, and it is separate from your signal being wrong. Even a correct signal can result in a loss if the price moves sharply before your fill.

Your strategy design must specify a maximum inventory limit — the largest position you will hold at any time — and a stop-loss rule that forces you out if the position moves against you beyond a defined threshold regardless of what the signal says. These are not optional; they are load-bearing risk controls in the same way your kill-switch is for the execution system.

**Passive versus aggressive execution:**

When your signal says to enter, you have two choices. You can post a limit order at the best bid or ask and wait to be filled — this earns the spread but risks not getting filled if price moves away. Or you can hit the market immediately — this guarantees a fill but pays the spread. Your signal strength and the current spread width should determine which you choose. A strong signal in a wide spread market favors aggression. A weak signal in a tight spread market favors passive posting.

This is a meaningful design decision because in microstructure, the difference between earning the spread and paying it is often the difference between a profitable and unprofitable strategy.

**Cost model — honest version for microstructure:**

Your Tier 1 and Tier 2 cost model was already an underestimate at 2bp half-spread versus the Corwin-Schultz 7-8bp reality. For microstructure you need to be even more precise. Your costs are: taker fee (Binance charges 4bp for market orders), maker rebate (Binance pays 2bp for limit orders that rest and fill), and slippage beyond the best level if your order size exceeds the top-of-book depth.

The cost model is not a post-hoc deduction here — it is wired into the strategy logic. Every entry decision must account for whether the expected alpha exceeds the cost of the trade. If your expected OBI signal has IC of 0.04 and you are paying 4bp in taker fees, the expected return per trade must exceed that threshold or you do not enter.

---

## Phase 3 — Backtest Engine Surgery

**Objective:** Adapt your existing event-driven engine to simulate microstructure strategies on historical L2 data with the same causality discipline as your equity backtester.

**What stays:**

The causality enforcement philosophy. Your BarHistory discipline — never look at data past the current as-of timestamp — translates directly. The new equivalent is a BookHistory structure that holds the reconstructed L2 book state at the current simulation timestamp and raises an error if queried past it. Same idea, nanosecond resolution instead of daily.

The per-fill accounting structure. Your existing fill event model with explicit commission and slippage per fill carries over.

The kill-switch and halt logic. Your existing execution system's risk controls are directly applicable.

**What changes:**

The fundamental simulation loop. Instead of iterating over daily bars and rebalancing a portfolio, you iterate over 100ms book snapshots and make continuous entry, exit, and sizing decisions. The loop is orders of magnitude tighter in time but the causality discipline is identical.

Fill simulation. In your equity backtest, a fill happens at the next bar's open. In microstructure simulation, you need to model fill probability explicitly. A passive limit order at the best bid is not guaranteed to fill — it fills only if price trades through that level, and only after all orders ahead of it in the queue are filled. A realistic fill model is one of the hardest parts of microstructure backtesting, and overestimating fill rates is one of the most common ways microstructure backtests look better than they are.

The honest approach: assume your passive orders fill only when price trades through your level, never at the best price unless you are at the front of the queue (which in a backtest you cannot verify). This understates your performance but understates it honestly.

**The key process disclosure you need to make up front:**

Your backtest cannot perfectly simulate queue position. This is a known limitation of all microstructure backtests that do not have access to the full order book with participant IDs. You will document this limitation explicitly, the same way you documented the cost model underestimate in Tier 2.

---

## Phase 4 — Statistical Validation

**Objective:** Apply the same rigorous statistical discipline as Tier 1 and Tier 2, adapted for the microstructure setting.

**The microstructure gauntlet — four gates, all must pass:**

Gate 1 — Adverse selection ratio. What percentage of your fills are immediately followed by price moving against you? If more than 50% of your fills are adversely selected, your signal is not good enough to overcome the information asymmetry. This is the microstructure equivalent of requiring positive IC.

Gate 2 — Realized spread capture. Are you consistently earning a positive realized spread — the difference between your entry price and the mid-price K seconds after your fill? This decomposes your P&L into the component you earned from liquidity provision versus the component you lost to adverse selection.

Gate 3 — Sharpe on out-of-sample data. Same concept as your equity gauntlet — evaluate on data the strategy never saw. Split your dataset: design on the first half, validate on the second. Require sign consistency and statistical significance on both halves.

Gate 4 — Cost sensitivity. Rerun the backtest with costs doubled. If the strategy does not survive doubled costs, it does not pass. This is the Tier 2 equivalent test — you are checking whether the alpha is robust to cost estimation error. Given that your Tier 1 cost model was 3-4x too optimistic, this gate is load-bearing.

**What replaces DSR deflation:**

The DSR framework deflates for multiple testing across a trial set. In microstructure you face the same problem — you will try multiple signal configurations and holding periods before finding one that works. Pre-commit your trial set before running any backtest. Every signal family, every parameter configuration, every holding period you test counts as a trial. Apply DSR deflation against that trial count before declaring a result.

---

## Phase 5 — Live Execution

**Objective:** Deploy the validated strategy into live paper trading on Binance testnet, then transition to live capital only after the paper trading period confirms the backtest is not an artifact.

**Infrastructure integration sequence:**

First, adapt your existing Binance WebSocket collector to feed your signal engine in real time rather than writing to Parquet. The signal engine computes OBI, microprice, and TFI on the live book and emits entry and exit signals.

Second, connect your signal engine to a Binance testnet order execution layer. This is where your matching engine's SBE codec and kill-switch logic integrate — you are now on the execution side of the problem, using your engine's infrastructure rather than its venue logic.

Third, run on testnet for a minimum of 60 days. Your existing paper trading discipline from the momentum and MARL accounts applies here. Do not touch the strategy during this period. Do not intervene. Measure adverse selection ratio, realized spread capture, and Sharpe on live fills versus backtest expectations.

**The go/no-go criteria for live capital:**

Live paper trading Sharpe must be within one standard error of the backtest Sharpe. Adverse selection ratio in live trading must be below 50%. Realized spread capture must be positive. If all three hold after 60 days, you have a deployable strategy. If any fail, you return to Phase 2 and redesign — you do not lower the bar.

---

## Honest Caveats Up Front

**Latency:** Your matching engine is L2 on the L-scale — outstanding for a software system, but your Python signal engine running over a standard WebSocket connection is L4 at best. You will not be competing with HFT firms on signal speed. This is fine for research and for strategies with holding periods of seconds to minutes, but you must be honest that any alpha with a decay shorter than one second is not exploitable at your execution latency.

**Queue position:** As noted in Phase 3, you cannot know your queue position in historical data. Your backtest fill model will overestimate your fill rate on passive orders. This is a known bias — document it, and adjust your live expectations accordingly.

**Wash trading on Binance:** Crypto microstructure data has more noise than equity microstructure data. Some of the volume in your trade tape is not genuine. This will make your signal noisier than academic papers on equity microstructure suggest. Your IC thresholds in Phase 1 account for this — but expect it.

**The honest question after Phase 1:** If your decay analysis shows no signal with IC above 0.03 at any horizon, the answer is not to lower the threshold. The answer is to consider whether a different strategy class — vol surface, term structure, or something else entirely — is more appropriate. The gauntlet is the gauntlet.

---

## Summary Timeline

Phase 0 takes as long as it takes to accumulate 30-90 days of clean data. Start immediately, run in the background, design Phase 1 while data accumulates.

Phase 1 is two to three weeks of research work once you have the data.

Phase 2 is one to two weeks of strategy design, contingent on Phase 1 passing.

Phase 3 is two to four weeks of engine surgery.

Phase 4 is one week of statistical validation.

Phase 5 is 60 days minimum of paper trading before any live capital decision.

Total realistic timeline to a live go/no-go decision: four to six months from today, with the data collection clock starting now.
