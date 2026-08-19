"""Integration tests for the local Taiwan symbol-directory search router."""

from unittest.mock import AsyncMock, patch

import pytest

from app.models.symbol_directory import SymbolDirectory

pytestmark = pytest.mark.asyncio(loop_scope="function")


async def _seed_symbols(db):
    db.add_all([
        SymbolDirectory(symbol="2330", name="台積電", exchange="TSE", type="stock", currency="TWD"),
        SymbolDirectory(symbol="2330A", name="台積特別股", exchange="TSE", type="stock", currency="TWD"),
        SymbolDirectory(symbol="0050", name="元大台灣50", exchange="TSE", type="etf", currency="TWD"),
        SymbolDirectory(symbol="6488", name="環球晶", exchange="OTC", type="stock", currency="TWD"),
        SymbolDirectory(symbol="9000", name="停牌台積電", exchange="TSE", type="stock", currency="TWD", active=False),
        SymbolDirectory(symbol="AAPL", name="Apple Inc.", exchange="NASDAQ", type="stock", currency="USD"),
    ])
    await db.commit()


class TestSearchSymbols:
    async def test_search_requires_query(self, client):
        resp = await client.get("/api/search")
        assert resp.status_code == 422

    async def test_empty_query_rejected(self, client):
        resp = await client.get("/api/search", params={"q": ""})
        assert resp.status_code == 422

    async def test_search_returns_taiwan_symbol_by_code_and_name(self, client, db):
        await _seed_symbols(db)

        exact = await client.get("/api/search", params={"q": "2330"})
        chinese = await client.get("/api/search", params={"q": "台積"})

        assert exact.status_code == 200
        assert exact.json()[0]["symbol"] == "2330"
        assert chinese.status_code == 200
        assert chinese.json()[0]["symbol"] == "2330"

    async def test_search_accepts_legacy_local_and_all_sources_without_external_fallback(
        self, client, db
    ):
        await _seed_symbols(db)

        local = await client.get("/api/search", params={"q": "0050", "source": "local"})
        all_source = await client.get("/api/search", params={"q": "6488", "source": "all"})

        assert local.status_code == 200
        assert local.json()[0]["symbol"] == "0050"
        assert all_source.status_code == 200
        assert all_source.json()[0]["symbol"] == "6488"

    async def test_yahoo_source_is_rejected(self, client, db):
        await _seed_symbols(db)

        resp = await client.get("/api/search", params={"q": "2330", "source": "yahoo"})

        assert resp.status_code == 422

    @patch("app.services.yahoo.yahoo_client.search", new_callable=AsyncMock)
    @patch("app.services.shioaji.client.ShioajiClient.list_contracts", new_callable=AsyncMock)
    async def test_search_never_calls_yahoo_or_shioaji(
        self, list_contracts, yahoo_search, client, db
    ):
        await _seed_symbols(db)

        resp = await client.get("/api/search", params={"q": "台積"})

        assert resp.status_code == 200
        assert resp.json()[0]["symbol"] == "2330"
        yahoo_search.assert_not_awaited()
        list_contracts.assert_not_awaited()

    async def test_search_excludes_inactive_and_non_taiwan_rows(self, client, db):
        await _seed_symbols(db)

        inactive = await client.get("/api/search", params={"q": "停牌"})
        overseas = await client.get("/api/search", params={"q": "Apple"})

        assert inactive.status_code == 200
        assert inactive.json() == []
        assert overseas.status_code == 200
        assert overseas.json() == []
