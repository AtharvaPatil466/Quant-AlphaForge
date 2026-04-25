from fastapi import APIRouter, HTTPException

from api.schemas import BacktestRequest, BacktestResponse, BacktestMetricsResponse
from backtest.engine import BacktestConfig, run_synthetic_backtest
from backtest.real_engine import run_real_backtest
from data.universe import SECTORS
from factors.registry import JS_FACTOR_NAMES

router = APIRouter()


def _validate_sector(sector: str) -> None:
    valid = SECTORS + ["All"]
    if sector not in valid:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid sector '{sector}'. Valid: {valid}",
        )


def _validate_factor(name: str) -> None:
    if name not in JS_FACTOR_NAMES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid factor '{name}'. Valid: {JS_FACTOR_NAMES}",
        )


@router.post("/backtest", response_model=BacktestResponse)
def backtest(req: BacktestRequest):
    _validate_sector(req.sector)
    _validate_factor(req.factor_name)

    config = BacktestConfig(
        sector=req.sector,
        lookback=req.lookback,
        factor_name=req.factor_name,
        holding_period=req.holding_period,
        position_size=req.position_size,
        stop_loss=req.stop_loss,
        tx_cost_bps=req.tx_cost_bps,
    )
    if req.data_source == "real":
        result = run_real_backtest(config, end_date=req.end_date)
    else:
        result = run_synthetic_backtest(config)

    if result.error:
        raise HTTPException(status_code=400, detail=result.error)

    return BacktestResponse(
        nav=result.nav,
        benchmark_nav=result.benchmark_nav,
        drawdowns=result.drawdowns,
        monthly_returns=result.monthly_returns,
        daily_returns=result.daily_returns,
        metrics=BacktestMetricsResponse(
            sharpe=result.metrics.sharpe,
            total_return=result.metrics.total_return,
            bench_return=result.metrics.bench_return,
            max_dd=result.metrics.max_dd,
            max_dd_day=result.metrics.max_dd_day,
            win_rate=result.metrics.win_rate,
            ann_vol=result.metrics.ann_vol,
            calmar=result.metrics.calmar,
            sortino=result.metrics.sortino,
            ann_return=result.metrics.ann_return,
        ),
    )
