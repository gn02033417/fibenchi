"""Stub-backed end-to-end gates for the Taiwan runtime path."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.schemas.quote import Quote
from app.services import price_sync, quote_service
from app.services.historical_queue import HistoricalDataQueue
from app.services.live_quote_store import LiveQuoteStore
from app.services.realtime_priority import compute_wanted_symbols
from app.services.shioaji.client import ShioajiClient
from app.services.shioaji.contracts import ShioajiContractsAdapter
from app.services.shioaji.stream import ShioajiQuoteStream, ShioajiQuoteSubscription
from app.services.subscription_manager import SubscriptionManager
from app.services.symbol_providers.base import SymbolEntry
from app.services.taiwan_symbol_directory import sync_taiwan_symbol_directory
from tests.conftest import TestSession

pytestmark = pytest.mark.asyncio(loop_scope="function")

TAIPEI = ZoneInfo("Asia/Taipei")


class _ReferenceProvider:
    def __init__(self, entries: list[SymbolEntry]):
        self.entries = entries

    async def fetch_symbols(self, config):
        return self.entries


class _ShioajiStub:
    """One offline HTTP stub shared by contracts, Kbars, and Quote SSE."""

    def __init__(self):
        self.contract_requests: list[dict[str, str]] = []
        self.kbars_requests: list[tuple[date, date]] = []
        self.subscribe_requests: list[dict[str, str]] = []
        self.unsubscribe_requests: list[dict[str, str]] = []
        self.stream_requests = 0

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path

        if request.method == "GET" and path == "/api/v1/data/contracts":
            self.contract_requests.append(dict(request.url.params))
            return httpx.Response(
                200,
                request=request,
                json=[
                    {"security_type": "STK", "region": "TW", "exchange": "TSE", "code": "2330"},
                    {"security_type": "STK", "region": "TW", "exchange": "TSE", "code": "0050"},
                    {"security_type": "STK", "region": "TW", "exchange": "OTC", "code": "6488"},
                    {"security_type": "FUT", "region": "TW", "exchange": "TSE", "code": "TXF"},
                ],
            )

        if request.method == "POST" and path == "/api/v1/data/kbars":
            payload = json.loads(request.content)
            start = date.fromisoformat(payload["start"])
            end = date.fromisoformat(payload["end"])
            self.kbars_requests.append((start, end))
            return httpx.Response(200, request=request, json=self._kbars_payload(start, end))

        if request.method == "POST" and path == "/api/v1/stream/subscribe":
            self.subscribe_requests.append(json.loads(request.content))
            return httpx.Response(204, request=request)

        if request.method == "POST" and path == "/api/v1/stream/unsubscribe":
            self.unsubscribe_requests.append(json.loads(request.content))
            return httpx.Response(204, request=request)

        if request.method == "GET" and path == "/api/v1/stream/data/quote_stk":
            self.stream_requests += 1
            body = (
                "event: quote_stk\n"
                'data: {"code":"2330","exchange":"TSE",'
                '"datetime":"2026-08-20T10:00:00+08:00",'
                '"open":1190.0,"high":1210.0,"low":1185.0,"close":1200.0,'
                '"previous_close":1195.0,"volume":25,"total_volume":1025,'
                '"bid_price":[1199.0],"bid_volume":[10],'
                '"ask_price":[1201.0],"ask_volume":[12],"market_state":"REGULAR"}\n\n'
            )
            return httpx.Response(
                200,
                request=request,
                headers={"content-type": "text/event-stream"},
                content=body.encode(),
            )

        return httpx.Response(404, request=request)

    @staticmethod
    def _kbars_payload(start: date, end: date) -> dict[str, list[object]]:
        timestamps: list[str] = []
        opens: list[float] = []
        highs: list[float] = []
        lows: list[float] = []
        closes: list[float] = []
        volumes: list[int] = []
        amounts: list[float] = []
        current = start
        while current <= end:
            if current.weekday() < 5:
                base = 1000.0 + (current - start).days * 0.1
                for minute, close in ((0, base), (1, base + 1.0)):
                    timestamp = datetime.combine(current, time(10, minute), tzinfo=TAIPEI)
                    timestamps.append(timestamp.isoformat())
                    opens.append(close - 0.5)
                    highs.append(close + 1.0)
                    lows.append(close - 1.0)
                    closes.append(close)
                    volumes.append(1000 + minute)
                    amounts.append(close * (1000 + minute))
            current += timedelta(days=1)
        return {
            "datetime": timestamps,
            "Open": opens,
            "High": highs,
            "Low": lows,
            "Close": closes,
            "Volume": volumes,
            "Amount": amounts,
        }


class _CancelledQueue:
    async def get(self):
        raise asyncio.CancelledError()


class _FiniteLiveQuoteStore:
    """Expose a real store snapshot, then close the SSE deterministically."""

    def __init__(self, source: LiveQuoteStore):
        self._source = source

    def snapshot(self):
        return self._source.snapshot()

    @asynccontextmanager
    async def subscribe(self):
        yield _CancelledQueue()


class _RecordingQuoteStream:
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


def _subscription(code: str) -> ShioajiQuoteSubscription:
    return ShioajiQuoteSubscription(code=code, exchange="TSE")


def _parse_first_sse_payload(body: str) -> dict:
    for line in body.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    raise AssertionError("SSE response did not contain a data frame")


async def test_taiwan_stub_path_sync_search_group_quote_history_indicators(
    client, db, monkeypatch
):
    """Exercise the approved path from references/contracts to browser data."""
    stub = _ShioajiStub()
    transport = httpx.MockTransport(stub)
    sidecar = ShioajiClient("http://shioaji-stub:8080", transport=transport)
    reference_entries = [
        SymbolEntry(symbol="2330", name="台積電", exchange="TSE", currency="TWD", type="stock"),
        SymbolEntry(symbol="0050", name="元大台灣50", exchange="TSE", currency="TWD", type="etf"),
        SymbolEntry(symbol="6488", name="環球晶", exchange="OTC", currency="TWD", type="stock"),
    ]

    sync_result = await sync_taiwan_symbol_directory(
        db,
        twse_provider=_ReferenceProvider(reference_entries[:2]),
        tpex_provider=_ReferenceProvider(reference_entries[2:]),
        contract_adapter=ShioajiContractsAdapter(sidecar),
    )
    assert sync_result.status == "success"
    assert sync_result.active_count == 3
    assert stub.contract_requests == [{"security_type": "STK"}]

    search_response = await client.get(
        "/api/search", params={"q": "台積", "source": "local"}
    )
    assert search_response.status_code == 200
    assert search_response.json()[0]["symbol"] == "2330"

    stock_response = await client.post(
        "/api/assets", json={"symbol": "2330", "name": "ignored"}
    )
    etf_response = await client.post(
        "/api/assets", json={"symbol": "0050", "name": "ignored"}
    )
    assert stock_response.status_code == etf_response.status_code == 201
    stock = stock_response.json()
    etf = etf_response.json()
    assert (stock["exchange"], stock["currency"], stock["type"]) == ("TSE", "TWD", "stock")
    assert (etf["exchange"], etf["currency"], etf["type"]) == ("TSE", "TWD", "etf")

    groups = (await client.get("/api/groups")).json()
    watchlist_id = next(group["id"] for group in groups if group["is_default"])
    group_response = await client.post(
        f"/api/groups/{watchlist_id}/assets",
        json={"asset_ids": [stock["id"], etf["id"]]},
    )
    assert group_response.status_code == 200
    assert {asset["symbol"] for asset in group_response.json()["assets"]} == {"2330", "0050"}

    live_store = LiveQuoteStore()
    stream = ShioajiQuoteStream("http://shioaji-stub:8080", transport=transport)
    manager = SubscriptionManager(stream, live_store, max_subscriptions=180)
    subscription = _subscription("2330")
    diff = await manager.reconcile([subscription])
    assert diff.subscribed == ("2330",)
    async for update in stream.quote_updates():
        await live_store.update(update.quote)
        break

    live_quote = live_store.get("2330")
    assert live_quote is not None
    assert live_quote.data_status == "LIVE"
    assert live_quote.price == 1200.0
    assert stub.subscribe_requests[0]["code"] == "2330"
    assert stub.stream_requests == 1

    monkeypatch.setattr(quote_service, "async_session", TestSession)
    finite_store = _FiniteLiveQuoteStore(live_store)
    quote_service.configure_live_quote_store(finite_store)
    try:
        stream_response = await client.get("/api/quotes/stream")
    finally:
        quote_service.configure_live_quote_store(LiveQuoteStore())
    assert stream_response.status_code == 200
    stream_payload = _parse_first_sse_payload(stream_response.text)
    assert stream_payload["2330"]["data_status"] == "LIVE"
    assert stream_payload["2330"]["price"] == 1200.0

    updated_at = live_quote.updated_at
    await manager.mark_disconnected()
    disconnected = live_store.get("2330")
    assert disconnected is not None
    assert disconnected.data_status == "DISCONNECTED"
    assert disconnected.updated_at == updated_at
    restored = await manager.restore_after_reconnect(lambda: [subscription])
    assert restored.subscribed == ("2330",)
    assert manager.current_symbols == ("2330",)
    assert len(stub.subscribe_requests) == 2

    queue = HistoricalDataQueue(
        client=sidecar,
        min_interval_seconds=0,
        timeout_seconds=1,
        retry_delays=(),
    )
    monkeypatch.setattr(price_sync, "_get_historical_queue", lambda: queue)
    prices_response = await client.get("/api/assets/2330/prices", params={"period": "3mo"})
    indicators_response = await client.get(
        "/api/assets/2330/indicators", params={"period": "3mo"}
    )
    assert prices_response.status_code == indicators_response.status_code == 200
    assert len(prices_response.json()) >= 40
    assert len(indicators_response.json()) >= 40
    assert any(
        value is not None
        for value in indicators_response.json()[-1]["values"].values()
    )
    assert stub.kbars_requests
    assert all((end - start).days <= 29 for start, end in stub.kbars_requests)


async def test_taiwan_subscription_gate_caps_priority_and_marks_evicted_cached():
    tracked = [*(f"{number:04d}" for number in range(1, 181)), "8888", "9999"]
    first_wanted = compute_wanted_symbols(
        active_asset="9999", tracked_symbols=tracked, cap=180
    )
    second_wanted = compute_wanted_symbols(
        active_asset="8888", tracked_symbols=tracked, cap=180
    )
    assert len(first_wanted) == len(second_wanted) == 180
    assert first_wanted[0] == "9999"
    assert second_wanted[0] == "8888"

    stream = _RecordingQuoteStream()
    store = LiveQuoteStore()
    manager = SubscriptionManager(stream, store, max_subscriptions=180)
    await manager.reconcile(_subscription(code) for code in first_wanted)
    await store.update(
        Quote(symbol="9999", price=100, currency="TWD", data_status="LIVE")
    )
    changed = await manager.reconcile(_subscription(code) for code in second_wanted)

    assert len(manager.current_symbols) == 180
    assert changed.unsubscribed == ("9999",)
    assert changed.subscribed == ("8888",)
    assert store.get("9999").data_status == "CACHED"
    assert "9999" not in manager.current_symbols
