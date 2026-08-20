"""Intraday price fetching, storage, and cleanup for live day view."""

from collections.abc import Iterable
from datetime import date, datetime, time, timedelta, timezone
from typing import cast
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import AssetRef
from app.domain.phases import PHASE_TO_SESSION, Phase, Session
from app.models.intraday import IntradayPrice
from app.schemas.intraday import IntradayBar
from app.services.intraday_aggregator import IntradayBucket

ET = ZoneInfo("America/New_York")


def _classify_session(ts: datetime, ref: AssetRef, tz_name: str | None = None) -> Session:
    """Classify a bar timestamp as pre/regular/post.

    Venue-schedule based (``ref.venue.phase``): holiday- and half-day-aware
    — the old hand-maintained wall-clock table filed bars after a 13:00 ET
    early close as "regular". Venues without extended hours can still print
    auction/late bars outside regular sessions; those "closed" instants are
    filed to the nearer session boundary (evening → post, next morning →
    pre) to preserve the 3-value storage.

    Fallback when no venue resolves: wall-clock against the bar's own
    exchange timezone with generic 09:00–17:30 hours, or US Eastern regular
    hours when even the timezone is unknown.
    """
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)

    venue = ref.venue
    if venue is not None:
        phase = venue.phase(ts)
        if phase in PHASE_TO_SESSION:
            return PHASE_TO_SESSION[phase]
        if phase == Phase.CLOSED:
            prev_close = venue.previous_close(ts)
            next_open = venue.next_open(ts)
            if prev_close is not None and next_open is not None:
                return Session.POST if ts - prev_close <= next_open - ts else Session.PRE
            return Session.POST

    if tz_name:
        try:
            local = ts.astimezone(ZoneInfo(tz_name)).time()
        except Exception:
            local = None
        if local is not None:
            if local < time(9, 0):
                return Session.PRE
            if local >= time(17, 30):
                return Session.POST
            return Session.REGULAR

    local = ts.astimezone(ET).time()
    if local < time(9, 30):
        return Session.PRE
    if local >= time(16, 0):
        return Session.POST
    return Session.REGULAR


async def get_intraday_bars(
    db: AsyncSession,
    refs: list[AssetRef],
) -> dict[str, list[IntradayBar]]:
    """Read the current window of intraday bars from DB, keyed by symbol.

    The window spans since yesterday's midnight ET (covers pre-market and
    the previous close), not just today.
    """
    by_id = {ref.id: ref for ref in refs if ref.id is not None}
    if not by_id:
        return {}

    # Fetch bars from last 2 days (covers pre-market + previous close)
    cutoff = datetime.now(ET).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)

    result = await db.execute(
        select(IntradayPrice)
        .where(
            IntradayPrice.asset_id.in_(by_id),
            IntradayPrice.timestamp >= cutoff,
        )
        .order_by(IntradayPrice.asset_id, IntradayPrice.timestamp)
    )
    rows = result.scalars().all()

    bars_by_symbol: dict[str, list[IntradayBar]] = {}
    for row in rows:
        ref = by_id.get(row.asset_id)
        if ref is None:
            continue
        sym = ref.symbol
        bars_by_symbol.setdefault(sym, []).append(IntradayBar(
            time=int(row.timestamp.timestamp()),
            price=row.price,
            volume=row.volume,
            # DB column is str-typed but only ever stores the 3 session values
            # (written via _classify_session); Pydantic re-validates at runtime.
            session=cast(Session, row.session),
            open=row.price,
            high=row.price,
            low=row.price,
            close=row.price,
            status="completed",
        ))

    return bars_by_symbol


async def persist_live_intraday_bars(
    db: AsyncSession,
    refs: Iterable[AssetRef],
    bars: Iterable[IntradayBucket],
) -> int:
    """Persist completed live buckets without inventing missing minutes.

    The existing ``intraday_prices`` table intentionally stores the chart's
    close as ``price``.  Forming buckets remain in the in-memory aggregator
    and SSE stream; only a minute observed to have rolled over is persisted.
    """
    by_symbol = {ref.symbol.upper(): ref for ref in refs if ref.id is not None}
    rows = [
        {
            "asset_id": by_symbol[bar.symbol.upper()].id,
            "timestamp": bar.timestamp,
            "price": bar.close,
            "volume": bar.volume,
            "session": bar.session,
        }
        for bar in bars
        if bar.status == "completed" and bar.symbol.upper() in by_symbol
    ]
    if not rows:
        return 0

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
    await db.commit()
    return len(rows)


async def cleanup_old_intraday(db: AsyncSession) -> int:
    """Delete intraday data older than 1 day. Returns rows deleted."""
    today = date.today()
    cutoff = datetime.combine(today - timedelta(days=1), time.min, tzinfo=ET)
    result = await db.execute(
        delete(IntradayPrice).where(IntradayPrice.timestamp < cutoff)
    )
    await db.commit()
    return result.rowcount or 0
