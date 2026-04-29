"""Adapter: drive `EventDrivenEngine` via the legacy `BacktestConfig` /
`BacktestResult` API.

This module exists so callers like `api/routes/backtest.py` can switch
their real-data backtest from `backtest.real_engine.run_real_backtest`
to the architecturally-correct event-driven engine without changing
their request/response schema.

Per ENGINE_CONSOLIDATION_DESIGN.md §4: this was the migration vehicle
that retired `real_engine.py` in Phase 2 session 4.

Numerical equivalence to `real_engine.run_real_backtest` is NOT a goal.
The legacy engine had documented bugs (same-bar fills, daily ±20%
clamp, per-rebalance flat tx-cost rather than per-fill cash cost) that
this engine deliberately does not reproduce. Result numbers will differ
— that is the whole point of the consolidation.
"""

from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from backtest import metrics as bm
from backtest.event_driven import (
    DataHandler,
    EngineConfig,
    EventDrivenEngine,
    ExecutionHandler,
    FlatSlippageModel,
    Portfolio,
    Strategy,
)
from backtest.event_driven.events import SignalEvent
from backtest.synthetic_demo import BacktestConfig, BacktestMetrics, BacktestResult
from data.real_dataset import load_real_history
from data.synthetic import PriceSeries
from factors.registry import load_factor


class _FactorScoreLongShort(Strategy):
    """Generic long-short strategy: compute a single-ticker factor score
    per ticker via `factor.compute_js`, then long top `long_pct` and
    short bottom `short_pct` of the cross-section, equal-weight within
    each leg.

    Replicates the legacy `_score_cross_section` semantics but operating
    against a `BarHistory` view (no look-ahead by construction). Lives
    inside the adapter because it has no use outside this migration —
    Phase 4 will use `PanelStrategy` driven by precomputed factor panels
    instead.
    """

    def __init__(
        self,
        factor_name: str,
        lookback_days: int,
        long_pct: float,
        short_pct: float,
        gross_leverage: float = 1.0,
        long_short: bool = True,
    ):
        if not (0.0 < long_pct <= 1.0):
            raise ValueError("long_pct must be in (0, 1]")
        if not (0.0 < short_pct <= 1.0):
            raise ValueError("short_pct must be in (0, 1]")
        self._factor_name = factor_name
        self._factor = load_factor(factor_name)
        self._lookback = lookback_days
        self._long_pct = long_pct
        self._short_pct = short_pct
        self._gross = gross_leverage
        self._long_short = long_short

    @property
    def id(self) -> str:
        return f"FactorScoreLongShort[{self._factor_name}]"

    def on_bar(self, history) -> List[SignalEvent]:
        scored: List[tuple[str, float]] = []
        for ticker in history.tickers():
            df = history.history(ticker)
            if len(df) < 2:
                continue
            prices = df["Close"].to_numpy(dtype=np.float64)
            volumes = df["Volume"].to_numpy(dtype=np.float64)
            # Compute returns from prices (matches what real_engine's
            # _score_cross_section did).
            returns = np.zeros_like(prices)
            returns[1:] = np.diff(prices) / np.maximum(prices[:-1], 1e-10)
            score = self._factor.compute_js(prices, volumes, returns, self._lookback)
            if np.isfinite(score):
                scored.append((ticker, float(score)))
        if not scored:
            return []

        scored.sort(key=lambda x: x[1], reverse=True)
        n = len(scored)
        n_long = max(1, int(round(n * self._long_pct)))
        n_short = max(1, int(round(n * self._short_pct))) if self._long_short else 0
        long_set = scored[:n_long]
        short_set = scored[-n_short:] if n_short else []
        # De-dupe ticker that appears in both legs on tiny universes.
        short_set = [(t, s) for (t, s) in short_set if t not in {x[0] for x in long_set}]

        long_w = (self._gross / 2.0) / max(1, len(long_set)) if long_set else 0.0
        short_w = (self._gross / 2.0) / max(1, len(short_set)) if short_set else 0.0

        signals: List[SignalEvent] = []
        held: set = set()
        for ticker, _ in long_set:
            signals.append(
                SignalEvent(
                    timestamp=history.as_of,
                    ticker=ticker,
                    target_weight=+long_w,
                    strategy_id=self.id,
                )
            )
            held.add(ticker)
        for ticker, _ in short_set:
            signals.append(
                SignalEvent(
                    timestamp=history.as_of,
                    ticker=ticker,
                    target_weight=-short_w,
                    strategy_id=self.id,
                )
            )
            held.add(ticker)
        # Flat-target every other ticker to close legacy positions.
        for ticker in history.tickers():
            if ticker not in held:
                signals.append(
                    SignalEvent(
                        timestamp=history.as_of,
                        ticker=ticker,
                        target_weight=0.0,
                        strategy_id=self.id,
                    )
                )
        return signals


