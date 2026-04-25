"""Baseline strategy evaluation for walk-forward validation."""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Mapping, Sequence

import numpy as np

from env.state_builder import rolling_signal_score


MetricDict = Dict[str, float]
Dataset = Mapping[str, Any]
PathDict = Dict[str, Any]


def safe_div(a: float, b: float, fallback: float = 0.0) -> float:
    """Finite-safe division helper."""
    if abs(b) < 1e-12 or not np.isfinite(b):
        return fallback
    out = a / b
    return float(out) if np.isfinite(out) else fallback


def compute_performance_metrics(
    daily_returns: Sequence[float],
    nav_history: Sequence[float],
    turnover: Sequence[float],
) -> MetricDict:
    """Compute a compact set of portfolio metrics from a daily path."""
    rets = np.asarray(daily_returns, dtype=np.float64)
    nav = np.asarray(nav_history, dtype=np.float64)
    turns = np.asarray(turnover, dtype=np.float64)

    if len(rets) == 0 or len(nav) < 2:
        return {
            "annual_return": 0.0,
            "total_return": 0.0,
            "sharpe": 0.0,
            "max_drawdown": 0.0,
            "avg_turnover": 0.0,
            "hit_rate": 0.0,
            "n_days": float(len(rets)),
            "daily_returns": [],
            "nav_series": [],
        }

    mean_ret = float(np.mean(rets))
    std_ret = float(np.std(rets, ddof=1)) if len(rets) > 1 else 0.0
    sharpe = safe_div(mean_ret, std_ret, 0.0) * math.sqrt(252) if std_ret > 1e-12 else 0.0

    total_return = safe_div(nav[-1] - nav[0], nav[0], 0.0)
    annual_return = (nav[-1] / nav[0]) ** (252.0 / max(len(rets), 1)) - 1.0 if nav[0] > 0 and nav[-1] > 0 else total_return
    peak = np.maximum.accumulate(nav)
    drawdowns = (peak - nav) / np.maximum(peak, 1e-10)

    return {
        "annual_return": float(annual_return),
        "total_return": float(total_return),
        "sharpe": float(sharpe),
        "max_drawdown": float(np.max(drawdowns)) if len(drawdowns) else 0.0,
        "avg_turnover": float(np.mean(turns)) if len(turns) else 0.0,
        "hit_rate": float(np.mean(rets > 0)),
        "n_days": float(len(rets)),
        # Daily series persisted so downstream code (bootstrap CIs, DSR, plots)
        # can work without re-running the environment. Aggregation across
        # windows concatenates these lists; see aggregate_metric_dicts below.
        "daily_returns": [float(x) for x in rets.tolist()],
        "nav_series": [float(x) for x in nav.tolist()],
    }


def aggregate_metric_dicts(metrics: Iterable[MetricDict]) -> MetricDict:
    """Average scalar metrics across windows; concatenate list-valued series.

    Scalar keys (sharpe, max_drawdown, ...) are averaged across windows.
    List keys (daily_returns, nav_series) are concatenated so a downstream
    consumer sees one combined path across all windows for bootstrap CIs.
    """
    metrics = list(metrics)
    if not metrics:
        return {}

    keys = sorted({key for item in metrics for key in item})
    aggregated: MetricDict = {}
    for key in keys:
        raw_values = [item[key] for item in metrics if key in item]
        if not raw_values:
            aggregated[key] = 0.0
            continue
        if any(isinstance(v, list) for v in raw_values):
            combined: List[float] = []
            for v in raw_values:
                if isinstance(v, list):
                    combined.extend(v)
            aggregated[key] = combined
        else:
            aggregated[key] = float(np.mean([float(v) for v in raw_values]))
    return aggregated


def _valid_tickers(dataset: Dataset) -> List[str]:
    tickers: List[str] = []
    for ticker, series in dataset.items():
        if hasattr(series, "prices") and hasattr(series, "returns") and len(series.prices) >= 2:
            tickers.append(ticker)
    return tickers


def _turnover(old_weights: Mapping[str, float], new_weights: Mapping[str, float]) -> float:
    tickers = set(old_weights) | set(new_weights)
    return float(sum(abs(new_weights.get(t, 0.0) - old_weights.get(t, 0.0)) for t in tickers))


