"""The application's background jobs, moved out of ``main.py``.

Each job registers itself with :func:`background_task`; ``main.py``'s
lifespan schedules the registry wholesale. Job bodies own their DB sessions
and swallow their own exceptions — a failing run logs and waits for the next
trigger, never crashes the scheduler.
"""

import logging

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.background_tasks.price_heal import heal_interior_holes, heal_unreconciled_prices
from app.background_tasks.registry import background_task
from app.config import settings as app_settings
from app.database import async_session
from app.services.compute.group import compute_and_cache_indicators
from app.services.intraday import cleanup_old_intraday, fetch_and_store_intraday
from app.services.market_calendar import any_venue_open
from app.services.price_sync import sync_all_prices
from app.services.symbol_sync_service import sync_all_enabled as sync_all_symbol_sources
from app.services.symbol_sync_service import sync_taiwan_directory

logger = logging.getLogger(__name__)


async def warm_all_group_caches() -> int:
    """Pre-compute indicator snapshots for every group so the first request
    on any group page hits a warm cache. Returns the number of groups warmed.

    Each group is warmed in its own DB session so a slow group doesn't hold
    a connection longer than necessary. Failures on one group are logged
    and do not stop subsequent groups.
    """
    from app.repositories.group_repo import GroupRepository

    async with async_session() as db:
        try:
            groups = await GroupRepository(db).list_all()
        except Exception:
            logger.exception("Failed to load groups for cache warming")
            return 0

    warmed = 0
    for group in groups:
        async with async_session() as db:
            try:
                snapshot = await compute_and_cache_indicators(db, group_id=group.id)
                if snapshot:
                    warmed += 1
            except Exception:
                logger.exception(f"Cache warm failed for group {group.id} ({group.name})")
    return warmed


async def startup_warmup() -> None:
    """Pre-compute indicator caches at startup.

    Not a scheduled task — the lifespan runs it once as an asyncio task so
    the API is reachable immediately while the cache builds. Fundamentals
    lazy-fetch via :func:`merge_fundamentals_from_cache` so we don't burst
    at Yahoo at boot.
    """
    logger.info("Starting background cache warmup...")
    try:
        warmed = await warm_all_group_caches()
        if warmed:
            logger.info(f"Startup warmup complete: {warmed} groups cached")
    except Exception:
        logger.exception("Startup indicator warmup failed (non-fatal)")


def _refresh_trigger() -> CronTrigger | None:
    """Primary refresh trigger from ``REFRESH_CRON`` (minute hour day month dow).

    A malformed value disables only this job — loudly. (Previously the whole
    scheduler block sat behind the 5-field check, so a bad cron silently
    killed every background job, including ones that don't use it.)
    """
    parts = app_settings.refresh_cron.split()
    if len(parts) != 5:
        logger.warning(
            "Malformed REFRESH_CRON %r (expected 5 fields) — the price_refresh job is "
            "disabled; all other background jobs run normally",
            app_settings.refresh_cron,
        )
        return None
    return CronTrigger(
        minute=parts[0], hour=parts[1], day=parts[2],
        month=parts[3], day_of_week=parts[4],
    )


# Supplemental runs are safe because settled-price sync only fetches missing
# completed XTAI sessions. A daytime run never writes the active session and a
# post-close run picks up only the dates the database still lacks.
@background_task("price_refresh", trigger=_refresh_trigger)
@background_task("price_refresh_supplemental", trigger=CronTrigger(minute="0", hour="8,16"))
async def scheduled_refresh():
    """Sync missing settled price sessions, then re-warm indicator caches."""
    logger.info("Running scheduled settled-price sync...")
    async with async_session() as db:
        try:
            counts = await sync_all_prices(db)
            total = sum(counts.values())
            logger.info(f"Refreshed {len(counts)} assets, {total} price points")
        except Exception:
            logger.exception("Scheduled refresh failed")
            return

    try:
        warmed = await warm_all_group_caches()
        if warmed:
            logger.info(f"Pre-computed indicator caches for {warmed} groups")
    except Exception:
        logger.exception("Indicator pre-computation failed (non-fatal)")

    # Clean up old intraday data (keep only last 2 days)
    async with async_session() as db:
        try:
            deleted = await cleanup_old_intraday(db)
            if deleted:
                logger.info(f"Cleaned up {deleted} old intraday bars")
        except Exception:
            logger.exception("Intraday cleanup failed (non-fatal)")


