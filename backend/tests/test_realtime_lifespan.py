"""Lifecycle coverage for the shared Shioaji live quote manager."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app import main
from app.domain import AssetRef


class FakeSubscriptionManager:
    instance: "FakeSubscriptionManager | None" = None

    def __init__(self, stream, store):
        self.stream = stream
        self.store = store
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
            assert manager.stream is stream
            assert manager.wanted_provider is main._tracked_quote_subscriptions

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
    ):
        repository.return_value.list_in_any_group_refs = AsyncMock(return_value=refs)
        subscriptions = await main._tracked_quote_subscriptions()

    assert [(subscription.code, subscription.exchange) for subscription in subscriptions] == [
        ("0050", "OTC"),
        ("2330", "TSE"),
    ]
