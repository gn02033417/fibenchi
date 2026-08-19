"""Offline tests for the official TPEx reference-data provider."""

import json
from pathlib import Path

import pytest

from app.services.symbol_providers import get_available_providers, get_provider
from app.services.symbol_providers.tpex import (
    TPEXProvider,
    parse_tpex_etfs,
    parse_tpex_stocks,
)

FIXTURE_DIR = Path(__file__).parents[2] / "fixtures" / "tpex"


def _load_json_fixture(name: str) -> list[dict[str, str]]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _load_text_fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def test_parse_tpex_stocks_uses_raw_code_and_otc_metadata():
    results = parse_tpex_stocks(_load_json_fixture("stocks.json"))

    assert len(results) == 1
    entry = results[0]
    assert entry.symbol == "6488"
    assert entry.name == "環球晶"
    assert entry.exchange == "OTC"
    assert entry.currency == "TWD"
    assert entry.type == "stock"


def test_parse_tpex_etfs_preserves_leading_zeroes_and_filters_unsupported():
    results = parse_tpex_etfs(_load_text_fixture("etfs.html"))

    assert len(results) == 1
    entry = results[0]
    assert entry.symbol == "00970B"
    assert entry.name == "野村美國短期非投資等級債ETF"
    assert entry.exchange == "OTC"
    assert entry.currency == "TWD"
    assert entry.type == "etf"


@pytest.mark.asyncio
async def test_fetch_symbols_is_offline_when_http_is_mocked(monkeypatch):
    class MockResponse:
        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            pass

    class MockClient:
        requested_urls: list[str] = []

        async def get(self, url):
            self.requested_urls.append(url)
            if url.endswith("stocks"):
                return MockResponse(json.dumps(_load_json_fixture("stocks.json"), ensure_ascii=False))
            return MockResponse(_load_text_fixture("etfs.html"))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    client = MockClient()
    monkeypatch.setattr(
        "app.services.symbol_providers.tpex.httpx.AsyncClient",
        lambda **kwargs: client,
    )

    results = await TPEXProvider().fetch_symbols(
        {"stocks_url": "https://fixture/stocks", "etfs_url": "https://fixture/etfs"}
    )

    assert [entry.symbol for entry in results] == ["6488", "00970B"]
    assert client.requested_urls == ["https://fixture/stocks", "https://fixture/etfs"]


def test_tpex_provider_is_registered():
    assert isinstance(get_provider("tpex"), TPEXProvider)
    providers = get_available_providers()
    assert providers["tpex"]["markets"] == [{"key": "otc", "label": "Taipei Exchange (OTC)"}]
