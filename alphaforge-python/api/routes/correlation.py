from fastapi import APIRouter, HTTPException, Query

from api.schemas import CorrelationResponse
from correlation import compute_correlation_result
from data.universe import SECTORS

router = APIRouter()


@router.get("/correlation", response_model=CorrelationResponse)
def correlation(
    sector: str = Query("Technology"),
    lookback: int = Query(252, ge=21, le=504),
    data_source: str = Query("synthetic", pattern="^(synthetic|real)$"),
    end_date: str | None = Query(None),
):
    valid = SECTORS + ["All"]
    if sector not in valid:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid sector '{sector}'. Valid: {valid}",
        )

    result = compute_correlation_result(
        sector=sector,
        lookback=lookback,
        data_source=data_source,
        end_date=end_date,
    )
    return CorrelationResponse(
        matrix=result.matrix,
        ic=result.ic,
        turnover=result.turnover,
        factors=result.factors,
    )
