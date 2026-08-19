"""Search business logic backed only by the local Taiwan symbol directory."""

from sqlalchemy import case, or_, select
from sqlalchemy import func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.symbol_directory import TAIWAN_EXCHANGES, SymbolDirectory

_SUPPORTED_TYPES = ("stock", "etf")


async def _query_local(db: AsyncSession, query: str, limit: int = 8) -> list[dict]:
    """Search active, supported Taiwan rows by code or name."""
    query = query.strip().lower()
    if not query:
        return []

    symbol_lower = sa_func.lower(SymbolDirectory.symbol)
    name_lower = sa_func.lower(SymbolDirectory.name)
    pattern = f"%{query}%"
    prefix = f"{query}%"
    stmt = (
        select(SymbolDirectory)
        .where(
            SymbolDirectory.active.is_(True),
            SymbolDirectory.exchange.in_(TAIWAN_EXCHANGES),
            SymbolDirectory.type.in_(_SUPPORTED_TYPES),
            or_(
                symbol_lower.like(pattern),
                name_lower.like(pattern),
            ),
        )
        .order_by(
            case(
                (symbol_lower == query, 0),
                (symbol_lower.like(prefix), 1),
                (name_lower.like(prefix), 2),
                else_=3,
            ),
            symbol_lower,
            name_lower,
            SymbolDirectory.id,
        )
        .limit(limit)
    )
    result = await db.execute(stmt)
    return [
        {
            "symbol": row.symbol,
            "name": row.name,
            "exchange": row.exchange,
            "type": row.type,
        }
        for row in result.scalars().all()
    ]


async def search_symbols(query: str, db: AsyncSession) -> list[dict]:
    """Search the local Taiwan symbol directory without external fallback."""
    return await _query_local(db, query)


async def search_local(query: str, db: AsyncSession) -> list[dict]:
    """Compatibility alias for callers that explicitly request local search."""
    return await _query_local(db, query)
