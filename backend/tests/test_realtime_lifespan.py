"""Lifecycle coverage for the shared Shioaji live quote manager."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app import main
from app.domain import AssetRef
from app.services import quote_service
from app.services.realtime_demand import RealtimeDemandController


class FakeSubscriptionManager:
    instance: "FakeSubscriptionManager | None" = None

    def __init__(self, stream, store, **kwargs):
        self.stream = stream
        self.store = store
        self.handlers = kwargs
        self.started = asyncio.Event()
        self.cancelled = False
        self.wanted_provider = None
        type(self).instance = self

    async def run_forever(self, wanted_provider):
        self.wanted_provider = wanted_provider
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


@pytest.mark.asyncio
async def test_lifespan_owns_one_shared_live_quote_store_and_manager_task():
    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=MagicMock())
    session_context.__aexit__ = AsyncMock(return_value=False)
    scheduler = MagicMock()
    engine = MagicMock(dispose=AsyncMock())
    stream = MagicMock()

    with (
        patch.object(main, "init_price_provider"),
        patch.object(main, "async_session", return_value=session_context),
        patch.object(main, "load_currency_cache", new=AsyncMock()),
        patch.object(main, "all_tasks", return_value=[]),
        patch.object(main, "scheduler", scheduler),
        patch.object(main, "startup_warmup", new=AsyncMock()),
        patch.object(main, "ShioajiQuoteStream", return_value=stream),
        patch.object(main, "SubscriptionManager", FakeSubscriptionManager),
        patch.object(main, "engine", engine),
    ):
        async with main.lifespan(main.app):
            manager = FakeSubscriptionManager.instance
            await asyncio.wait_for(manager.started.wait(), timeout=0.1)

            assert main.app.state.subscription_manager is manager
            assert main.app.state.live_quote_store is manager.store
            assert main.app.state.realtime_demand_controller is not None
            assert main.app.state.intraday_aggregator is not None
            assert manager.stream is stream
            assert manager.wanted_provider is main._tracked_quote_subscriptions
            assert callable(manager.handlers["on_quote_update"])
            assert callable(manager.handlers["on_disconnect"])

    assert manager.cancelled is True
    engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_tracked_quote_subscriptions_keep_verified_taiwan_identity():
    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=MagicMock())
    session_context.__aexit__ = AsyncMock(return_value=False)
    refs = [
        AssetRef("2330", 1, exchange="TSE"),
        AssetRef("0050", 2, exchange="OTC"),
        AssetRef("AAPL", 3, exchange=None),
    ]

    with (
        patch.object(main, "async_session", return_value=session_context),
        patch.object(main, "AssetRepository") as repository,
        patch.object(main, "GroupRepository") as group_repository,
    ):
        repository.return_value.list_in_any_group_refs = AsyncMock(return_value=refs)
        group_repository.return_value.list_realtime_priority_groups = AsyncMock(return_value=[])
        subscriptions = await main._tracked_quote_subscriptions()

    assert [(subscription.code, subscription.exchange) for subscription in subscriptions] == [
        ("0050", "OTC"),
        ("2330", "TSE"),
    ]


@pytest.mark.asyncio
async def test_tracked_quote_subscriptions_raise_active_asset_and_group_demand():
    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=MagicMock())
    session_context.__aexit__ = AsyncMock(return_value=False)
    active_group = SimpleNamespace(assets=[SimpleNamespace(symbol="0050")])
    priority_group = SimpleNamespace(assets=[SimpleNamespace(symbol="2330")])
    controller = RealtimeDemandController(AsyncMock())
    quote_service.configure_realtime_demand_controller(controller)

    try:
        async with controller.register(active_assets=("2317",), active_group_ids=(8,)):
            with (
                patch.object(main, "async_session", return_value=session_context),
                patch.object(main, "AssetRepository") as asset_repository,
                patch.object(main, "GroupRepository") as group_repository,
            ):
                asset_repository.return_value.list_in_any_group_refs = AsyncMock(return_value=[
                    AssetRef("0050", 1, exchange="TSE"),
                    AssetRef("2317", 2, exchange="TSE"),
                    AssetRef("2330", 3, exchange="TSE"),
                ])
                group_repository.return_value.list_realtime_priority_groups = AsyncMock(return_value=[priority_group])
                group_repository.return_value.get_by_id = AsyncMock(return_value=active_group)
                subscriptions = await main._tracked_quote_subscriptions()
    finally:
        quote_service.configure_realtime_demand_controller(None)

    assert [subscription.code for subscription in subscriptions] == ["2317", "2330", "0050"]
