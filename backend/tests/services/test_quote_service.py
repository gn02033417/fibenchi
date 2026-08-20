"""Unit tests for quote_service REST parsing and event-driven SSE output."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain import AssetRef
from app.schemas.quote import Quote
from app.services.live_quote_store import LiveQuoteStore
from app.services.quote_service import (
    configure_live_quote_store,
    configure_realtime_demand_controller,
    get_quotes,
    quote_event_generator,
)
from app.services.realtime_demand import RealtimeDemandController

pytestmark = pytest.mark.asyncio(loop_scope="function")


@pytest.fixture
def live_store():
    store = LiveQuoteStore()
    configure_live_quote_store(store)
    yield store
    configure_live_quote_store(LiveQuoteStore())


def _mock_provider(quotes_return=None):
    provider = MagicMock()
    provider.batch_fetch_quotes = AsyncMock(return_value=quotes_return or [])
    return provider


async def test_get_quotes_parses_symbols():
    mock_quotes = [Quote(symbol="AAPL", price=185.50)]
    mock_prov = _mock_provider(quotes_return=mock_quotes)
    with patch("app.services.quote_service.get_price_provider", return_value=mock_prov):
        result = await get_quotes("AAPL,MSFT")
    assert result == mock_quotes


async def test_get_quotes_uppercase_normalization():
    mock_prov = _mock_provider()
    with patch("app.services.quote_service.get_price_provider", return_value=mock_prov):
        await get_quotes("aapl, msft")
    mock_prov.batch_fetch_quotes.assert_awaited_once_with(["AAPL", "MSFT"])


async def test_get_quotes_empty_returns_empty():
    assert await get_quotes("") == []


async def test_stream_emits_current_tracked_snapshot_without_provider_polling(live_store):
    quote = Quote(symbol="2330", price=102, currency="TWD", data_status="LIVE")
    await live_store.update(quote)
    provider = _mock_provider([quote])

    with (
        patch(
            "app.services.quote_service._tracked_asset_refs",
            new=AsyncMock(return_value=[AssetRef("2330", 1, exchange="TSE")]),
        ),
        patch("app.services.quote_service.get_price_provider", return_value=provider),
    ):
        stream = quote_event_generator()
        event = await anext(stream)
        await stream.aclose()

    payload = json.loads(event.split("data: ", 1)[1])
    assert payload["2330"]["price"] == 102
    assert payload["2330"]["data_status"] == "LIVE"
    provider.batch_fetch_quotes.assert_not_awaited()


async def test_stream_emits_only_changed_tracked_quotes_after_the_first_frame(live_store):
    original = Quote(symbol="2330", price=100, currency="TWD", data_status="LIVE")
    await live_store.update(original)

    with patch(
        "app.services.quote_service._tracked_asset_refs",
        new=AsyncMock(return_value=[AssetRef("2330", 1, exchange="TSE")]),
    ):
        stream = quote_event_generator()
        _ = await anext(stream)
        await live_store.update(original)
        await live_store.update(Quote(symbol="0050", price=200, currency="TWD", data_status="LIVE"))
        await live_store.update(Quote(symbol="2330", price=101, currency="TWD", data_status="LIVE"))
        event = await asyncio.wait_for(anext(stream), timeout=0.1)
        await stream.aclose()

    payload = json.loads(event.split("data: ", 1)[1])
    assert payload == {"2330": payload["2330"]}
    assert payload["2330"]["price"] == 101


async def test_stream_initial_frame_contains_disconnected_placeholders_for_tracked_symbols(live_store):
    with patch(
        "app.services.quote_service._tracked_asset_refs",
        new=AsyncMock(return_value=[AssetRef("0050", 1, exchange="TSE")]),
    ):
        stream = quote_event_generator()
        event = await anext(stream)
        await stream.aclose()

    payload = json.loads(event.split("data: ", 1)[1])
    assert payload["0050"]["price"] is None
    assert payload["0050"]["data_status"] == "DISCONNECTED"


async def test_stream_cancellation_unregisters_store_listener(live_store):
    with patch(
        "app.services.quote_service._tracked_asset_refs",
        new=AsyncMock(return_value=[]),
    ):
        stream = quote_event_generator()
        _ = await anext(stream)
        assert live_store.listener_count == 1
        await stream.aclose()

    assert live_store.listener_count == 0


async def test_stream_registers_and_removes_active_view_demand(live_store):
    refresh = AsyncMock()
    controller = RealtimeDemandController(refresh)
    configure_realtime_demand_controller(controller)

    try:
        with patch(
            "app.services.quote_service._tracked_asset_refs",
            new=AsyncMock(return_value=[]),
        ):
            stream = quote_event_generator(
                active_assets=frozenset(("2330",)),
                active_group_ids=frozenset((7,)),
            )
            _ = await anext(stream)
            snapshot = await controller.snapshot()
            await stream.aclose()

        assert snapshot.active_assets == ("2330",)
        assert snapshot.active_group_ids == (7,)
        assert await controller.snapshot() == type(snapshot)()
        assert refresh.await_count == 2
    finally:
        configure_realtime_demand_controller(None)
