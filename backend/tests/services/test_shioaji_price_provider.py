"""Offline Shioaji snapshot to Fibenchi Quote contract tests."""

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.config import Settings
from app.domain import AssetRef
from app.schemas.quote import Quote
from app.services.price_providers import _PROVIDERS
from app.services.price_providers.shioaji import ShioajiPriceProvider
from app.services.shioaji.client import (
    ShioajiClient,
    ShioajiUnavailableError,
)
from app.services.shioaji.quotes import ShioajiSnapshot

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "shioaji" / "quotes.json"
FIXTURE_ROWS = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


class FixtureShioajiClient:
    def __init__(self, rows=None, error=None):
        self.rows = [ShioajiSnapshot.model_validate(row) for row in (rows or [])]
        self.error = error
        self.calls: list[list[dict[str, str]]] = []

    async def snapshots(self, contracts):
        self.calls.append([dict(contract) for contract in contracts])
        if self.error is not None:
            raise self.error
        requested = {(contract["exchange"], contract["code"]) for contract in contracts}
        return [
            row for row in self.rows if (row.exchange, row.code) in requested
        ]


def test_settings_and_registry_default_to_shioaji():
    assert Settings().price_provider == "shioaji"
    assert _PROVIDERS == {"shioaji": ShioajiPriceProvider}


def test_fixture_maps_exactly_to_quote_schema():
    provider = ShioajiPriceProvider(client=FixtureShioajiClient(FIXTURE_ROWS))
    snapshot = ShioajiSnapshot.model_validate(FIXTURE_ROWS[0])

    quote = provider.map_snapshot(snapshot)

    assert quote == Quote(
        symbol="2330",
        price=2240.0,
        previous_close=2265.0,
        change=-25.0,
        change_percent=-1.1,
        volume=25820,
        avg_volume=None,
        currency="TWD",
        market_state=None,
        session_date="2026-05-18",
        data_status="CACHED",
        updated_at=datetime(2026, 5, 18, 14, 30, tzinfo=ZoneInfo("Asia/Taipei")),
        open=2225.0,
        high=2260.0,
        low=2215.0,
        bid=2240.0,
        bid_volume=524,
        ask=2245.0,
        ask_volume=103,
    )


@pytest.mark.asyncio
async def test_provider_preserves_raw_codes_and_verified_exchanges():
    client = FixtureShioajiClient(FIXTURE_ROWS)
    provider = ShioajiPriceProvider(client=client)

    quotes = await provider.batch_fetch_quotes(
        [AssetRef("0050", exchange="TSE"), AssetRef("6488", exchange="OTC")]
    )

    assert [quote.symbol for quote in quotes] == ["0050", "6488"]
    assert [quote.currency for quote in quotes] == ["TWD", "TWD"]
    assert client.calls == [[
        {"security_type": "STK", "exchange": "TSE", "code": "0050"},
        {"security_type": "STK", "exchange": "OTC", "code": "6488"},
    ]]


@pytest.mark.asyncio
async def test_provider_returns_disconnected_placeholders_on_sidecar_failure():
    provider = ShioajiPriceProvider(
        client=FixtureShioajiClient(error=ShioajiUnavailableError("offline"))
    )

    quotes = await provider.batch_fetch_quotes([AssetRef("2330", exchange="TSE")])

    assert quotes == [Quote.placeholder("2330", currency="TWD")]
    assert quotes[0].data_status == "DISCONNECTED"
    assert quotes[0].updated_at is None
    assert quotes[0].is_placeholder


@pytest.mark.asyncio
async def test_provider_returns_placeholder_for_missing_snapshot():
    provider = ShioajiPriceProvider(client=FixtureShioajiClient([]))

    quotes = await provider.batch_fetch_quotes([AssetRef("9999", exchange="TSE")])

    assert quotes == [Quote.placeholder("9999", currency="TWD")]
    assert quotes[0].data_status == "DISCONNECTED"


@pytest.mark.asyncio
async def test_client_posts_official_snapshot_contract_shape():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/data/snapshots"
        assert json.loads(request.content) == {
            "contracts": [
                {"security_type": "STK", "exchange": "TSE", "code": "0050"}
            ]
        }
        return httpx.Response(200, json=[FIXTURE_ROWS[1]])

    client = ShioajiClient(
        "http://shioaji-stub:8080",
        transport=httpx.MockTransport(handler),
    )

    snapshots = await client.snapshots([
        {"security_type": "STK", "exchange": "TSE", "code": "0050"}
    ])

    assert snapshots[0].code == "0050"
    assert snapshots[0].exchange == "TSE"
