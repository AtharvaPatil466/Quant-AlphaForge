"""API route for mean-variance portfolio optimization."""

from fastapi import APIRouter, HTTPException

from api.schemas import OptimizeRequest, OptimizeResponse
from data.universe import SECTORS
from optimizer.mean_variance import OptimizeConfig, optimize_portfolio

router = APIRouter()


@router.post("/optimize", response_model=OptimizeResponse)
def optimize(req: OptimizeRequest):
    valid_sectors = SECTORS + ["All"]
    if req.sector not in valid_sectors:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid sector '{req.sector}'. Valid: {valid_sectors}",
        )
    if req.mode not in ("long_only", "long_short", "market_neutral"):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid mode '{req.mode}'. Valid: long_only, long_short, market_neutral",
        )

    config = OptimizeConfig(
        sector=req.sector,
        lookback=req.lookback,
        risk_aversion=req.risk_aversion,
        target_return=req.target_return,
        mode=req.mode,
        max_weight=req.max_weight,
        min_weight=req.min_weight,
        max_gross_leverage=req.max_gross_leverage,
        max_positions=req.max_positions,
        shrinkage_alpha=req.shrinkage_alpha,
        cov_shrinkage=req.cov_shrinkage,
    )

    result = optimize_portfolio(config)

    if result.error:
        raise HTTPException(status_code=400, detail=result.error)

    return OptimizeResponse(
        weights=result.weights,
        expected_return=result.expected_return,
        expected_vol=result.expected_vol,
        expected_sharpe=result.expected_sharpe,
        n_long=result.n_long,
        n_short=result.n_short,
        gross_leverage=result.gross_leverage,
        net_exposure=result.net_exposure,
        factor_exposures=result.factor_exposures,
        tickers=result.tickers,
    )
