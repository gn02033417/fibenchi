"""Legacy Yahoo intraday persistence kept outside the Taiwan runtime path."""

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import AssetRef
from app.models.intraday import IntradayPrice
from app.services.intraday import _classify_session
from app.services.yahoo import yahoo_client


async def fetch_and_store_intraday(
    db: AsyncSession,
    refs: list[AssetRef],
) -> int:
    """Fetch Yahoo 1m bars and persist them for legacy provider tests/users."""
    raw = await yahoo_client.intraday(list(refs))
    by_symbol = {ref.symbol: ref for ref in refs}

    total = 0
    for sym, raw_bars in raw.items():
        ref = by_symbol.get(sym)
        if ref is None or ref.id is None or not raw_bars:
            continue
        asset_id = ref.id

        oldest_ts = min(bar.timestamp for bar in raw_bars)
        await db.execute(
            delete(IntradayPrice).where(
                IntradayPrice.asset_id == asset_id,
                IntradayPrice.timestamp < oldest_ts,
            )
        )

        rows = [
            {
                "asset_id": asset_id,
                "timestamp": bar.timestamp,
                "price": bar.price,
                "volume": bar.volume,
                "session": _classify_session(bar.timestamp, ref, bar.tz_name),
            }
            for bar in raw_bars
        ]

        stmt = pg_insert(IntradayPrice).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["asset_id", "timestamp"],
            set_={
                "price": stmt.excluded.price,
                "volume": stmt.excluded.volume,
                "session": stmt.excluded.session,
            },
        )
        await db.execute(stmt)
        total += len(rows)

    await db.commit()
    return total