def _rank_by_lookback(
    dataset: Dataset,
    tickers: Sequence[str],
    signal_day: int,
    lookback: int,
    reverse: bool = True,
) -> List[str]:
    scored = []
    for ticker in tickers:
        prices = np.asarray(dataset[ticker].prices, dtype=np.float64)
        if signal_day < lookback or signal_day >= len(prices):
            continue
        start_idx = signal_day - lookback
        score = safe_div(prices[signal_day] - prices[start_idx], prices[start_idx], 0.0)
        scored.append((ticker, score))
    scored.sort(key=lambda item: item[1], reverse=reverse)
    return [ticker for ticker, _ in scored]


def _select_weights(
    dataset: Dataset,
    strategy: str,
    signal_day: int,
    top_n: int,
    rng: np.random.Generator,
) -> Dict[str, float]:
    tickers = _valid_tickers(dataset)
    if not tickers:
        return {}

    if strategy == "equal_weight":
        weight = 1.0 / len(tickers)
        return {ticker: weight for ticker in tickers}

    if strategy == "random_top5":
        n_pick = min(top_n, len(tickers))
        picks = rng.choice(tickers, size=n_pick, replace=False).tolist()
        weight = 1.0 / max(len(picks), 1)
        return {ticker: weight for ticker in picks}

    if strategy == "momentum_top5":
        ranked = _rank_by_lookback(dataset, tickers, signal_day, lookback=21, reverse=True)
    elif strategy == "mean_reversion_top5":
        ranked = _rank_by_lookback(dataset, tickers, signal_day, lookback=5, reverse=False)
    else:
        raise ValueError(f"Unknown baseline strategy '{strategy}'")

    picks = ranked[: min(top_n, len(ranked))]
    if not picks:
        return {}
    weight = 1.0 / len(picks)
    return {ticker: weight for ticker in picks}


def _feature_value(series: Any, day: int, lookback: int) -> float:
    prices = np.asarray(series.prices, dtype=np.float64)
    if len(prices) == 0:
        return 0.0
    d = min(day, len(prices) - 1)
    start = max(0, d - lookback)
    base = float(prices[start])
    if abs(base) < 1e-12:
        return 0.0
    return safe_div(float(prices[d]) - base, base, 0.0)


def _volatility_feature(series: Any, day: int, lookback: int) -> float:
    rets = np.asarray(getattr(series, "returns", np.zeros(0)), dtype=np.float64)
    if len(rets) < 2:
        return 0.0
    d = min(day, len(rets) - 1)
    start = max(1, d - lookback + 1)
    chunk = rets[start:d + 1]
    if len(chunk) < 2:
        return 0.0
    return float(np.std(chunk, ddof=1)) * math.sqrt(252.0)


def _ma_gap_feature(series: Any, day: int, lookback: int) -> float:
    prices = np.asarray(series.prices, dtype=np.float64)
    if len(prices) == 0:
        return 0.0
    d = min(day, len(prices) - 1)
    start = max(0, d - lookback + 1)
    ma = float(np.mean(prices[start:d + 1]))
    if abs(ma) < 1e-12:
        return 0.0
    return safe_div(float(prices[d]), ma, 0.0) - 1.0


def _volume_ratio_feature(series: Any, day: int, lookback: int) -> float:
    vols = np.asarray(getattr(series, "volumes", np.ones(0)), dtype=np.float64)
    if len(vols) == 0:
        return 0.0
    d = min(day, len(vols) - 1)
    start = max(0, d - lookback + 1)
    avg = float(np.mean(vols[start:d + 1]))
    if abs(avg) < 1e-12:
        return 0.0
    return safe_div(float(vols[d]), avg, 0.0) - 1.0


def _ticker_feature_vector(series: Any, day: int) -> np.ndarray:
    """Compact price/volume feature vector using only information up to ``day``."""
    return np.asarray(
        [
            _feature_value(series, day, 5),
            _feature_value(series, day, 21),
            _feature_value(series, day, 63),
            _volatility_feature(series, day, 5),
            _volatility_feature(series, day, 21),
            _ma_gap_feature(series, day, 21),
            _ma_gap_feature(series, day, 63),
            _volume_ratio_feature(series, day, 21),
            rolling_signal_score(series, day),
        ],
        dtype=np.float64,
    )


