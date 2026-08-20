"""Integration tests for the quotes REST and event-driven SSE endpoints."""

import asyncio
import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.symbol_directory import SymbolDirectory
from app.schemas.quote import Quote
from app.services.live_quote_store import LiveQuoteStore
from app.services.quote_service import configure_live_quote_store
from tests.conftest import TestSession

pytestmark = pytest.mark.asyncio(loop_scope="function")


_MOCK_QUOTES = [
    Quote(
        symbol="2330",
        price=2240.00,
        previous_close=2265.00,
        change=-25.00,
        change_percent=-1.10,
        currency="TWD",
        market_state="REGULAR",
        data_status="LIVE",
    ),
    Quote(
        symbol="0050",
        price=183.50,
        previous_close=182.00,
        change=1.50,
        change_percent=0.82,
        currency="TWD",
        market_state="REGULAR",
        data_status="LIVE",
    ),
]


@pytest.fixture(autouse=True)
async def seed_taiwan_directory(db):
    db.add_all(
        [
            SymbolDirectory(symbol="2330", name="台積電", exchange="TSE", type="stock", currency="TWD"),
            SymbolDirectory(symbol="0050", name="元大台灣50", exchange="TSE", type="etf", currency="TWD"),
        ]
    )
    await db.commit()


class _CancelledQueue:
    async def get(self):
        raise asyncio.CancelledError()


class _FiniteLiveQuoteStore:
    """Provides one snapshot then closes the response deterministically."""

    def __init__(self, quotes: list[Quote]):
        self._snapshot = {quote.symbol: quote for quote in quotes}

    def snapshot(self) -> dict[str, Quote]:
        return dict(self._snapshot)

    @asynccontextmanager
    async def subscribe(self):
        yield _CancelledQueue()


@pytest.fixture
def finite_store(monkeypatch):
    store = _FiniteLiveQuoteStore(_MOCK_QUOTES)
    monkeypatch.setattr("app.services.quote_service.async_session", TestSession)
    configure_live_quote_store(store)
    yield store
    configure_live_quote_store(LiveQuoteStore())


def _parse_sse_events(body: str) -> list[dict]:
    return [json.loads(line[6:]) for line in body.split("\n") if line.startswith("data: ")]


def _mock_provider(quotes_return=None):
    provider = MagicMock()
    provider.batch_fetch_quotes = AsyncMock(return_value=quotes_return or [])
    return provider


async def test_get_quotes_returns_data(client):
    mock_prov = _mock_provider(_MOCK_QUOTES)
    with patch("app.services.quote_service.get_price_provider", return_value=mock_prov):
        resp = await client.get("/api/quotes", params={"symbols": "2330,0050"})

    assert resp.status_code == 200
    assert [quote["symbol"] for quote in resp.json()] == ["2330", "0050"]


async def test_get_quotes_empty_symbols(client):
    mock_prov = _mock_provider()
    with patch("app.services.quote_service.get_price_provider", return_value=mock_prov):
        resp = await client.get("/api/quotes", params={"symbols": ""})

    assert resp.status_code == 200
    assert resp.json() == []


async def test_get_quotes_single_symbol(client):
    mock_prov = _mock_provider([_MOCK_QUOTES[0]])
    with patch("app.services.quote_service.get_price_provider", return_value=mock_prov):
        resp = await client.get("/api/quotes", params={"symbols": "2330"})

    assert resp.status_code == 200
    assert resp.json()[0]["currency"] == "TWD"


async def test_stream_quotes_no_tracked_returns_an_empty_initial_frame(client, finite_store):
    resp = await client.get("/api/quotes/stream")

    assert resp.status_code == 200
    assert _parse_sse_events(resp.text) == [{}]


async def test_stream_quotes_uses_live_store_without_provider_polling(client, finite_store):
    asset = (await client.post("/api/assets", json={"symbol": "2330", "name": "台積電", "type": "stock"})).json()
    groups = (await client.get("/api/groups")).json()
    watchlist_id = next(group["id"] for group in groups if group["is_default"])
    await client.post(f"/api/groups/{watchlist_id}/assets", json={"asset_ids": [asset["id"]]})
    provider = _mock_provider(_MOCK_QUOTES)

    with patch("app.services.quote_service.get_price_provider", return_value=provider):
        resp = await client.get("/api/quotes/stream")

    assert resp.status_code == 200
    payload = _parse_sse_events(resp.text)[0]
    assert payload["2330"]["price"] == 2240.00
    provider.batch_fetch_quotes.assert_not_awaited()


async def test_stream_quotes_cache_headers_remain_compatible(client, finite_store):
    resp = await client.get("/api/quotes/stream")

    assert resp.headers.get("cache-control") == "no-cache"
    assert resp.headers.get("x-accel-buffering") == "no"


async def test_stream_quotes_multiple_symbols_uses_first_snapshot(client, finite_store):
    assets = [
        (await client.post("/api/assets", json={"symbol": symbol, "name": name, "type": kind})).json()
        for symbol, name, kind in (("2330", "台積電", "stock"), ("0050", "元大台灣50", "etf"))
    ]
    groups = (await client.get("/api/groups")).json()
    watchlist_id = next(group["id"] for group in groups if group["is_default"])
    await client.post(f"/api/groups/{watchlist_id}/assets", json={"asset_ids": [asset["id"] for asset in assets]})

    payload = _parse_sse_events((await client.get("/api/quotes/stream")).text)[0]

    assert set(payload) == {"2330", "0050"}
