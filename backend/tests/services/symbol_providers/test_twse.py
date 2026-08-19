"""Offline tests for the official TWSE reference-data provider."""

import json
from pathlib import Path

import pytest

from app.services.symbol_providers import get_available_providers, get_provider
from app.services.symbol_providers.twse import (
    TWSEProvider,
    parse_twse_etfs,
    parse_twse_stocks,
)

FIXTURE_DIR = Path(__file__).parents[2] / "fixtures" / "twse"


def _load_fixture(name: str) -> list[dict[str, str]]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_parse_twse_stocks_uses_raw_code_and_tse_metadata():
    results = parse_twse_stocks(_load_fixture("stocks.json"))

    assert len(results) == 1
    entry = results[0]
    assert entry.symbol == "2330"
    assert entry.name == "台積電"
    assert entry.exchange == "TSE"
    assert entry.currency == "TWD"
    assert entry.type == "stock"


def test_parse_twse_etfs_preserves_leading_zeroes_and_filters_unsupported():
    results = parse_twse_etfs(_load_fixture("etfs.json"))

    by_symbol = {entry.symbol: entry for entry in results}
    assert set(by_symbol) == {"0050", "00679B"}
    assert by_symbol["0050"].name == "元大台灣卓越50證券投資信託基金"
    assert by_symbol["0050"].exchange == "TSE"
    assert by_symbol["0050"].currency == "TWD"
    assert by_symbol["0050"].type == "etf"
    assert by_symbol["00679B"].type == "etf"


@pytest.mark.asyncio
async def test_fetch_symbols_is_offline_when_http_is_mocked(monkeypatch):
    class MockResponse:
        def __init__(self, payload):
            self.text = json.dumps(payload, ensure_ascii=False)

        def raise_for_status(self):
            pass

    class MockClient:
        requested_urls: list[str] = []

        async def get(self, url):
            self.requested_urls.append(url)
            if url.endswith("stocks"):
                return MockResponse(_load_fixture("stocks.json"))
            return MockResponse(_load_fixture("etfs.json"))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    client = MockClient()
    monkeypatch.setattr(
        "app.services.symbol_providers.twse.httpx.AsyncClient",
        lambda **kwargs: client,
    )

    results = await TWSEProvider().fetch_symbols(
        {"stocks_url": "https://fixture/stocks", "etfs_url": "https://fixture/etfs"}
    )

    assert [entry.symbol for entry in results] == ["2330", "0050", "00679B"]
    assert client.requested_urls == ["https://fixture/stocks", "https://fixture/etfs"]


@pytest.mark.asyncio
async def test_fetch_symbols_rejects_empty_etf_snapshot(monkeypatch):
    class MockResponse:
        def __init__(self, payload):
            self.text = json.dumps(payload, ensure_ascii=False)

        def raise_for_status(self):
            pass

    class MockClient:
        async def get(self, url):
            return MockResponse(_load_fixture("stocks.json") if url.endswith("stocks") else [])

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(
        "app.services.symbol_providers.twse.httpx.AsyncClient",
        lambda **kwargs: MockClient(),
    )

    with pytest.raises(RuntimeError, match="ETF"):
        await TWSEProvider().fetch_symbols(
            {"stocks_url": "https://fixture/stocks", "etfs_url": "https://fixture/etfs"}
        )


def test_twse_provider_is_registered():
    assert isinstance(get_provider("twse"), TWSEProvider)
    providers = get_available_providers()
    assert providers["twse"]["markets"] == [{"key": "tse", "label": "Taiwan Stock Exchange (TSE)"}]

