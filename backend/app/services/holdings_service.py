"""Disabled ETF holdings seam for the pure Taiwan build."""

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

_DISABLED_DETAIL = "ETF holdings are not enabled in the Taiwan build"


async def get_holdings(db: AsyncSession, symbol: str) -> dict:
    """Raise a stable response for the intentionally disabled feature."""
    raise HTTPException(status_code=410, detail=_DISABLED_DETAIL)


async def get_holdings_indicators(db: AsyncSession, symbol: str) -> list:
    """Raise a stable response for the intentionally disabled feature."""
    raise HTTPException(status_code=410, detail=_DISABLED_DETAIL)
