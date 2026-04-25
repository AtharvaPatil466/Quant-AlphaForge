from fastapi import APIRouter, HTTPException, Query

from api.schemas import FactorsListResponse, FactorScoreResponse
from factors.registry import JS_FACTOR_NAMES
from scanner.scanner import compute_factor_scores
from data.universe import SECTORS

router = APIRouter()


@router.get("/factors", response_model=FactorsListResponse)
def list_factors():
    return FactorsListResponse(factors=list(JS_FACTOR_NAMES))


@router.get("/factors/{factor_name}", response_model=list[FactorScoreResponse])
def factor_scores(
    factor_name: str,
    sector: str = Query("Technology"),
    lookback: int = Query(252, ge=21, le=504),
    data_source: str = Query("synthetic", pattern="^(synthetic|real)$"),
    end_date: str | None = Query(None),
):
    if factor_name not in JS_FACTOR_NAMES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid factor '{factor_name}'. Valid: {list(JS_FACTOR_NAMES)}",
        )
    valid = SECTORS + ["All"]
    if sector not in valid:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid sector '{sector}'. Valid: {valid}",
        )

    scores = compute_factor_scores(
        sector,
        lookback,
        factor_name,
        data_source=data_source,
        end_date=end_date,
    )
    return [
        FactorScoreResponse(
            ticker=s.ticker,
            name=s.name,
            raw_score=s.raw_score,
            score=s.score,
            signal=s.signal,
        )
        for s in scores
    ]
