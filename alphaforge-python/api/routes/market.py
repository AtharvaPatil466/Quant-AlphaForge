from __future__ import annotations

import json

from fastapi import APIRouter, Query

from api.schemas import (
    LivePriceItem,
    LivePricesResponse,
    MarketAvailabilityItem,
    MarketAvailabilityResponse,
)
from data.market.loader import MarketDataError, MarketDataLoader
from data.market.paths import validation_report_path
from data.market.universe import ALL_REAL_TICKERS, REAL_UNIVERSE

router = APIRouter()


def _tickers_for_sector(sector: str) -> list[str]:
    if sector == "All":
        return list(ALL_REAL_TICKERS)
    return list(REAL_UNIVERSE.get(sector, REAL_UNIVERSE["Technology"]))


@router.get("/market/availability", response_model=MarketAvailabilityResponse)
def market_availability(sector: str = Query("All")):
    tickers = _tickers_for_sector(sector)
    loader = MarketDataLoader()
    report_path = validation_report_path()
    reported = {}
    if report_path.exists():
        payload = json.loads(report_path.read_text())
        reported = {
            item["ticker"]: item
            for item in payload.get("tickers", [])
        }

    items = []
    for ticker in tickers:
        details = reported.get(ticker, {})
        start = None
        end = None
        clean_trading_days = int(details.get("clean_trading_days", 0))
        try:
            start, end = loader.available_range(ticker)
            if clean_trading_days == 0 and start is not None:
                clean_trading_days = len(loader.load_ticker(ticker))
        except MarketDataError:
            pass
        items.append(
            MarketAvailabilityItem(
                ticker=ticker,
                clean=bool(details.get("clean", start is not None)),
                clean_trading_days=clean_trading_days,
                usable_start=details.get("usable_start", start.date().isoformat() if start is not None else None),
                usable_end=details.get("usable_end", end.date().isoformat() if end is not None else None),
                issue_codes=[issue["code"] for issue in details.get("issues", [])],
            )
        )
    return MarketAvailabilityResponse(items=items)


@router.get("/market/live-prices", response_model=LivePricesResponse)
def live_prices(sector: str = Query("All"), end_date: str | None = Query(None)):
    tickers = _tickers_for_sector(sector)
    loader = MarketDataLoader()
    latest = loader.load_latest(tickers, end_date=end_date)
    return LivePricesResponse(
        items=[
            LivePriceItem(
                ticker=ticker,
                date=row.name.date().isoformat() if hasattr(row.name, "date") else str(row.name),
                close=float(row.get("Close", 0.0)),
                volume=float(row.get("Volume", 0.0)),
            )
            for ticker, row in sorted(latest.items())
        ]
    )
