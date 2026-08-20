"""Offline contract tests for the Shioaji Kbars HTTP boundary."""

import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.services.shioaji.client import ShioajiClient, ShioajiPayloadError
from app.services.shioaji.kbars import MinuteBar

TAIPEI = ZoneInfo("Asia/Taipei")


def _client(handler) -> ShioajiClient:
    return ShioajiClient(
        "http://shioaji-stub:8080",
        timeout=1.0,
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.asyncio
async def test_kbars_posts_official_contract_and_normalizes_minute_ohlcv():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/data/kbars"
        assert json.loads(request.content) == {
            "contract": {
                "security_type": "STK",
                "exchange": "TSE",
                "code": "2330",
            },
            "start": "2026-05-18",
            "end": "2026-05-18",
        }
        return httpx.Response(
            200,
            json={
                "datetime": ["2026-05-18T09:01:00", "2026-05-18T01:02:00Z"],
                "Open": [2225.0, 2230.0],
                "High": [2235.0, 2240.0],
                "Low": [2220.0, 2225.0],
                "Close": [2230.0, 2235.0],
                "Volume": [2565, 377],
                "Amount": [5708965000.0, 840260000.0],
            },
        )

    bars = await _client(handler).kbars(
        {"security_type": "STK", "exchange": "TSE", "code": "2330"},
        start=date(2026, 5, 18),
        end=date(2026, 5, 18),
    )

    assert bars == [
        MinuteBar(
            timestamp=datetime(2026, 5, 18, 9, 1, tzinfo=TAIPEI),
            open=2225.0,
            high=2235.0,
            low=2220.0,
            close=2230.0,
            volume=2565,
            amount=5708965000.0,
        ),
        MinuteBar(
            timestamp=datetime(2026, 5, 18, 9, 2, tzinfo=TAIPEI),
            open=2230.0,
            high=2240.0,
            low=2225.0,
            close=2235.0,
            volume=377,
            amount=840260000.0,
        ),
    ]


@pytest.mark.asyncio
async def test_kbars_rejects_mismatched_column_lengths():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "datetime": ["2026-05-18T09:01:00"],
                "Open": [2225.0],
                "High": [2235.0],
                "Low": [2220.0],
                "Close": [2230.0],
                "Volume": [2565],
                "Amount": [5708965000.0, 1.0],
            },
        )

    with pytest.raises(ShioajiPayloadError):
        await _client(handler).kbars(
            {"security_type": "STK", "exchange": "TSE", "code": "2330"},
            start=date(2026, 5, 18),
            end=date(2026, 5, 18),
        )
