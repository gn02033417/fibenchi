"""Unit tests for local Taiwan symbol-directory search."""

from unittest.mock import AsyncMock, patch

import pytest

from app.models.symbol_directory import SymbolDirectory
from app.services.search_service import search_symbols

pytestmark = pytest.mark.asyncio(loop_scope="function")


async def _seed_symbols(db):
    db.add_all([
        SymbolDirectory(symbol="2330", name="台積電", exchange="TSE", type="stock", currency="TWD"),
        SymbolDirectory(symbol="2330A", name="台積特別股", exchange="TSE", type="stock", currency="TWD"),
        SymbolDirectory(symbol="12330", name="台積相關商品", exchange="OTC", type="stock", currency="TWD"),
        SymbolDirectory(symbol="0050", name="元大台灣50", exchange="TSE", type="etf", currency="TWD"),
        SymbolDirectory(symbol="9000", name="停牌台積電", exchange="TSE", type="stock", currency="TWD", active=False),
        SymbolDirectory(symbol="US01", name="Overseas", exchange="NASDAQ", type="stock", currency="USD"),
        SymbolDirectory(symbol="7777", name="未知商品", exchange="TSE", type="unknown", currency="TWD"),
    ])
    await db.commit()


async def test_search_supports_exact_prefix_and_substring_code_matching(db):
    await _seed_symbols(db)

    result = await search_symbols("2330", db)

    assert [row["symbol"] for row in result] == ["2330", "2330A", "12330"]
    assert all(row["exchange"] in {"TSE", "OTC"} for row in result)


async def test_search_supports_chinese_name_matching(db):
    await _seed_symbols(db)

    result = await search_symbols("台積", db)

    assert [row["symbol"] for row in result] == ["12330", "2330", "2330A"]


async def test_search_excludes_inactive_unsupported_and_non_taiwan_rows(db):
    await _seed_symbols(db)

    result = await search_symbols("台", db)

    symbols = [row["symbol"] for row in result]
    assert symbols == ["12330", "2330", "2330A", "0050"]
    assert "9000" not in symbols
    assert "US01" not in symbols
    assert "7777" not in symbols


async def test_search_does_not_call_yahoo_or_shioaji(db):
    await _seed_symbols(db)

    with (
        patch("app.services.yahoo.yahoo_client.search", new_callable=AsyncMock) as yahoo_search,
        patch("app.services.shioaji.client.ShioajiClient.list_contracts", new_callable=AsyncMock) as list_contracts,
    ):
        result = await search_symbols("2330", db)

    assert result[0]["symbol"] == "2330"
    yahoo_search.assert_not_awaited()
    list_contracts.assert_not_awaited()


async def test_search_returns_empty_for_blank_query(db):
    assert await search_symbols("   ", db) == []
