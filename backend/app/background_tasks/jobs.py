"""The application's background jobs, moved out of ``main.py``.

Each job registers itself with :func:`background_task`; ``main.py``'s
lifespan schedules the registry wholesale. Job bodies own their DB sessions
and swallow their own exceptions — a failing run logs and waits for the next
trigger, never crashes the scheduler.
"""

import logging

from apscheduler.triggers.cron import CronTrigger

from app.background_tasks.registry import background_task
from app.config import settings as app_settings
from app.database import async_session
from app.services.compute.group import compute_and_cache_indicators
from app.services.intraday import cleanup_old_intraday
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
    are intentionally not fetched by the Taiwan build.
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


@background_task("price_refresh", trigger=_refresh_trigger)
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