def _fit_ridge_excess_model_from_matrix(
    x: Sequence[np.ndarray],
    y: Sequence[float],
    alpha: float = 1.0,
) -> Dict[str, np.ndarray] | None:
    """Fit a tiny ridge model to predict next-day excess returns."""
    if len(x) < 20 or len(y) < 20:
        return None

    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    x_mean = np.mean(x, axis=0)
    x_std = np.std(x, axis=0)
    x_std = np.where(x_std < 1e-8, 1.0, x_std)
    x_scaled = (x - x_mean) / x_std
    y_mean = float(np.mean(y))
    y_centered = y - y_mean

    reg = alpha * np.eye(x_scaled.shape[1], dtype=np.float64)
    lhs = x_scaled.T @ x_scaled + reg
    rhs = x_scaled.T @ y_centered
    coef = np.linalg.pinv(lhs) @ rhs
    return {
        "x_mean": x_mean,
        "x_std": x_std,
        "coef": coef,
        "intercept": np.asarray([y_mean], dtype=np.float64),
    }


def _predict_ridge_excess(model: Mapping[str, np.ndarray], series: Any, day: int) -> float:
    x = _ticker_feature_vector(series, day)
    x_scaled = (x - model["x_mean"]) / model["x_std"]
    pred = float(model["intercept"][0] + np.dot(x_scaled, model["coef"]))
    return pred if np.isfinite(pred) else 0.0


def simulate_supervised_baseline_path(
    dataset: Dataset,
    top_n: int = 5,
    tx_cost_bps: int = 5,
    min_history: int = 21,
    retrain_interval: int = 5,
    ridge_alpha: float = 1.0,
) -> PathDict:
    """Run a simple expanding-window ridge model on next-day excess returns."""
    tickers = _valid_tickers(dataset)
    if not tickers:
        return {
            "daily_returns": [],
            "nav_history": [100.0],
            "turnover": [],
            "activity_ratio": 0.0,
        }

    min_len = min(
        min(len(np.asarray(dataset[ticker].prices)), len(np.asarray(dataset[ticker].returns)))
        for ticker in tickers
    )
    if min_len < min_history + 2:
        return {
            "daily_returns": [],
            "nav_history": [100.0],
            "turnover": [],
            "activity_ratio": 0.0,
        }

    nav = [100.0]
    daily_returns: List[float] = []
    turnover: List[float] = []
    prev_weights: Dict[str, float] = {}
    tx_cost = tx_cost_bps / 10000.0
    model: Dict[str, np.ndarray] | None = None
    last_fit_signal_day = -1
    x_rows: List[np.ndarray] = []
    y_rows: List[float] = []

    for day in range(1, min_len):
        signal_day = day - 1
        weights: Dict[str, float] = {}

        new_train_day = signal_day - 1
        if new_train_day >= min_history:
            next_day_returns: Dict[str, float] = {}
            per_ticker_features: Dict[str, np.ndarray] = {}
            for ticker in tickers:
                rets = np.asarray(dataset[ticker].returns, dtype=np.float64)
                if new_train_day + 1 >= len(rets):
                    continue
                per_ticker_features[ticker] = _ticker_feature_vector(dataset[ticker], new_train_day)
                next_day_returns[ticker] = float(rets[new_train_day + 1])

            if len(next_day_returns) >= 3:
                cross_mean = float(np.mean(list(next_day_returns.values())))
                for ticker, next_ret in next_day_returns.items():
                    x_rows.append(per_ticker_features[ticker])
                    y_rows.append(next_ret - cross_mean)

        if signal_day >= min_history:
            if model is None or (signal_day - last_fit_signal_day) >= retrain_interval:
                model = _fit_ridge_excess_model_from_matrix(
                    x_rows,
                    y_rows,
                    alpha=ridge_alpha,
                )
                if model is not None:
                    last_fit_signal_day = signal_day

            if model is not None:
                ranked = sorted(
                    (
                        (ticker, _predict_ridge_excess(model, dataset[ticker], signal_day))
                        for ticker in tickers
                    ),
                    key=lambda item: item[1],
                    reverse=True,
                )
                picks = [ticker for ticker, _score in ranked[: min(top_n, len(ranked))]]
                if picks:
                    weight = 1.0 / len(picks)
                    weights = {ticker: weight for ticker in picks}

        daily_turnover = _turnover(prev_weights, weights)
        gross_return = 0.0
        for ticker, weight in weights.items():
            rets = np.asarray(dataset[ticker].returns, dtype=np.float64)
            if day < len(rets):
                gross_return += weight * float(rets[day])

        net_return = gross_return - daily_turnover * tx_cost
        if not np.isfinite(net_return):
            net_return = 0.0

        nav.append(nav[-1] * (1.0 + net_return))
        daily_returns.append(net_return)
        turnover.append(daily_turnover)
        prev_weights = weights

    active_days = sum(1 for item in turnover if item > 1e-12)
    return {
        "daily_returns": daily_returns,
        "nav_history": nav,
        "turnover": turnover,
        "activity_ratio": active_days / max(len(turnover), 1),
    }


