import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

from app.background_tasks import all_tasks, startup_warmup
from app.config import settings as app_settings
from app.database import async_session, engine
from app.models.symbol_directory import TAIWAN_EXCHANGES
from app.repositories.asset_repo import AssetRepository
from app.repositories.group_repo import GroupRepository
from app.routers import (
    annotations,
    assets,
    companion,
    data,
    groups,
    holdings,
    indicators,
    market,
    note,
    portfolio,
    prices,
    pseudo_etf_analysis,
    pseudo_etfs,
    quotes,
    search,
    sparklines,
    symbol_sources,
    system,
    tags,
    thesis,
)
from app.routers import settings as settings_router
from app.services import quote_service
from app.services.currency_service import load_cache as load_currency_cache
from app.services.intraday import persist_live_intraday_bars
from app.services.intraday_aggregator import IntradayAggregator
from app.services.live_quote_store import LiveQuoteStore
from app.services.price_providers import init_price_provider
from app.services.realtime_demand import RealtimeDemandController
from app.services.realtime_priority import compute_wanted_symbols
from app.services.shioaji.stream import ShioajiQuoteStream, ShioajiQuoteSubscription
from app.services.subscription_manager import SubscriptionManager

# App loggers write through the root logger, which neither uvicorn nor docker
# configures — so every logger.info() (price heal, hole heal, refresh
# summaries, dropped-bar notices) was silently discarded and only WARNING+
# reached `docker logs`. That cost real diagnostic time in the 2026-08-05
# incident. basicConfig is a no-op when handlers already exist (pytest, etc.),
# and uvicorn's own loggers don't propagate to root, so nothing is duplicated.
logging.basicConfig(
    level=getattr(logging, app_settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def _tracked_quote_subscriptions() -> list[ShioajiQuoteSubscription]:
    """Build a deterministic Taiwan Quote subscription set from tracked assets."""
    demand = await quote_service.get_realtime_demand_snapshot()
    async with async_session() as db:
        refs = await AssetRepository(db).list_in_any_group_refs()
        group_repo = GroupRepository(db)
        priority_groups = await group_repo.list_realtime_priority_groups()
        active_groups = [
            group
            for group_id in demand.active_group_ids
            if (group := await group_repo.get_by_id(group_id)) is not None
        ]

    subscriptions_by_symbol: dict[str, ShioajiQuoteSubscription] = {}
    for ref in refs:
        if ref.exchange not in TAIWAN_EXCHANGES:
            continue
        subscription = ShioajiQuoteSubscription(code=ref.symbol, exchange=ref.exchange)
        subscriptions_by_symbol.setdefault(subscription.code, subscription)

    def subscribed_symbols(group) -> list[str]:
        return [
            asset.symbol.upper()
            for asset in group.assets
            if asset.symbol.upper() in subscriptions_by_symbol
        ]

    wanted_symbols = compute_wanted_symbols(
        active_assets=(symbol for symbol in demand.active_assets if symbol in subscriptions_by_symbol),
        realtime_priority_groups=[subscribed_symbols(group) for group in priority_groups],
        active_group_symbols=(
            symbol
            for group in active_groups
            for symbol in subscribed_symbols(group)
        ),
        tracked_symbols=subscriptions_by_symbol,
    )
    return [subscriptions_by_symbol[symbol] for symbol in wanted_symbols]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize the price data provider (Yahoo, IBKR, etc.)
    init_price_provider()

    # Load currency lookup cache from DB
    async with async_session() as db:
        await load_currency_cache(db)

    # Schedule the registered background jobs (app/background_tasks/jobs.py).
    # A task whose trigger factory returns None is disabled — it logged why —
    # but never takes the others down with it.
    for task in all_tasks():
        trigger = task.resolve_trigger()
        if trigger is None:
            continue
        scheduler.add_job(task.func, trigger, id=task.id)
    scheduler.start()
    logger.info(
        f"Scheduler started with {len(scheduler.get_jobs())} background jobs "
        f"(refresh cron: {app_settings.refresh_cron})"
    )

    # Kick off cache warmup in the background — API is reachable immediately,
    # cache builds in parallel so the first group hit is warm.
    warmup_task = asyncio.create_task(startup_warmup())
    live_quote_store = LiveQuoteStore()
    intraday_aggregator = IntradayAggregator()
    intraday_ref_cache = {}
    intraday_ref_lock = asyncio.Lock()

    async def consume_live_intraday(update) -> None:
        try:
            completed = [
                bar
                for bar in intraday_aggregator.ingest(update)
                if bar.status == "completed"
            ]
            if not completed:
                return

            symbols = {bar.symbol.upper() for bar in completed}
            async with intraday_ref_lock:
                missing = symbols - set(intraday_ref_cache)
                if missing:
                    async with async_session() as db:
                        refs = await AssetRepository(db).list_in_any_group_refs()
                    intraday_ref_cache.update({ref.symbol.upper(): ref for ref in refs})
                refs = [
                    intraday_ref_cache[symbol]
                    for symbol in symbols
                    if symbol in intraday_ref_cache
                ]

            if not refs:
                return
            async with async_session() as db:
                await persist_live_intraday_bars(db, refs, completed)
        except Exception:
            logger.exception("Live intraday aggregation/persistence failed")

    def mark_intraday_disconnected(symbols: tuple[str, ...]) -> None:
        intraday_aggregator.mark_disconnected(symbols)

    subscription_manager = SubscriptionManager(
        ShioajiQuoteStream(),
        live_quote_store,
        on_quote_update=consume_live_intraday,
        on_disconnect=mark_intraday_disconnected,
    )

    async def refresh_realtime_demand() -> None:
        await subscription_manager.reconcile(await _tracked_quote_subscriptions())

    realtime_demand_controller = RealtimeDemandController(refresh_realtime_demand)
    quote_service.configure_live_quote_store(live_quote_store)
    quote_service.configure_intraday_aggregator(intraday_aggregator)
    quote_service.configure_realtime_demand_controller(realtime_demand_controller)
    app.state.live_quote_store = live_quote_store
    app.state.intraday_aggregator = intraday_aggregator
    app.state.subscription_manager = subscription_manager
    app.state.realtime_demand_controller = realtime_demand_controller
    realtime_task = asyncio.create_task(
        subscription_manager.run_forever(_tracked_quote_subscriptions)
    )

    yield

    realtime_task.cancel()
    warmup_task.cancel()
    with suppress(asyncio.CancelledError):
        await realtime_task
    quote_service.configure_intraday_aggregator(None)
    quote_service.configure_realtime_demand_controller(None)
    app.state.realtime_demand_controller = None
    app.state.intraday_aggregator = None
    scheduler.shutdown(wait=False)
    await engine.dispose()


app = FastAPI(
    title="Fibenchi",
    summary="Investment research dashboard for tracking stocks, ETFs, and custom baskets.",
    description=(
        "Fibenchi is a self-hosted investment research tool. It lets you organize "
        "stocks and ETFs into groups, view OHLCV price charts with technical indicators "
        "(RSI, SMA, Bollinger Bands, MACD), write investment theses, and annotate charts "
        "with dated notes.\n\n"
        "**Pseudo-ETFs** are user-created baskets of assets with equal-weight allocation and "
        "quarterly rebalancing. They have their own indexed performance chart, per-constituent "
        "breakdown, and indicator snapshots.\n\n"
        "**Key concepts:**\n"
        "- Assets are stocks or ETFs identified by ticker symbol. Removing an asset from its "
        "last group preserves the row for pseudo-ETF relationships.\n"
        "- Prices are sourced from Yahoo Finance and cached in PostgreSQL. A daily cron job "
        "refreshes all grouped assets.\n"
        "- Ephemeral price views allow fetching prices for ungrouped symbols (e.g. ETF "
        "holdings) without persisting data.\n"
        "- Groups are user-defined collections of assets. The default 'Watchlist' group "
        "cannot be deleted or renamed. Per-group batch endpoints provide sparklines and "
        "indicator snapshots in a single request, avoiding N+1 queries.\n"
        "- Real-time quotes are delivered via SSE with delta compression — only symbols whose "
        "data changed since the last push are included.\n"
    ),
    version="1.1.0",
    lifespan=lifespan,
    openapi_tags=[
        {
            "name": "assets",
            "description": "Manage tracked stocks and ETFs. Assets are identified by ticker symbol and auto-validated against Yahoo Finance.",
        },
        {
            "name": "data",
            "description": (
                "General-purpose batch data query for external tooling. Fetch quotes, indicator "
                "snapshots, prices, and/or technical indicators for multiple tickers in a single "
                "request. Works for any ticker — tracked assets use cached DB data, untracked "
                "symbols are fetched ephemerally from the price provider."
            ),
        },
        {
            "name": "prices",
            "description": "OHLCV price data and technical indicators (RSI, SMA 20/50, Bollinger Bands, MACD) for individual assets. Supports both persisted (grouped) and ephemeral (ungrouped) price fetching.",
        },
        {
            "name": "holdings",
            "description": "ETF holdings breakdown and per-holding technical indicator snapshots. Only available for assets with type=etf.",
        },
        {
            "name": "portfolio",
            "description": "Portfolio-wide analytics: composite equal-weight index of all grouped assets, and top/bottom performer rankings by period return.",
        },
        {
            "name": "groups",
            "description": "User-defined groups for organizing assets into named collections. The default 'Watchlist' group is protected. Per-group batch endpoints provide sparklines and indicator snapshots in a single request.",
        },
        {
            "name": "tags",
            "description": "Colored labels for categorizing assets (e.g. 'tech', 'growth', 'dividend'). Tags can be attached to assets and used for dashboard filtering.",
        },
        {
            "name": "note",
            "description": "Free-text note per asset. Supports Markdown content.",
        },
        {
            "name": "theses",
            "description": "Global cross-cutting theses: thematic baskets of tickers tracked under one hypothesis, with a lifecycle status and open date. An asset can belong to many theses.",
        },
        {
            "name": "annotations",
            "description": "Dated chart annotations per asset. Each annotation has a date, title, body, and color for visual markers on price charts.",
        },
        {
            "name": "quotes",
            "description": (
                "Real-time market quotes via REST and SSE. The REST endpoint returns quotes for "
                "arbitrary symbols. The SSE stream pushes the shared Shioaji live quote state for "
                "all grouped assets: an initial snapshot followed by delta-compressed changes."
            ),
        },
        {
            "name": "pseudo-etfs",
            "description": "User-created custom baskets (pseudo-ETFs) with equal-weight allocation and quarterly rebalancing. Includes constituent management, indexed performance with per-symbol breakdown, technical indicator snapshots, note, and annotations.",
        },
        {
            "name": "settings",
            "description": "User preference storage for indicator visibility, chart preferences, and display options.",
        },
        {
            "name": "companion",
            "description": "Versioned config bundle (groups + tickers + tags) for the mobile companion app — tells it what to track; live data is fetched on-device.",
        },
        {
            "name": "system",
            "description": "Health checks and operational endpoints.",
        },
    ],
)

app.include_router(assets.router)
app.include_router(data.router)
app.include_router(groups.router)
app.include_router(companion.router)
app.include_router(tags.router)
app.include_router(tags.asset_tag_router)
app.include_router(portfolio.router)
app.include_router(prices.router)
app.include_router(holdings.router)
app.include_router(indicators.router)
app.include_router(market.router)
app.include_router(note.router)
app.include_router(thesis.router)
app.include_router(annotations.router)
app.include_router(pseudo_etfs.router)
app.include_router(pseudo_etf_analysis.router)
app.include_router(quotes.router)
app.include_router(settings_router.router)
app.include_router(search.router)
app.include_router(sparklines.router)
app.include_router(symbol_sources.router)
app.include_router(system.router)


@app.get("/api/health", summary="Health check", tags=["system"])
async def health():
    """Return `{\"status\": \"ok\"}` when the service is running."""
    return {"status": "ok"}


# --- SPA static serving (production only) ---
# In production the frontend is built into /app/static by the root Dockerfile.
# In dev this directory doesn't exist, so the mount is skipped entirely.
_SPA_DIR = Path(__file__).resolve().parent.parent / "static"

if (_SPA_DIR / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=_SPA_DIR / "assets"), name="static-assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def _spa_fallback(path: str):
        file = _SPA_DIR / path
        if file.is_file() and file.resolve().is_relative_to(_SPA_DIR.resolve()):
            return FileResponse(file)
        return FileResponse(_SPA_DIR / "index.html")
