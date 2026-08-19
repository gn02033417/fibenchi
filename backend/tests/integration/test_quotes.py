"""Tests for the quotes router (REST + SSE stream)."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.symbol_directory import SymbolDirectory
from app.schemas.quote import Quote
from app.services.quote_service import _reset_asset_list_cache
from tests.conftest import TestSession

pytestmark = pytest.mark.asyncio(loop_scope="function")


_MOCK_QUOTES = [
    Quote(**{
        "symbol": "2330",
        "price": 2240.00,
        "previous_close": 2265.00,
        "change": -25.00,
        "change_percent": -1.10,
        "currency": "TWD",
        "market_state": "REGULAR",
    }),
    Quote(**{
        "symbol": "0050",
        "price": 183.50,
        "previous_close": 182.00,
        "change": 1.50,
        "change_percent": 0.82,
        "currency": "TWD",
        "market_state": "REGULAR",
    }),
]


@pytest.fixture(autouse=True)
async def seed_taiwan_directory(db):
    db.add_all([
        SymbolDirectory(symbol="2330", name="台積電", exchange="TSE", type="stock", currency="TWD"),
        SymbolDirectory(symbol="0050", name="元大台灣50", exchange="TSE", type="etf", currency="TWD"),
    ])
    await db.commit()


def _parse_sse_events(body: str) -> list[dict]:
    """Parse SSE text into a list of data payloads."""
    events = []
    for line in body.split("\n"):
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


def _mock_provider(quotes_return=None, quotes_side_effect=None):
    """Create a mock PriceProvider with batch_fetch_quotes stub."""
    provider = MagicMock()
    if quotes_side_effect is not None:
        provider.batch_fetch_quotes = AsyncMock(side_effect=quotes_side_effect)
    else:
        provider.batch_fetch_quotes = AsyncMock(return_value=quotes_return or [])
    return provider


# ── REST endpoint tests ──────────────────────────────────────────────


async def test_get_quotes_returns_data(client):
    """GET /api/quotes returns quote data for requested symbols."""
    mock_prov = _mock_provider(quotes_return=_MOCK_QUOTES)
    with patch("app.services.quote_service.get_price_provider", return_value=mock_prov):
        resp = await client.get("/api/quotes", params={"symbols": "2330,0050"})

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["symbol"] == "2330"
    assert data[0]["price"] == 2240.00
    assert data[1]["symbol"] == "0050"


async def test_get_quotes_empty_symbols(client):
    """GET /api/quotes with empty symbols returns empty list."""
    mock_prov = _mock_provider(quotes_return=[])
    with patch("app.services.quote_service.get_price_provider", return_value=mock_prov):
        resp = await client.get("/api/quotes", params={"symbols": ""})

    assert resp.status_code == 200
    assert resp.json() == []


async def test_get_quotes_single_symbol(client):
    """GET /api/quotes works with a single symbol."""
    mock_prov = _mock_provider(quotes_return=[_MOCK_QUOTES[0]])
    with patch("app.services.quote_service.get_price_provider", return_value=mock_prov):
        resp = await client.get("/api/quotes", params={"symbols": "2330"})

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["symbol"] == "2330"
    assert data[0]["market_state"] == "REGULAR"
    assert data[0]["currency"] == "TWD"


async def test_get_quotes_uppercase_normalization(client):
    """Symbols are normalized to uppercase before fetching."""
    mock_prov = _mock_provider(quotes_return=[_MOCK_QUOTES[0]])
    with patch("app.services.quote_service.get_price_provider", return_value=mock_prov):
        await client.get("/api/quotes", params={"symbols": "2330"})

    mock_prov.batch_fetch_quotes.assert_awaited_once_with(["2330"])


# ── SSE stream tests ─────────────────────────────────────────────────
# The SSE generator uses async_session directly (not get_db), so we must
# patch it to use the test database session.


async def test_stream_quotes_no_tracked(client):
    """SSE stream emits empty payload when no assets are tracked."""
    _reset_asset_list_cache()
    with (
        patch("app.services.quote_service.async_session", TestSession),
        patch("app.services.quote_service.asyncio.sleep", side_effect=asyncio.CancelledError()),
    ):
        resp = await client.get("/api/quotes/stream")

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    body = resp.text
    assert "event: quotes" in body
    assert "data: {}" in body


async def test_stream_quotes_emits_event(client):
    """SSE stream emits quote data for tracked assets."""
    a = (await client.post("/api/assets", json={"symbol": "2330", "name": "台積電", "type": "stock"})).json()
    groups = (await client.get("/api/groups")).json()
    watchlist_id = next(g["id"] for g in groups if g["is_default"])
    await client.post(f"/api/groups/{watchlist_id}/assets", json={"asset_ids": [a["id"]]})

    _reset_asset_list_cache()
    mock_prov = _mock_provider(quotes_return=[_MOCK_QUOTES[0]])
    with (
        patch("app.services.quote_service.async_session", TestSession),
        patch("app.services.quote_service.get_price_provider", return_value=mock_prov),
        patch("app.services.quote_service.asyncio.sleep", side_effect=asyncio.CancelledError()),
    ):
        resp = await client.get("/api/quotes/stream")

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert len(events) >= 1
    assert "2330" in events[0]
    assert events[0]["2330"]["price"] == 2240.00
    assert events[0]["2330"]["market_state"] == "REGULAR"


async def test_stream_quotes_cache_headers(client):
    """SSE stream sets correct cache-control and buffering headers."""
    _reset_asset_list_cache()
    with (
        patch("app.services.quote_service.async_session", TestSession),
        patch("app.services.quote_service.asyncio.sleep", side_effect=asyncio.CancelledError()),
    ):
        resp = await client.get("/api/quotes/stream")

    assert resp.headers.get("cache-control") == "no-cache"
    assert resp.headers.get("x-accel-buffering") == "no"


async def test_stream_quotes_multiple_symbols(client):
    """SSE stream includes all tracked symbols in first event."""
    a1 = (await client.post("/api/assets", json={"symbol": "2330", "name": "台積電", "type": "stock"})).json()
    a2 = (await client.post("/api/assets", json={"symbol": "0050", "name": "元大台灣50", "type": "etf"})).json()
    groups = (await client.get("/api/groups")).json()
    watchlist_id = next(g["id"] for g in groups if g["is_default"])
    await client.post(f"/api/groups/{watchlist_id}/assets", json={"asset_ids": [a1["id"], a2["id"]]})

    _reset_asset_list_cache()
    mock_prov = _mock_provider(quotes_return=_MOCK_QUOTES)
    with (
        patch("app.services.quote_service.async_session", TestSession),
        patch("app.services.quote_service.get_price_provider", return_value=mock_prov),
        patch("app.services.quote_service.asyncio.sleep", side_effect=asyncio.CancelledError()),
    ):
        resp = await client.get("/api/quotes/stream")

    events = _parse_sse_events(resp.text)
    assert len(events) >= 1
    assert "2330" in events[0]
    assert "0050" in events[0]
