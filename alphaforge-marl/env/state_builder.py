"""Builds the 57-dimensional state vector for the MARL trading environment."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

import numpy as np


def build_state(
    *,
    day: int,
    episode_length: int,
    nav_history: List[float],
    positions: Dict[str, float],
    cash_ratio: float,
    index_returns: np.ndarray,
    index_volumes: np.ndarray,
    index_prices: np.ndarray,
    factor_scores: Dict[str, Dict[str, float]],
    tickers: List[str],
    days_since_rebalance: int,
    dataset: Optional[Dict[str, Any]] = None,
) -> np.ndarray:
    """Build 57-dim observation vector.

    Layout:
      [0:7]   Portfolio state
      [7:15]  Market regime features
      [15:35] Top 5 long candidates: rolling price features (5 x 4)
      [35:55] Top 5 short candidates: rolling price features (5 x 4)
      [55:57] Time features

    When ``dataset`` is provided, dims 15-54 use time-varying per-ticker
    features (5d return, 21d return, 5d vol, price vs 21d MA) instead of
    static factor scores.
    """
    obs = np.zeros(57, dtype=np.float32)

    # ── Portfolio state (7 dims) ─────────────────────────────────
    nav = nav_history[-1] if nav_history else 100.0
    initial_nav = nav_history[0] if nav_history else 100.0
    peak_nav = max(nav_history) if nav_history else 100.0

    obs[0] = _safe((nav - initial_nav) / initial_nav)  # current return
    obs[1] = _safe((peak_nav - nav) / peak_nav) if peak_nav > 0 else 0.0  # drawdown
    obs[2] = _rolling_sharpe(nav_history, 21)  # rolling 21d Sharpe

    n_pos = len(positions)
    max_pos = max(10, len(tickers))
    obs[3] = min(1.0, n_pos / max_pos)  # position count normalized

    long_exp = sum(v for v in positions.values() if v > 0)
    short_exp = sum(abs(v) for v in positions.values() if v < 0)
    obs[4] = min(2.0, long_exp)   # long exposure
    obs[5] = min(2.0, short_exp)  # short exposure
    obs[6] = max(0.0, min(1.0, cash_ratio))

    # ── Market regime features (8 dims) ──────────────────────────
    d = min(day, len(index_returns) - 1)
    rets = index_returns[:d + 1] if d >= 0 else np.zeros(1)

    obs[7] = _autocorrelation(rets, 5)    # autocorr 5d
    obs[8] = _autocorrelation(rets, 21)   # autocorr 21d
    obs[9] = _realized_vol(rets, 21)      # vol 21d
    obs[10] = _realized_vol(rets, 63)     # vol 63d
    obs[11] = _hurst(index_prices[:d + 1] if d >= 0 else np.ones(1), 100)
    obs[12] = _volume_ratio(index_volumes, d, 21)
    obs[13] = _skewness(rets, 21)
    obs[14] = _kurtosis(rets, 21)

    if dataset is not None:
        # Rank candidates using only information available up to `day`.
        ranked = _rank_by_dataset_day(dataset, tickers, day)
        top5 = ranked[:5]
        bot5 = ranked[-5:] if len(ranked) >= 5 else ranked[:5]

        # Time-varying features: 5d ret, 21d ret, 5d vol, price vs 21d MA
        for i, t in enumerate(top5):
            if i >= 5:
                break
            base = 15 + i * 4
            _fill_ticker_features(obs, base, dataset.get(t), day)

        for i, t in enumerate(bot5):
            if i >= 5:
                break
            base = 35 + i * 4
            _fill_ticker_features(obs, base, dataset.get(t), day)
    else:
        # ── Per-ticker rolling features for top/bottom candidates (40 dims) ──
        ranked = _rank_by_composite(factor_scores, tickers)
        top5 = ranked[:5]
        bot5 = ranked[-5:] if len(ranked) >= 5 else ranked[:5]

        # Fallback: static factor scores (backward compat for tests)
        for i, t in enumerate(top5):
            if i >= 5:
                break
            base = 15 + i * 4
            s = factor_scores.get(t, {})
            obs[base + 0] = _safe(s.get("_composite", 0.0) / 100.0)
            obs[base + 1] = _safe(s.get("Momentum (12-1)", 0.0))
            obs[base + 2] = _safe(s.get("Mean Reversion (5d)", 0.0))
            obs[base + 3] = _safe(s.get("Volume Surge", 0.0))

        for i, t in enumerate(bot5):
            if i >= 5:
                break
            base = 35 + i * 4
            s = factor_scores.get(t, {})
            obs[base + 0] = _safe(s.get("_composite", 0.0) / 100.0)
            obs[base + 1] = _safe(s.get("Momentum (12-1)", 0.0))
            obs[base + 2] = _safe(s.get("Mean Reversion (5d)", 0.0))
            obs[base + 3] = _safe(s.get("Volume Surge", 0.0))

    # ── Time features (2 dims) ───────────────────────────────────
    obs[55] = day / max(1, episode_length)  # day of episode normalized
    obs[56] = min(1.0, days_since_rebalance / 21.0)

    # Sanitize
    obs = np.nan_to_num(obs, nan=0.0, posinf=0.0, neginf=0.0)
    return obs


def _fill_ticker_features(
    obs: np.ndarray, base: int, series: Any, day: int
) -> None:
    """Fill 4 time-varying features for one ticker at obs[base:base+4].

    Features:
      [0] 5-day return (short-term momentum)
      [1] 21-day return (medium-term momentum)
      [2] 5-day realized vol (recent turbulence)
      [3] price vs 21-day MA ratio - 1 (mean reversion signal)
    """
    if series is None:
        return
    prices = series.prices
    n = len(prices)
    d = min(day, n - 1)
    if d < 1:
        return

    # 5-day return
    if d >= 5:
        obs[base + 0] = _safe((prices[d] - prices[d - 5]) / max(prices[d - 5], 1e-10))
    else:
        obs[base + 0] = _safe((prices[d] - prices[0]) / max(prices[0], 1e-10))

    # 21-day return
    if d >= 21:
        obs[base + 1] = _safe((prices[d] - prices[d - 21]) / max(prices[d - 21], 1e-10))
    else:
        obs[base + 1] = _safe((prices[d] - prices[0]) / max(prices[0], 1e-10))

    # 5-day realized vol
    rets = series.returns
    if d >= 5:
        chunk = rets[max(1, d - 4):d + 1]
        if len(chunk) >= 2:
            obs[base + 2] = _safe(float(np.std(chunk, ddof=1)) * math.sqrt(252))

    # Price vs 21-day MA ratio
    if d >= 21:
        ma21 = float(np.mean(prices[d - 20:d + 1]))
        if ma21 > 1e-10:
            obs[base + 3] = _safe(prices[d] / ma21 - 1.0)


def rolling_signal_score(series: Any, day: int) -> float:
    """Risk-adjusted trend score using only data available up to ``day``.

    The goal is to prefer smoother, better-confirmed trends over noisy spikes.
    """
    if series is None or not hasattr(series, "prices"):
        return 0.0

    prices = np.asarray(series.prices, dtype=np.float64)
    if len(prices) == 0:
        return 0.0

    d = min(day, len(prices) - 1)
    if d < 1:
        return 0.0

    rets = np.asarray(getattr(series, "returns", np.zeros(len(prices))), dtype=np.float64)
    vols = np.asarray(getattr(series, "volumes", np.ones(len(prices))), dtype=np.float64)

    d5 = max(0, d - 5)
    d21 = max(0, d - 21)
    d63 = max(0, d - 63)

    mom21 = _safe((prices[d] - prices[d21]) / max(prices[d21], 1e-10))
    mom63 = _safe((prices[d] - prices[d63]) / max(prices[d63], 1e-10))

    vol_window = rets[max(1, d - 20):d + 1]
    vol21 = float(np.std(vol_window, ddof=1)) * math.sqrt(252) if len(vol_window) >= 2 else 0.0
    risk_adj_mom = mom21 / max(vol21, 1e-4)

    high63 = float(np.max(prices[d63:d + 1])) if d >= 1 else float(prices[d])
    breakout = _safe(prices[d] / max(high63, 1e-10) - 1.0)

    ma21 = float(np.mean(prices[max(0, d - 20):d + 1]))
    pullback = _safe(-(prices[d] / max(ma21, 1e-10) - 1.0))

    vol_avg = float(np.mean(vols[max(0, d - 20):d + 1]))
    vol_confirm = _safe(vols[d] / max(vol_avg, 1e-10) - 1.0)

    return float(
        0.35 * risk_adj_mom
        + 0.25 * mom63
        + 0.20 * breakout
        + 0.10 * pullback
        + 0.10 * vol_confirm
    )


# ── Helpers ──────────────────────────────────────────────────────

def _safe(v: float) -> float:
    return v if math.isfinite(v) else 0.0


def _rolling_sharpe(nav_history: List[float], window: int) -> float:
    if len(nav_history) < window + 1:
        return 0.0
    nav = np.array(nav_history[-window - 1:])
    rets = np.diff(nav) / nav[:-1]
    mu = float(np.mean(rets))
    sigma = float(np.std(rets, ddof=1))
    if sigma < 1e-12:
        return 0.0
    return _safe((mu / sigma) * math.sqrt(252))


def _autocorrelation(rets: np.ndarray, lag: int) -> float:
    if len(rets) < lag + 10:
        return 0.0
    x = rets[:-lag]
    y = rets[lag:]
    n = min(len(x), len(y))
    if n < 5:
        return 0.0
    x, y = x[-n:], y[-n:]
    mx, my = np.mean(x), np.mean(y)
    num = float(np.sum((x - mx) * (y - my)))
    dx = float(np.sum((x - mx) ** 2))
    dy = float(np.sum((y - my) ** 2))
    denom = math.sqrt(dx * dy)
    return _safe(num / denom) if denom > 1e-12 else 0.0


def _realized_vol(rets: np.ndarray, window: int) -> float:
    if len(rets) < window:
        return 0.0
    chunk = rets[-window:]
    return _safe(float(np.std(chunk, ddof=1)) * math.sqrt(252))


def _hurst(prices: np.ndarray, window: int) -> float:
    if len(prices) < window:
        return 0.5
    p = prices[-window:]
    log_rets = np.diff(np.log(np.maximum(p, 1e-10)))
    n = len(log_rets)
    if n < 20:
        return 0.5
    max_k = n // 2
    if max_k < 4:
        return 0.5
    rs_list, ns_list = [], []
    for k in [max_k // 4, max_k // 2, max_k]:
        if k < 4:
            continue
        num_seg = n // k
        rs_vals = []
        for seg in range(num_seg):
            sub = log_rets[seg * k:(seg + 1) * k]
            m = np.mean(sub)
            s = np.std(sub, ddof=1)
            if s < 1e-12:
                continue
            cumdev = np.cumsum(sub - m)
            r = np.max(cumdev) - np.min(cumdev)
            rs_vals.append(r / s)
        if rs_vals:
            rs_list.append(math.log(np.mean(rs_vals)))
            ns_list.append(math.log(k))
    if len(rs_list) < 2:
        return 0.5
    x, y = np.array(ns_list), np.array(rs_list)
    mx, my = np.mean(x), np.mean(y)
    num = float(np.sum((x - mx) * (y - my)))
    denom = float(np.sum((x - mx) ** 2))
    h = num / denom if denom > 1e-12 else 0.5
    return float(np.clip(h, 0.0, 1.0))


def _volume_ratio(volumes: np.ndarray, day: int, window: int) -> float:
    if day < window or len(volumes) <= day:
        return 1.0
    avg = float(np.mean(volumes[max(0, day - window):day]))
    if avg < 1e-8:
        return 1.0
    return _safe(float(volumes[day]) / avg)


def _skewness(rets: np.ndarray, window: int) -> float:
    if len(rets) < window:
        return 0.0
    chunk = rets[-window:]
    m = np.mean(chunk)
    s = np.std(chunk, ddof=1)
    if s < 1e-12:
        return 0.0
    return _safe(float(np.mean(((chunk - m) / s) ** 3)))


def _kurtosis(rets: np.ndarray, window: int) -> float:
    if len(rets) < window:
        return 0.0
    chunk = rets[-window:]
    m = np.mean(chunk)
    s = np.std(chunk, ddof=1)
    if s < 1e-12:
        return 0.0
    return _safe(float(np.mean(((chunk - m) / s) ** 4)) - 3.0)


def _rank_by_composite(
    factor_scores: Dict[str, Dict[str, float]], tickers: List[str]
) -> List[str]:
    scored = [(t, factor_scores.get(t, {}).get("_composite", 0.0)) for t in tickers]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [t for t, _ in scored]


def _rank_by_dataset_day(
    dataset: Dict[str, Any], tickers: List[str], day: int
) -> List[str]:
    """Rank tickers using only data available up to the current episode day."""
    scored = []
    for ticker in tickers:
        composite = rolling_signal_score(dataset.get(ticker), day)
        scored.append((ticker, composite))

    scored.sort(key=lambda x: x[1], reverse=True)
    return [t for t, _ in scored]