def _equal_weight_benchmark_nav(
    history: Dict[str, pd.DataFrame],
    timestamps: pd.DatetimeIndex,
    initial: float = 100.0,
) -> List[float]:
    """Equal-weight long-only benchmark NAV path over `timestamps`.

    Computes the average of (close[t] / close[t_first] - 1) across all
    tickers, scaled by `initial`. Approximates the legacy real_engine's
    benchmark column (which averaged daily returns; we approximate with
    a buy-and-hold equal-weight basket which is closer to S&P 500 EW).
    """
    if not history or len(timestamps) == 0:
        return [initial]
    closes = pd.DataFrame(
        {tk: df["Close"] for tk, df in history.items()}
    ).reindex(timestamps).ffill()
    base = closes.iloc[0]
    rel = closes.divide(base.replace(0, np.nan), axis=1)
    bench = rel.mean(axis=1, skipna=True) * initial
    bench = bench.fillna(initial)
    return [float(x) for x in bench.tolist()]


def run_real_backtest_via_event_driven(
    config: BacktestConfig,
    *,
    end_date: date | str | None = None,
    market_dir: str | None = None,
) -> BacktestResult:
    """Real-data backtest via `EventDrivenEngine`, with a legacy-shaped
    `BacktestResult` return for API compatibility."""
    warmup_days = max(252, config.lookback)
    total_days = warmup_days + config.lookback + 5
    history = load_real_history(
        sector=config.sector,
        lookback=total_days,
        end_date=end_date,
        market_dir=market_dir,
        min_rows=warmup_days + 5,
        align="inner",
    )
    if not history:
        return BacktestResult(
            error="No validated real-market data available for the requested universe."
        )

    n_days = min(len(df) for df in history.values())
    if n_days <= warmup_days + 1:
        return BacktestResult(
            error="Not enough clean real-market history for the requested backtest window."
        )

    # Ensure each frame has the OHLCV schema the DataHandler requires.
    # The market loader produces all five columns; assert here for safety.
    required = {"Open", "High", "Low", "Close", "Volume"}
    for ticker, df in history.items():
        missing = required - set(df.columns)
        if missing:
            return BacktestResult(
                error=f"market data for {ticker} is missing columns {sorted(missing)}"
            )

    # Build the DataHandler.
    data_handler = DataHandler({tk: df.copy() for tk, df in history.items()})

    # Strategy: long-short by factor score, leg sizing per `position_size`.
    long_pct = max(0.01, min(1.0, config.position_size / 100.0))
    strategy = _FactorScoreLongShort(
        factor_name=config.factor_name,
        lookback_days=config.lookback,
        long_pct=long_pct,
        short_pct=long_pct,
        gross_leverage=1.0,
        long_short=config.long_short,
    )

    # Engine: rebalance every `holding_period` bars, warm up with the
    # legacy warmup window so the first decision has full lookback.
    # We run the engine at $1M initial cash (to clear the engine's
    # min_order_notional=100 floor on individual orders) and then
    # rescale the NAV path to the legacy base-100 display at the end.
    engine_initial_cash = 1_000_000.0
    output_initial_nav = 100.0
    eng_config = EngineConfig(
        rebalance_freq=max(1, config.holding_period),
        initial_cash=engine_initial_cash,
        warmup_bars=warmup_days,
    )
    portfolio = Portfolio(initial_cash=engine_initial_cash)
    # Use `tx_cost_bps` as commission; slippage stays at the engine
    # default of 5 bps. Total per-fill cost is therefore
    # commission + slippage on each round-trip.
    exec_handler = ExecutionHandler(
        FlatSlippageModel(slippage_bps=5.0, commission_bps=float(config.tx_cost_bps))
    )
    engine = EventDrivenEngine(
        data_handler=data_handler,
        strategy=strategy,
        execution_handler=exec_handler,
        portfolio=portfolio,
        config=eng_config,
    )
    run = engine.run()

    # Convert NAV history to legacy-shaped lists.
    if not portfolio.nav_history:
        return BacktestResult(
            error="EventDrivenEngine produced no NAV marks (engine never marked)."
        )
    nav_marks = portfolio.nav_history
    timestamps = pd.DatetimeIndex([m.timestamp for m in nav_marks])

    raw_nav = np.asarray([float(m.nav) for m in nav_marks], dtype=np.float64)
    if raw_nav.size < 2 or not np.all(np.isfinite(raw_nav)) or np.any(raw_nav <= 0):
        return BacktestResult(error="Real-data simulation produced invalid NAV values.")
    # Rescale to base-100 for the legacy BacktestResult contract.
    scale = output_initial_nav / raw_nav[0]
    nav_arr = raw_nav * scale
    nav: List[float] = nav_arr.tolist()

    # Daily returns (length = len(nav) - 1, matches legacy)
    daily_returns = (np.diff(nav_arr) / nav_arr[:-1]).tolist()

    # Benchmark = equal-weight long-only over the same timestamps.
    benchmark_nav = _equal_weight_benchmark_nav(history, timestamps, initial=output_initial_nav)

    # Drawdowns
    peak = np.maximum.accumulate(nav_arr)
    dd = (peak - nav_arr) / np.maximum(peak, 1e-10)
    drawdowns = dd[1:].tolist()  # match legacy length (one less than nav)
    max_dd = float(dd.max()) if dd.size else 0.0
    max_dd_day = int(dd.argmax()) if dd.size else 0

    # Metrics
    total_return = float(nav_arr[-1] / nav_arr[0] - 1.0)
    bench_arr = np.asarray(benchmark_nav, dtype=np.float64)
    bench_return = float(bench_arr[-1] / bench_arr[0] - 1.0) if bench_arr.size else 0.0
    avg_r = float(np.mean(daily_returns)) if daily_returns else 0.0
    std_r = float(np.std(daily_returns, ddof=0)) if daily_returns else 0.0
    sharpe = (avg_r / std_r * (252 ** 0.5)) if std_r > 1e-8 else 0.0
    ann_vol = std_r * (252 ** 0.5) if std_r > 1e-8 else 0.0
    wins = int(np.sum(np.asarray(daily_returns) > 0)) if daily_returns else 0
    win_rate = (wins / len(daily_returns)) if daily_returns else 0.0

    metrics = BacktestMetrics(
        sharpe=sharpe,
        total_return=total_return,
        bench_return=bench_return,
        max_dd=max_dd,
        max_dd_day=max_dd_day,
        win_rate=win_rate,
        ann_vol=ann_vol,
        calmar=(total_return / max_dd) if max_dd > 0 else 0.0,
        sortino=bm.sortino_ratio(daily_returns) if daily_returns else 0.0,
        ann_return=bm.annualized_return(nav),
    )
    return BacktestResult(
        nav=nav,
        benchmark_nav=benchmark_nav,
        drawdowns=drawdowns,
        monthly_returns=bm.monthly_returns(nav),
        daily_returns=daily_returns,
        metrics=metrics,
    )