def simulate_supervised_baseline(
    dataset: Dataset,
    top_n: int = 5,
    tx_cost_bps: int = 5,
    min_history: int = 21,
    retrain_interval: int = 5,
    ridge_alpha: float = 1.0,
) -> MetricDict:
    path = simulate_supervised_baseline_path(
        dataset,
        top_n=top_n,
        tx_cost_bps=tx_cost_bps,
        min_history=min_history,
        retrain_interval=retrain_interval,
        ridge_alpha=ridge_alpha,
    )
    metrics = compute_performance_metrics(
        path["daily_returns"],
        path["nav_history"],
        path["turnover"],
    )
    metrics["activity_ratio"] = float(path.get("activity_ratio", 0.0))
    return metrics


def simulate_baseline_path(
    dataset: Dataset,
    strategy: str,
    top_n: int = 5,
    tx_cost_bps: int = 5,
    seed: int = 0,
) -> PathDict:
    """Run a simple baseline strategy over one dataset window and return its path."""
    if strategy == "ridge_excess_top5":
        return simulate_supervised_baseline_path(
            dataset,
            top_n=top_n,
            tx_cost_bps=tx_cost_bps,
        )

    tickers = _valid_tickers(dataset)
    if not tickers:
        return {
            "daily_returns": [],
            "nav_history": [100.0],
            "turnover": [],
        }

    min_len = min(
        min(len(np.asarray(dataset[ticker].prices)), len(np.asarray(dataset[ticker].returns)))
        for ticker in tickers
    )
    if min_len < 2:
        return {
            "daily_returns": [],
            "nav_history": [100.0],
            "turnover": [],
        }

    nav = [100.0]
    daily_returns: List[float] = []
    turnover: List[float] = []
    prev_weights: Dict[str, float] = {}
    rng = np.random.default_rng(seed)
    tx_cost = tx_cost_bps / 10000.0

    for day in range(1, min_len):
        signal_day = day - 1
        weights = _select_weights(dataset, strategy, signal_day, top_n, rng)
        daily_turnover = _turnover(prev_weights, weights)
        gross_return = 0.0
        for ticker, weight in weights.items():
            rets = np.asarray(dataset[ticker].returns, dtype=np.float64)
            gross_return += weight * float(rets[day])

        net_return = gross_return - daily_turnover * tx_cost
        if not np.isfinite(net_return):
            net_return = 0.0

        nav.append(nav[-1] * (1.0 + net_return))
        daily_returns.append(net_return)
        turnover.append(daily_turnover)
        prev_weights = weights

    return {
        "daily_returns": daily_returns,
        "nav_history": nav,
        "turnover": turnover,
    }


def simulate_baseline(
    dataset: Dataset,
    strategy: str,
    top_n: int = 5,
    tx_cost_bps: int = 5,
    seed: int = 0,
) -> MetricDict:
    """Run a simple baseline strategy over one dataset window."""
    path = simulate_baseline_path(
        dataset,
        strategy=strategy,
        top_n=top_n,
        tx_cost_bps=tx_cost_bps,
        seed=seed,
    )
    metrics = compute_performance_metrics(
        path["daily_returns"],
        path["nav_history"],
        path["turnover"],
    )
    if "activity_ratio" in path:
        metrics["activity_ratio"] = float(path["activity_ratio"])
    return metrics


def evaluate_baselines(
    windows: Sequence[Dataset],
    tx_cost_bps: int = 5,
) -> Dict[str, MetricDict]:
    """Evaluate all default baselines across a sequence of windows."""
    strategies = [
        "equal_weight",
        "momentum_top5",
        "mean_reversion_top5",
        "ridge_excess_top5",
        "random_top5",
    ]
    results: Dict[str, MetricDict] = {}
    for strategy in strategies:
        per_window = [
            simulate_baseline(window, strategy=strategy, tx_cost_bps=tx_cost_bps, seed=idx)
            for idx, window in enumerate(windows)
        ]
        results[strategy] = aggregate_metric_dicts(per_window)
    return results
