"""Tests for deterministic Shioaji subscription reconciliation."""

import asyncio
from contextlib import suppress
from datetime import datetime

import pytest

from app.schemas.quote import Quote
from app.services.live_quote_store import LiveQuoteStore
from app.services.shioaji.stream import ShioajiQuoteSubscription
from app.services.subscription_manager import SubscriptionManager


class FakeQuoteStream:
    def __init__(self):
        self.subscribed: list[ShioajiQuoteSubscription] = []
        self.unsubscribed: list[ShioajiQuoteSubscription] = []

    async def subscribe(self, subscription: ShioajiQuoteSubscription) -> None:
        self.subscribed.append(subscription)

    async def unsubscribe(self, subscription: ShioajiQuoteSubscription) -> None:
        self.unsubscribed.append(subscription)

    async def quote_events(self):
        if False:
            yield None


class ReconnectingFakeQuoteStream(FakeQuoteStream):
    def __init__(self):
        super().__init__()
        self.connections = 0
        self.wait_on_second_connection = asyncio.Event()

    async def quote_events(self):
        self.connections += 1
        if self.connections == 1:
            yield Quote(symbol="2330", price=100, currency="TWD", data_status="LIVE")
            return
        await self.wait_on_second_connection.wait()
        if False:
            yield None


def _subscription(code: str, exchange: str = "TSE") -> ShioajiQuoteSubscription:
    return ShioajiQuoteSubscription(code=code, exchange=exchange)


@pytest.mark.asyncio
async def test_reconcile_applies_exact_diffs_and_is_idempotent():
    stream = FakeQuoteStream()
    store = LiveQuoteStore()
    manager = SubscriptionManager(stream, store, max_subscriptions=3)

    first = await manager.reconcile((_subscription("2330"), _subscription("2317"), _subscription("1101")))
    repeated = await manager.reconcile((_subscription("2330"), _subscription("2317"), _subscription("1101")))
    changed = await manager.reconcile((_subscription("2317"), _subscription("2603")))

    assert first.subscribed == ("2330", "2317", "1101")
    assert first.unsubscribed == ()
    assert repeated.subscribed == repeated.unsubscribed == ()
    assert changed.unsubscribed == ("2330", "1101")
    assert changed.subscribed == ("2603",)
    assert [subscription.code for subscription in stream.subscribed] == ["2330", "2317", "1101", "2603"]
    assert [subscription.code for subscription in stream.unsubscribed] == ["2330", "1101"]
    assert manager.current_symbols == ("2317", "2603")
    assert store.get("2330").data_status == "CACHED"


@pytest.mark.asyncio
async def test_reconcile_enforces_cap_and_deduplicates_by_symbol():
    stream = FakeQuoteStream()
    manager = SubscriptionManager(stream, LiveQuoteStore(), max_subscriptions=180)
    wanted = [_subscription("0050")] + [_subscription(f"{number:04}") for number in range(1, 250)]
    wanted.insert(2, _subscription("0050", "OTC"))

    diff = await manager.reconcile(wanted)

    assert len(diff.subscribed) == 180
    assert len(manager.current_symbols) == 180
    assert manager.current_symbols[0] == "0050"
    assert manager.current_symbols.count("0050") == 1


@pytest.mark.asyncio
async def test_disconnect_marks_known_quotes_and_reconnect_recomputes_wanted_set():
    stream = FakeQuoteStream()
    store = LiveQuoteStore()
    manager = SubscriptionManager(stream, store, max_subscriptions=2)
    await manager.reconcile((_subscription("2330"),))
    await store.update(
        Quote(
            symbol="2330",
            price=100,
            currency="TWD",
            data_status="LIVE",
            updated_at=datetime(2026, 8, 19, 9, 0),
        )
    )

    await manager.mark_disconnected()
    calls = 0

    async def wanted_provider():
        nonlocal calls
        calls += 1
        return (_subscription("2317"),)

    restored = await manager.restore_after_reconnect(wanted_provider)

    assert store.get("2330").data_status == "DISCONNECTED"
    assert calls == 1
    assert restored.subscribed == ("2317",)
    assert manager.current_symbols == ("2317",)


@pytest.mark.asyncio
async def test_run_forever_reconnects_with_a_fresh_wanted_set():
    stream = ReconnectingFakeQuoteStream()
    store = LiveQuoteStore()
    manager = SubscriptionManager(
        stream,
        store,
        max_subscriptions=2,
        reconnect_initial_delay=0.001,
        reconnect_max_delay=0.002,
    )
    calls = 0

    async def wanted_provider():
        nonlocal calls
        calls += 1
        return (_subscription("2330" if calls == 1 else "2317"),)

    task = asyncio.create_task(manager.run_forever(wanted_provider))
    for _ in range(100):
        if stream.connections >= 2:
            break
        await asyncio.sleep(0.001)

    try:
        assert stream.connections == 2
        assert calls == 2
        assert [subscription.code for subscription in stream.subscribed] == ["2330", "2317"]
        assert store.get("2330").data_status == "DISCONNECTED"
        assert manager.current_symbols == ("2317",)
    finally:
        stream.wait_on_second_connection.set()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
