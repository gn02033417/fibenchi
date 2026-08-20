"""Offline contract tests for the Shioaji Quote SSE boundary."""

import json

import httpx
import pytest

from app.services.shioaji.client import ShioajiHTTPError
from app.services.shioaji.stream import (
    ShioajiQuoteStream,
    ShioajiQuoteSubscription,
)


def _stream(handler) -> ShioajiQuoteStream:
    return ShioajiQuoteStream(
        "http://shioaji-stub:8080",
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.asyncio
async def test_quote_stream_subscribes_and_unsubscribes_with_official_payload():
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True})

    stream = _stream(handler)
    subscription = ShioajiQuoteSubscription(code="2330", exchange="TSE")

    await stream.subscribe(subscription)
    await stream.unsubscribe(subscription)

    assert [(request.method, request.url.path) for request in requests] == [
        ("POST", "/api/v1/stream/subscribe"),
        ("POST", "/api/v1/stream/unsubscribe"),
    ]
    assert [json.loads(request.content) for request in requests] == [
        {
            "security_type": "STK",
            "exchange": "TSE",
            "code": "2330",
            "quote_type": "Quote",
        },
        {
            "security_type": "STK",
            "exchange": "TSE",
            "code": "2330",
            "quote_type": "Quote",
        },
    ]


@pytest.mark.asyncio
async def test_quote_stream_parses_fake_sse_and_normalizes_a_live_quote():
    payload = {
        "code": "2330",
        "exchange": "TSE",
        "date": "2026-08-19",
        "time": "09:01:02.123456",
        "open": "100",
        "high": "103",
        "low": "99",
        "close": "102",
        "price_chg": "2",
        "total_volume": 321,
        "bid_price": ["101.5"],
        "bid_volume": [10],
        "ask_price": ["102.5"],
        "ask_volume": [12],
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/stream/data/quote_stk"
        body = ": heartbeat\n\nevent: quote_stk\ndata: " + json.dumps(payload) + "\n\n"
        return httpx.Response(200, content=body.encode())

    quotes = [quote async for quote in _stream(handler).quote_events()]

    assert len(quotes) == 1
    assert quotes[0].model_dump() == {
        "symbol": "2330",
        "price": 102.0,
        "previous_close": 100.0,
        "change": 2.0,
        "change_percent": 2.0,
        "volume": 321,
        "avg_volume": None,
        "currency": "TWD",
        "market_state": "REGULAR",
        "open": 100.0,
        "high": 103.0,
        "low": 99.0,
        "bid": 101.5,
        "bid_volume": 10,
        "ask": 102.5,
        "ask_volume": 12,
        "data_status": "LIVE",
        "updated_at": quotes[0].updated_at,
        "session_date": "2026-08-19",
    }
    assert quotes[0].updated_at.isoformat() == "2026-08-19T09:01:02.123456+08:00"


@pytest.mark.asyncio
async def test_quote_stream_wraps_non_success_sse_response():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "sidecar unavailable"})

    with pytest.raises(ShioajiHTTPError) as exc_info:
        async for _ in _stream(handler).quote_events():
            pass

    assert exc_info.value.path == "/api/v1/stream/data/quote_stk"
