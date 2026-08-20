import logging
from datetime import date

import pandas as pd
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import AssetRef
from app.models import PriceHistory

logger = logging.getLogger(__name__)


class PriceRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_by_asset(self, asset_id: int) -> list[PriceHistory]:
        result = await self.db.execute(
            select(PriceHistory)
            .where(PriceHistory.asset_id == asset_id)
            .order_by(PriceHistory.date)
        )
        return list(result.scalars().all())

    async def list_by_asset_since(self, asset_id: int, start: date) -> list[PriceHistory]:
        result = await self.db.execute(
            select(PriceHistory)
            .where(PriceHistory.asset_id == asset_id, PriceHistory.date >= start)
            .order_by(PriceHistory.date)
        )
        return list(result.scalars().all())

    async def get_dates_for_asset_between(
        self, asset_id: int, start: date, end: date
    ) -> set[date]:
        """Return persisted price dates in the inclusive range for one asset."""
        if end < start:
            return set()
        result = await self.db.execute(
            select(PriceHistory.date).where(
                PriceHistory.asset_id == asset_id,
                PriceHistory.date >= start,
                PriceHistory.date <= end,
            )
        )
        return set(result.scalars())

    async def list_by_assets_since(
        self, asset_ids: list[int], start: date
    ) -> list[PriceHistory]:
        if not asset_ids:
            return []
        result = await self.db.execute(
            select(PriceHistory)
            .where(
                PriceHistory.asset_id.in_(asset_ids),
                PriceHistory.date >= start,
            )
            .order_by(PriceHistory.asset_id, PriceHistory.date)
        )
        return list(result.scalars().all())

    async def get_latest_date(self, asset_ids: list[int]) -> date | None:
        if not asset_ids:
            return None
        result = await self.db.execute(
            select(func.max(PriceHistory.date)).where(
                PriceHistory.asset_id.in_(asset_ids)
            )
        )
        return result.scalar()

    async def get_first_dates(
        self, asset_ids: list[int], since: date
    ) -> dict[int, date]:
        if not asset_ids:
            return {}
        result = await self.db.execute(
            select(
                PriceHistory.asset_id,
                func.min(PriceHistory.date).label("first_date"),
            )
            .where(PriceHistory.asset_id.in_(asset_ids))
            .where(PriceHistory.date >= since)
            .group_by(PriceHistory.asset_id)
        )
        return {row.asset_id: row.first_date for row in result}

    async def get_last_dates(self, asset_ids: list[int]) -> dict[int, date]:
        if not asset_ids:
            return {}
        result = await self.db.execute(
            select(
                PriceHistory.asset_id,
                func.max(PriceHistory.date).label("last_date"),
            )
            .where(PriceHistory.asset_id.in_(asset_ids))
            .group_by(PriceHistory.asset_id)
        )
        return {row.asset_id: row.last_date for row in result}

    async def get_latest_closes(
        self, asset_ids: list[int]
    ) -> dict[int, tuple[date, float]]:
        """Latest stored (date, close) per asset."""
        if not asset_ids:
            return {}
        last_dates = (
            select(
                PriceHistory.asset_id,
                func.max(PriceHistory.date).label("last_date"),
            )
            .where(PriceHistory.asset_id.in_(asset_ids))
            .group_by(PriceHistory.asset_id)
            .subquery()
        )
        result = await self.db.execute(
            select(PriceHistory.asset_id, PriceHistory.date, PriceHistory.close).join(
                last_dates,
                (PriceHistory.asset_id == last_dates.c.asset_id)
                & (PriceHistory.date == last_dates.c.last_date),
            )
        )
        return {row.asset_id: (row.date, row.close) for row in result}

    async def get_prices_at_dates(
        self, asset_ids: list[int], dates: set[date]
    ) -> dict[tuple[int, date], float]:
        if not asset_ids or not dates:
            return {}
        result = await self.db.execute(
            select(PriceHistory)
            .where(
                PriceHistory.asset_id.in_(asset_ids),
                PriceHistory.date.in_(list(dates)),
            )
        )
        return {
            (p.asset_id, p.date): p.close
            for p in result.scalars().all()
        }

    async def delete_prices_after(self, asset_id: int, last_date: date) -> int:
        """Delete stored bars strictly after ``last_date`` for one asset.

        Purges a stale current-session partial that a re-sync dropped from its
        fetched frame but left orphaned in the DB — an upsert can only update
        the rows it received, never remove one it no longer has. Returns the
        number of rows deleted.
        """
        result = await self.db.execute(
            delete(PriceHistory).where(
                PriceHistory.asset_id == asset_id,
                PriceHistory.date > last_date,
            )
        )
        await self.db.commit()
        return result.rowcount or 0

    @staticmethod
    def build_price_rows(ref: AssetRef, df: pd.DataFrame) -> list[dict]:
        """Convert a price DataFrame to insertable row dicts.

        Rows with a NaN in any OHLC column are skipped — but never silently:
        a skipped bar leaves a hole in price_history that is indistinguishable
        from a market holiday downstream (it inflates σ-Move, issue #559), so
        every skip is logged with its dates.
        """
        ohlc_cols = ["open", "high", "low", "close"]
        rows = []
        skipped: list[date] = []
        for idx, row in df.iterrows():
            dt = idx.date() if hasattr(idx, "date") else idx
            if not isinstance(dt, date):
                dt = pd.Timestamp(dt).date()

            if row[ohlc_cols].isna().any():
                skipped.append(dt)
                continue

            rows.append({
                "asset_id": ref.id,
                "date": dt,
                "open": round(float(row["open"]), 4),
                "high": round(float(row["high"]), 4),
                "low": round(float(row["low"]), 4),
                "close": round(float(row["close"]), 4),
                "volume": int(row["volume"]) if pd.notna(row["volume"]) else 0,
            })

        if skipped:
            logger.warning(
                "Skipped %d price bar(s) with NaN OHLC for %s (asset_id=%d) "
                "(dates: %s) — this leaves a gap in price_history",
                len(skipped), ref, ref.id,
                ", ".join(d.isoformat() for d in skipped),
            )
        return rows

    async def upsert_prices(self, ref: AssetRef, df: pd.DataFrame) -> int:
        """Upsert price rows from a DataFrame. Returns row count.

        Uses PostgreSQL ON CONFLICT DO UPDATE. For SQLite (tests), this
        method is typically mocked.
        """
        if df.empty:
            return 0

        from sqlalchemy.dialects.postgresql import insert as pg_insert

        rows = self.build_price_rows(ref, df)
        if not rows:
            return 0

        stmt = pg_insert(PriceHistory).values(rows)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_asset_date",
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
            },
        )
        await self.db.execute(stmt)
        await self.db.commit()
        return len(rows)
