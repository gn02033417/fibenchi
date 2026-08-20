"""Quote REST handling and event-driven browser SSE generation."""

import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

from pydantic import TypeAdapter

from app.database import async_session
from app.domain import AssetRef
from app.domain.market_state import any_active, state_info
from app.domain.phases import Phase
from app.repositories.asset_repo import AssetRepository
from app.schemas.intraday import IntradayBar
from app.schemas.quote import Quote
from app.services.intraday import get_intraday_bars
from app.services.live_quote_store import LiveQuoteStore
from app.services.market_calendar import schedule_poll_hint
from app.services.price_providers import get_price_provider
from app.services.realtime_demand import RealtimeDemandController, RealtimeDemandSnapshot

# Serializers for the browser SSE payloads (both keyed by symbol).
_quotes_payload_adapter = TypeAdapter(dict[str, Quote])
_intraday_payload_adapter = TypeAdapter(dict[str, list[IntradayBar]])
_live_quote_store = LiveQuoteStore()
_realtime_demand_controller: RealtimeDemandController | None = None


def configure_live_quote_store(store: LiveQuoteStore) -> None:
    """Bind browser SSE to the application-owned store from the lifespan."""
    global _live_quote_store
    _live_quote_store = store


def get_live_quote_store() -> LiveQuoteStore:
    return _live_quote_store


def configure_realtime_demand_controller(controller: RealtimeDemandController | None) -> None:
    """Bind connection-scoped browser demand to the application lifespan."""
    global _realtime_demand_controller
    _realtime_demand_controller = controller


async def get_realtime_demand_snapshot() -> RealtimeDemandSnapshot:
    controller = _realtime_demand_controller
    if controller is None:
        return RealtimeDemandSnapshot()
    return await controller.snapshot()


def _reset_asset_list_cache() -> None:
    """Compatibility seam retained for callers that reset quote-service state."""


def _poll_interval(market_states: set[str], symbols: Sequence[str], at=None) -> int:
    """Legacy schedule helper retained until Yahoo polling cleanup in TW-18."""
    if any(state_info(state).phase == Phase.OPEN for state in market_states):
        live = 15
    elif any_active(market_states):
        live = 60
    else:
        live = 300

    phase, next_open_secs = schedule_poll_hint(symbols, at)
    if market_states:
        interval = live
    else:
        scheduled = 15 if phase == Phase.OPEN else 60 if phase in (Phase.PREMARKET, Phase.AFTERMARKET) else 300
        interval = min(live, scheduled)
    if next_open_secs is not None:
        interval = min(interval, max(15, int(next_open_secs) + 1))
    return interval


async def get_quotes(symbols: str) -> list[Quote]:
    symbol_list = [symbol.strip().upper() for symbol in symbols.split(",") if symbol.strip()]
    if not symbol_list:
        return []
    return await get_price_provider().batch_fetch_quotes(symbol_list)


async def _tracked_asset_refs() -> list[AssetRef]:
    async with async_session() as db:
        return await AssetRepository(db).list_in_any_group_refs()


async def quote_event_generator(
    intraday_symbols: frozenset[str] | None = None,
    active_assets: frozenset[str] | None = None,
    active_group_ids: frozenset[int] | None = None,
):
    """Yield one current quote frame then live state deltas without provider polling."""
    store = get_live_quote_store()
    try:
        async with _registered_realtime_demand(active_assets, active_group_ids):
            async with store.subscribe() as updates:
                refs = await _tracked_asset_refs()
                tracked_refs = {ref.symbol: ref for ref in refs}
                snapshot = store.snapshot()
                payload = {
                    symbol: snapshot.get(symbol)
                    or Quote.placeholder(symbol, currency="TWD", data_status="DISCONNECTED")
                    for symbol in tracked_refs
                }
                yield _quote_event(payload)

                wanted_intraday = frozenset(intraday_symbols or ())
                bar_refs = [ref for symbol, ref in tracked_refs.items() if symbol in wanted_intraday]
                if bar_refs:
                    async with async_session() as db:
                        intraday_payload = await get_intraday_bars(db, bar_refs)
                    if intraday_payload:
                        yield _intraday_event(intraday_payload)

                while True:
                    quote = await updates.get()
                    if quote.symbol not in tracked_refs:
                        continue
                    yield _quote_event({quote.symbol: quote})
    except asyncio.CancelledError:
        return


@asynccontextmanager
async def _registered_realtime_demand(
    active_assets: frozenset[str] | None,
    active_group_ids: frozenset[int] | None,
) -> AsyncIterator[None]:
    controller = _realtime_demand_controller
    if controller is None:
        yield
        return
    async with controller.register(
        active_assets=active_assets or (),
        active_group_ids=active_group_ids or (),
    ):
        yield


def _quote_event(payload: dict[str, Quote]) -> str:
    data = _quotes_payload_adapter.dump_json(payload).decode()
    return f"event: quotes\ndata: {data}\n\n"


def _intraday_event(payload: dict[str, list[IntradayBar]]) -> str:
    data = _intraday_payload_adapter.dump_json(payload).decode()
    return f"event: intraday\ndata: {data}\n\n"