@background_task("symbol_directory_sync", trigger=CronTrigger(minute="0", hour="2", day_of_week="sun"))
async def scheduled_symbol_sync():
    """Weekly sync of all enabled symbol directory sources."""
    logger.info("Running scheduled symbol directory sync...")
    async with async_session() as db:
        try:
            counts = await sync_all_symbol_sources(db)
            total = sum(counts.values())
            logger.info(f"Symbol sync complete: {len(counts)} sources, {total} symbols")
        except Exception:
            logger.exception("Scheduled symbol sync failed")


@background_task(
    "taiwan_symbol_directory_sync",
    trigger=CronTrigger(minute="0", hour="7", timezone="Asia/Taipei"),
)
async def scheduled_taiwan_symbol_directory_sync():
    """Refresh Taiwan reference/contract truth before the local market opens."""
    logger.info("Running scheduled Taiwan symbol directory sync...")
    async with async_session() as db:
        result = await sync_taiwan_directory(db)
        if result.status == "success":
            logger.info(
                "Taiwan symbol directory sync complete: %d active, %d inactive",
                result.active_count,
                result.inactive_count,
            )
        else:
            logger.error("Taiwan symbol directory sync failed: %s", result.error)


def _intraday_trigger() -> IntervalTrigger | None:
    """Keep the legacy Yahoo job out of the Taiwan/Shioaji scheduler."""
    if app_settings.price_provider.strip().lower() == "shioaji":
        logger.info("Legacy Yahoo intraday sync disabled for Shioaji mode")
        return None
    return IntervalTrigger(seconds=60)


@background_task("intraday_sync", trigger=_intraday_trigger)
async def scheduled_intraday_sync():
    """Fetch 1m intraday bars for all grouped assets."""
    if app_settings.price_provider.strip().lower() == "shioaji":
        logger.debug("Skipping legacy Yahoo intraday sync in Shioaji mode")
        return
    from app.repositories.asset_repo import AssetRepository

    async with async_session() as db:
        try:
            refs = await AssetRepository(db).list_in_any_group_refs()
            if not refs:
                return

            # Venue-schedule gate. This replaces quoting 15 *random* symbols
            # per tick to sniff for an active market — a Yahoo round-trip
            # every 60s that could still miss the one open venue (3 Tokyo
            # listings in a 200-symbol portfolio → ~80% miss). The calendar
            # answer is deterministic, holiday-aware, and free.
            if not any_venue_open(refs):
                return

            count = await fetch_and_store_intraday(db, refs)
            if count:
                logger.info(f"Intraday sync: {count} bars for {len(refs)} symbols")
        except Exception:
            logger.exception("Intraday sync failed")


# Self-heal stragglers the scheduled refreshes missed: when a symbol's latest
# stored bar reconciles with neither the live price nor the quote's previous
# close (the state that blanks σ-Move), refresh just that symbol instead of
# waiting for the next full run.
@background_task("price_heal", trigger=IntervalTrigger(minutes=10))
async def scheduled_price_heal():
    """Refresh symbols whose stored bars contradict live quotes."""
    async with async_session() as db:
        # While every tracked venue is closed, quotes are frozen and no stored
        # bar can newly diverge — skip the full portfolio quote scan. The venue
        # schedule replaces the old weekday() proxy, which ran all day on
        # global holidays, skipped crypto weekends, and used the server-local
        # date (Monday morning in Tokyo is still Sunday here).
        from app.repositories.asset_repo import AssetRepository

        refs = await AssetRepository(db).list_in_any_group_refs()
        if not refs or not any_venue_open(refs):
            return
        try:
            healed = await heal_unreconciled_prices(db)
            if healed:
                logger.info(
                    f"Price heal: refreshed {len(healed)} symbol(s): {', '.join(sorted(healed))}"
                )
        except Exception:
            logger.exception("Price heal failed")
        try:
            # Mid-series holes (issue #559): self-throttled to one scan per
            # HOLE_SCAN_INTERVAL, so piggybacking on this job costs nothing.
            filled = await heal_interior_holes(db)
            if filled:
                logger.info(
                    f"Hole heal: refreshed {len(filled)} symbol(s): {', '.join(sorted(filled))}"
                )
        except Exception:
            logger.exception("Hole heal failed")
