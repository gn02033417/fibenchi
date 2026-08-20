"""Batch indicator computation and sparkline data for group asset pages."""

from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import PERIOD_DAYS, WARMUP_DAYS
from app.domain import AssetRef
from app.models import PriceHistory
from app.repositories.asset_repo import AssetRepository
from app.repositories.group_repo import GroupRepository
from app.repositories.price_repo import PriceRepository
from app.schemas.price import IndicatorSnapshotBase
from app.services.compute.indicators import build_indicator_snapshot, compute_indicators
from app.services.compute.utils import prices_to_df
from app.services.fundamentals_cache import merge_fundamentals_from_cache
from app.utils import TTLCache

# In-memory cache for batch indicator snapshots.
# Key: (frozenset of symbols, latest_price_date) — auto-invalidates when prices change.
_indicator_cache: TTLCache = TTLCache(default_ttl=600)


def invalidate_indicator_cache() -> None:
    """Discard snapshots after settled daily history changes in place."""
    _indicator_cache.clear()


async def _get_default_group_refs(db: AsyncSession) -> list[AssetRef]:
    """Get an AssetRef per asset in the default group."""
    group = await GroupRepository(db).get_default()
    if not group:
        return []
    return await AssetRepository(db).list_in_group_refs(group.id)


async def get_batch_sparklines(
    db: AsyncSession, period: str = "3mo", group_id: int | None = None,
) -> dict[str, list[dict]]:
    """Return close-price sparkline data for assets in a group.

    If group_id is None, uses the default group.
    """
    if group_id is not None:
        refs = await AssetRepository(db).list_in_group_refs(group_id)
    else:
        refs = await _get_default_group_refs(db)
    return await _sparklines_for_refs(db, period, refs)


async def get_sparklines_for_symbols(
    db: AsyncSession, symbols: list[str], period: str = "3mo",
) -> dict[str, list[dict]]:
    """Close-price sparklines for specific tracked symbols, keyed by symbol.

    The symbol-addressed sibling of the per-group batch, mirroring
    ``compute_indicators_for_symbols``. A roster that spans several groups is
    one call here instead of one per group — and symbols that repeat across
    groups are fetched once, not once per membership. Untracked symbols are
    omitted (no DB price history).
    """
    if not symbols:
        return {}
    refs = await AssetRepository(db).list_refs_by_symbols(symbols)
    return await _sparklines_for_refs(db, period, refs)


async def _sparklines_for_refs(
    db: AsyncSession, period: str, refs: list[AssetRef],
) -> dict[str, list[dict]]:
    """Close-price series per symbol over the period, in one price query."""
    days = PERIOD_DAYS.get(period, 90)
    start = date.today() - timedelta(days=days)

    if not refs:
        return {}

    by_id = {ref.id: ref for ref in refs if ref.id is not None}

    prices = await PriceRepository(db).list_by_assets_since(list(by_id), start)

    out: dict[str, list[dict]] = {ref.symbol: [] for ref in by_id.values()}
    for p in prices:
        ref = by_id.get(p.asset_id)
        if ref is not None:
            out[ref.symbol].append({"date": p.date.isoformat(), "close": round(p.close, 4)})

    return out


async def _compute_snapshots_for_refs(
    db: AsyncSession, refs: list[AssetRef],
) -> dict[str, IndicatorSnapshotBase]:
    """Compute DB-backed indicator snapshots for the refs, with caching.

    The snapshot *values* depend purely on (symbols, latest price date), so the
    cache is keyed by exactly that — identical symbol sets share entries across
    callers (group pages and the symbol-addressed indicators endpoint alike).
    """
    by_id = {ref.id: ref for ref in refs if ref.id is not None}
    if not by_id:
        return {}

    price_repo = PriceRepository(db)

    # Build cache key: symbols + latest price date (scope-independent by design)
    latest_date = await price_repo.get_latest_date(list(by_id))
    cache_key = (frozenset(ref.symbol for ref in by_id.values()), latest_date)

    cached = _indicator_cache.get_value(cache_key)
    if cached is not None:
        return cached

    # Fetch enough history for indicator warmup (SMA50 needs ~50 trading days)
    warmup_start = date.today() - timedelta(days=PERIOD_DAYS["3mo"] + WARMUP_DAYS)

    all_prices = await price_repo.list_by_assets_since(list(by_id), warmup_start)

    # Group prices by asset
    grouped: dict[int, list[PriceHistory]] = {}
    for p in all_prices:
        grouped.setdefault(p.asset_id, []).append(p)

    out: dict[str, IndicatorSnapshotBase] = {}
    for asset_id, ref in by_id.items():
        prices = grouped.get(asset_id, [])
        if len(prices) < 26:  # Need at least MACD slow period
            out[ref.symbol] = IndicatorSnapshotBase(bars=len(prices))
            continue

        df = prices_to_df(prices)

        venue = ref.venue
        sessions = venue.session_dates_for_index(df.index) if venue else None
        snapshot = build_indicator_snapshot(compute_indicators(df, session_dates=sessions))
        out[ref.symbol] = snapshot

    # Merge cached fundamental metrics; background-fetch any misses
    merge_fundamentals_from_cache([ref.symbol for ref in by_id.values()], out)

    # The cache hands out these model instances by reference, and the
    # fundamentals merge mutates their ``values`` in place — snapshots must
    # stay mutable (IndicatorSnapshotBase is deliberately not frozen).
    _indicator_cache.set_value(cache_key, out)

    return out


async def compute_and_cache_indicators(
    db: AsyncSession, group_id: int | None = None,
) -> dict[str, IndicatorSnapshotBase]:
    """Compute indicator snapshots for assets in a group, with caching.

    If group_id is None, uses the default group.
    """
    if group_id is not None:
        refs = await AssetRepository(db).list_in_group_refs(group_id)
    else:
        refs = await _get_default_group_refs(db)

    return await _compute_snapshots_for_refs(db, refs)


async def compute_indicators_for_symbols(
    db: AsyncSession, symbols: list[str],
) -> dict[str, IndicatorSnapshotBase]:
    """Compute indicator snapshots for specific tracked symbols (DB-backed).

    Mirrors the per-group snapshot shape but is addressable by symbol set rather
    than by group — used to fill indicator columns for thesis members that live in
    other groups. Unknown/untracked symbols are omitted (no DB price history).
    """
    if not symbols:
        return {}
    refs = await AssetRepository(db).list_refs_by_symbols(symbols)
    return await _compute_snapshots_for_refs(db, refs)
