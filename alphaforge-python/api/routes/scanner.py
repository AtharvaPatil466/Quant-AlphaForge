from fastapi import APIRouter, HTTPException, Query

from api.schemas import ScannerItemResponse
from scanner.scanner import scan_universe
from data.universe import SECTORS

router = APIRouter()


@router.get("/scanner", response_model=list[ScannerItemResponse])
def scanner(
    sector: str = Query("All"),
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

    results = scan_universe(
        sector=sector,
        lookback=lookback,
        data_source=data_source,
        end_date=end_date,
    )
    return [
        ScannerItemResponse(
            ticker=r.ticker,
            name=r.name,
            composite=r.composite,
            signal=r.signal,
            ret5d=r.ret5d,
            volume=r.volume,
            price=r.price,
            factor_scores=r.factor_scores,
        )
        for r in results
    ]
