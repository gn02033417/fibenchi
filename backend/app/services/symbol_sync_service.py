"""Sync service — orchestrates provider execution and symbol_directory upserts."""

import logging
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.symbol_directory import SymbolDirectory
from app.models.symbol_source import SymbolSource
from app.services.symbol_providers import get_provider

logger = logging.getLogger(__name__)


async def sync_source(source_id: int, db: AsyncSession) -> int:
    """Sync a single symbol source: fetch from provider → upsert into symbol_directory.

    Returns the number of symbols synced.
    """
    source = await db.get(SymbolSource, source_id)
    if source is None:
        raise ValueError(f"Symbol source {source_id} not found")

    provider = get_provider(source.provider_type)
    entries = await provider.fetch_symbols(source.config)

    if not entries:
        logger.warning("Provider %s returned 0 symbols for source %d", source.provider_type, source_id)
        source.last_synced_at = datetime.now(UTC).replace(tzinfo=None)
        await db.commit()
        return 0

    # Batch upsert into symbol_directory
    rows = [
        {
            "symbol": e.symbol,
            "name": e.name,
            "exchange": e.exchange,
            "type": e.type,
            "source_id": source_id,
            "last_seen": datetime.now(UTC).replace(tzinfo=None),
        }
        for e in entries
    ]

    stmt = pg_insert(SymbolDirectory).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["symbol"],
        set_={
            "name": stmt.excluded.name,
            "exchange": stmt.excluded.exchange,
            "type": stmt.excluded.type,
            "source_id": stmt.excluded.source_id,
            "last_seen": stmt.excluded.last_seen,
        },
    )
    await db.execute(stmt)

    # Update source stats
    source.symbol_count = len(entries)
    source.last_synced_at = datetime.now(UTC).replace(tzinfo=None)
    await db.commit()

    logger.info("Synced %d symbols for source %d (%s)", len(entries), source_id, source.name)
    return len(entries)


async def sync_all_enabled(db: AsyncSession) -> dict[int, int]:
    """Sync all enabled sources. Returns {source_id: count} for each."""
    stmt = select(SymbolSource).where(SymbolSource.enabled.is_(True))
    result = await db.execute(stmt)
    sources = result.scalars().all()

    counts: dict[int, int] = {}
    for source in sources:
        try:
            counts[source.id] = await sync_source(source.id, db)
        except Exception:
            logger.exception("Failed to sync source %d (%s)", source.id, source.name)
            counts[source.id] = 0

    return counts


async def nullify_source_symbols(source_id: int, db: AsyncSession) -> None:
    """Set source_id to NULL for all symbols belonging to this source."""
    stmt = (
        update(SymbolDirectory)
        .where(SymbolDirectory.source_id == source_id)
        .values(source_id=None)
    )
    await db.execute(stmt)


async def sync_taiwan_directory(db: AsyncSession, **kwargs):
    """Compatibility seam for the Taiwan reference/contract directory sync."""
    from app.services.taiwan_symbol_directory import sync_taiwan_symbol_directory

    return await sync_taiwan_symbol_directory(db, **kwargs)
