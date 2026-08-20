"""Tests for the intentionally disabled ETF holdings routes."""

import pytest

from app.services.compute.indicators import bb_position
from tests.helpers import seed_taiwan_directory


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


async def test_holdings_routes_are_disabled(client):
    """Taiwan runtime does not expose Yahoo-backed ETF holdings routes."""
    await client.post("/api/assets", json={"symbol": "0051", "name": "元大台灣中型100", "type": "etf"})

    assert (await client.get("/api/assets/0051/holdings")).status_code == 404
    assert (await client.get("/api/assets/0051/holdings/indicators")).status_code == 404
