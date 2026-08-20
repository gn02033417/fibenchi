from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import PeriodType
from app.database import get_db
from app.schemas.price import AssetDetailResponse, IndicatorResponse, PriceResponse, RefreshResponse
from app.services import price_service
from app.services.entity_lookups import find_asset, get_asset

router = APIRouter(prefix="/api/assets/{symbol}", tags=["prices"])


@router.get("/prices", response_model=list[PriceResponse], summary="Get OHLCV price history")
async def get_prices(symbol: str, period: PeriodType = Query("3mo"), db: AsyncSession = Depends(get_db)):
    """Return daily OHLCV price history for a symbol.

    For tracked assets, prices are read from the database (and auto-synced
    from the configured Taiwan provider if the requested period isn't yet
    covered). For untracked symbols, the provider fetch is ephemeral.

    Supported periods: `1mo`, `3mo` (default), `6mo`, `1y`, `2y`, `5y`.
    """
    asset = await find_asset(symbol, db)
    return await price_service.get_prices(db, asset, symbol, period)


@router.get("/indicators", response_model=list[IndicatorResponse], summary="Get technical indicators (RSI, SMA, MACD, Bollinger, ATR, ADX)")
async def get_indicators(symbol: str, period: PeriodType = Query("3mo"), db: AsyncSession = Depends(get_db)):
    """Return daily indicator time series for a symbol.

    Includes RSI (14), SMA 20/50, Bollinger Bands (20, 2σ), MACD (12/26/9),
    ATR (14), and ADX (14) with +DI/-DI.
    An extra 80-day warmup window is fetched internally so that the first
    returned data point already has converged indicator values.

    Supported periods: `1mo`, `3mo` (default), `6mo`, `1y`, `2y`, `5y`.
    """
    asset = await find_asset(symbol, db)
    return await price_service.get_indicators(db, asset, symbol, period)


@router.get("/detail", response_model=AssetDetailResponse, summary="Get prices and indicators in one call")
async def get_detail(symbol: str, period: PeriodType = Query("3mo"), db: AsyncSession = Depends(get_db)):
    """Return both OHLCV prices and technical indicators for a symbol in a single request.

    Avoids the need for parallel `/prices` + `/indicators` calls from the frontend,
    sharing the data-loading step.

    Supported periods: `1mo`, `3mo` (default), `6mo`, `1y`, `2y`, `5y`.
    """
    asset = await find_asset(symbol, db)
    return await price_service.get_detail(db, asset, symbol, period)


@router.post("/refresh", response_model=RefreshResponse, status_code=200, summary="Force-refresh Taiwan prices")
async def refresh_prices(symbol: str, period: PeriodType = Query("3mo"), db: AsyncSession = Depends(get_db)):
    """Force a re-sync of price data from the configured Taiwan provider.

    Returns the number of price points upserted.
    """
    asset = await get_asset(symbol, db)
    return await price_service.refresh_prices(db, asset, period)
