"""Tests for the in-memory live quote freshness store."""

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.schemas.quote import Quote
from app.services.live_quote_store import LiveQuoteStore


@pytest.mark.asyncio
async def test_store_publishes_latest_quote_to_async_listeners():
    store = LiveQuoteStore()
    quote = Quote(symbol="2330", price=100, currency="TWD", data_status="LIVE")

    async with store.subscribe() as updates:
        await store.update(quote)
        received = await asyncio.wait_for(updates.get(), timeout=0.1)

    assert received == quote
    assert store.get("2330") == quote


@pytest.mark.asyncio
async def test_store_explicitly_transitions_cached_and_disconnected_states():
    store = LiveQuoteStore()
    quote = Quote(
        symbol="2330",
        price=100,
        currency="TWD",
        data_status="LIVE",
        updated_at=datetime(2026, 8, 19, 9, 0, tzinfo=ZoneInfo("Asia/Taipei")),
    )
    await store.update(quote)

    await store.mark_cached(("2330", "2317"))
    await store.mark_disconnected(("2330",))

    assert store.get("2330").data_status == "DISCONNECTED"
    assert store.get("2330").price == 100
    assert store.get("2317").data_status == "CACHED"
    assert store.get("2317").currency == "TWD"
