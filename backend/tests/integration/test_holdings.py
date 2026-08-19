"""Tests for the holdings router (ETF holdings + holding indicators)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.compute.indicators import bb_position
from app.services.yahoo import yahoo_client
from tests.helpers import make_price_df, seed_taiwan_directory

pytestmark = pytest.mark.asyncio(loop_scope="function")


@pytest.fixture(autouse=True)
async def seed_directory(db):
    await seed_taiwan_directory(db, [
        {"symbol": "0051", "name": "元大台灣中型100", "type": "etf"},
        {"symbol": "2331", "name": "測試股票一"},
    ])


# ── Pure unit tests for bb_position ───────────────────────────────────

def test_bb_position_above():
    assert bb_position(close=110, upper=105, middle=100, lower=95) == "above"


def test_bb_position_upper():
    assert bb_position(close=103, upper=105, middle=100, lower=95) == "upper"


def test_bb_position_lower():
    assert bb_position(close=97, upper=105, middle=100, lower=95) == "lower"


def test_bb_position_below():
    assert bb_position(close=90, upper=105, middle=100, lower=95) == "below"


_MOCK_HOLDINGS = {
    "top_holdings": [
        {"symbol": "AAPL", "name": "Apple Inc.", "percent": 7.0},
        {"symbol": "MSFT", "name": "Microsoft Corp.", "percent": 6.5},
    ],
    "sector_weightings": [{"sector": "Technology", "percent": 30.0}],
    "total_percent": 13.5,
}


# ── Integration tests ────────────────────────────────────────────────

async def test_holdings_indicators_success(client):
    """Holdings indicators endpoint returns data for ETF with mocked Yahoo."""
    # Create an ETF asset
    await client.post("/api/assets", json={"symbol": "0051", "name": "元大台灣中型100", "type": "etf"})

    histories = {
        "AAPL": make_price_df(100, 180.0),
        "MSFT": make_price_df(100, 400.0),
    }

    mock_prov = MagicMock()
    mock_prov.batch_fetch_history = AsyncMock(return_value=histories)
    mock_prov.batch_fetch_currencies = AsyncMock(return_value={"AAPL": "USD", "MSFT": "USD"})

    with (
        patch.object(yahoo_client, "holdings", AsyncMock(return_value=_MOCK_HOLDINGS)),
        patch("app.services.compute.indicators.get_price_provider", return_value=mock_prov),
    ):
        resp = await client.get("/api/assets/0051/holdings/indicators")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["symbol"] == "AAPL"
    assert data[0]["close"] is not None
    assert data[1]["symbol"] == "MSFT"

    # Verify indicator values are nested under 'values'
    from app.services.compute.indicators import get_all_output_fields
    expected_fields = set(get_all_output_fields())
    for item in data:
        assert "values" in item
        values = item["values"]
        # All registry output fields should be present
        for field in expected_fields:
            assert field in values
        # With 100 data points, all indicators should have values
        assert isinstance(values["macd"], float)
        assert isinstance(values["macd_signal"], float)
        assert isinstance(values["bb_upper"], float)
        # Derived fields still present
        assert "macd_signal_dir" in values
        assert "bb_position" in values


async def test_holdings_indicators_not_etf(client):
    """Holdings indicators endpoint returns 400 for stock assets."""
    await client.post("/api/assets", json={"symbol": "2331", "name": "測試股票一", "type": "stock"})

    resp = await client.get("/api/assets/2331/holdings/indicators")
    assert resp.status_code == 400


async def test_holdings_indicators_no_data(client):
    """Holdings indicators endpoint returns 404 when no holdings found."""
    await client.post("/api/assets", json={"symbol": "0051", "name": "元大台灣中型100", "type": "etf"})

    with patch.object(yahoo_client, "holdings", AsyncMock(return_value=None)):
        resp = await client.get("/api/assets/0051/holdings/indicators")

    assert resp.status_code == 404
