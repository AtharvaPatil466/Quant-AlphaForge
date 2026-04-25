"""Pydantic request/response models for the AlphaForge API."""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from data.universe import SECTORS
from factors.registry import JS_FACTOR_NAMES


# ── Request Models ───────────────────────────────────────────────────────────

class BacktestRequest(BaseModel):
    sector: str = Field("Technology", description="Sector name or 'All'")
    lookback: int = Field(252, ge=21, le=504)
    factor_name: str = Field("Momentum (12-1)")
    holding_period: int = Field(10, ge=1, le=60)
    position_size: int = Field(10, ge=1, le=20)
    stop_loss: float = Field(5.0, ge=1.0, le=15.0)
    tx_cost_bps: int = Field(5, ge=0, le=100)
    data_source: str = Field("synthetic", description="synthetic or real")
    end_date: Optional[str] = Field(None, description="Optional market end date for real data")


# ── Response Models ──────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    version: str


class BacktestMetricsResponse(BaseModel):
    sharpe: Optional[float] = None
    total_return: Optional[float] = None
    bench_return: Optional[float] = None
    max_dd: Optional[float] = None
    max_dd_day: int = 0
    win_rate: Optional[float] = None
    ann_vol: Optional[float] = None
    calmar: Optional[float] = None
    sortino: Optional[float] = None
    ann_return: Optional[float] = None


class BacktestResponse(BaseModel):
    nav: List[float]
    benchmark_nav: List[float]
    drawdowns: List[float]
    monthly_returns: List[float]
    daily_returns: List[float]
    metrics: BacktestMetricsResponse
    error: Optional[str] = None


class ScannerItemResponse(BaseModel):
    ticker: str
    name: str
    composite: float
    signal: str
    ret5d: float
    volume: float
    price: float
    factor_scores: Dict[str, float]


class FactorScoreResponse(BaseModel):
    ticker: str
    name: str
    raw_score: float
    score: float
    signal: str


class CorrelationResponse(BaseModel):
    matrix: List[List[float]]
    ic: List[float]
    turnover: List[float]
    factors: List[str]


class UniverseResponse(BaseModel):
    tickers: List[str]


class SectorsResponse(BaseModel):
    sectors: List[str]


class FactorsListResponse(BaseModel):
    factors: List[str]


class PriceSeriesResponse(BaseModel):
    ticker: str
    prices: List[float]
    volumes: List[float]


class MarketAvailabilityItem(BaseModel):
    ticker: str
    clean: bool
    clean_trading_days: int
    usable_start: Optional[str] = None
    usable_end: Optional[str] = None
    issue_codes: List[str] = Field(default_factory=list)


class MarketAvailabilityResponse(BaseModel):
    items: List[MarketAvailabilityItem]


class LivePriceItem(BaseModel):
    ticker: str
    date: Optional[str] = None
    close: float
    volume: float


class LivePricesResponse(BaseModel):
    items: List[LivePriceItem]


class OptimizeRequest(BaseModel):
    sector: str = Field("Technology", description="Sector name or 'All'")
    lookback: int = Field(252, ge=21, le=504)
    risk_aversion: float = Field(1.0, ge=0.01, le=100.0)
    target_return: Optional[float] = Field(None, description="Target annualized return")
    mode: str = Field("long_short", description="long_only, long_short, or market_neutral")
    max_weight: float = Field(0.20, ge=0.01, le=1.0)
    min_weight: float = Field(-0.20, ge=-1.0, le=0.0)
    max_gross_leverage: float = Field(2.0, ge=0.1, le=5.0)
    max_positions: int = Field(0, ge=0, description="0 = no limit")
    shrinkage_alpha: float = Field(0.5, ge=0.0, le=1.0)
    cov_shrinkage: float = Field(0.1, ge=0.0, le=1.0)


class OptimizeResponse(BaseModel):
    weights: Dict[str, float]
    expected_return: float
    expected_vol: float
    expected_sharpe: float
    n_long: int
    n_short: int
    gross_leverage: float
    net_exposure: float
    factor_exposures: Dict[str, float]
    tickers: List[str]


class ErrorResponse(BaseModel):
    error: str
    detail: str
