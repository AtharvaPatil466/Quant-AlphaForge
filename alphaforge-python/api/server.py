"""
AlphaForge Python API — FastAPI server.

Run with: uvicorn api.server:app --reload
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import health, backtest, scanner, factors, correlation, optimize, market
from version import __version__
from data.universe import SECTORS, get_tickers
from data.synthetic import generate_prices, generate_dataset, PriceSeries
from api.schemas import UniverseResponse, SectorsResponse, PriceSeriesResponse

app = FastAPI(
    title="AlphaForge Alpha Engine",
    version=__version__,
    description="Quantitative alpha research API — synthetic data, factor scoring, backtesting.",
)

# CORS — allow all origins for local dev (file:// sends origin=null)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount route modules
PREFIX = "/api/v1"
app.include_router(health.router, prefix=PREFIX)
app.include_router(backtest.router, prefix=PREFIX)
app.include_router(scanner.router, prefix=PREFIX)
app.include_router(factors.router, prefix=PREFIX)
app.include_router(correlation.router, prefix=PREFIX)
app.include_router(optimize.router, prefix=PREFIX)
app.include_router(market.router, prefix=PREFIX)


# Inline routes that don't need their own file
@app.get(f"{PREFIX}/universe", response_model=UniverseResponse)
def universe(sector: str = "Technology"):
    tickers = get_tickers(sector)
    return UniverseResponse(tickers=[t.ticker for t in tickers])


@app.get(f"{PREFIX}/sectors", response_model=SectorsResponse)
def sectors():
    return SectorsResponse(sectors=SECTORS)


@app.get(f"{PREFIX}/price-series", response_model=PriceSeriesResponse)
def price_series(ticker: str = "AAPL", days: int = 504, seed: int = 42):
    """Get synthetic price series for a single ticker."""
    prices, volumes = generate_prices(ticker, days, seed)
    return PriceSeriesResponse(
        ticker=ticker,
        prices=prices.tolist(),
        volumes=volumes.tolist(),
    )
