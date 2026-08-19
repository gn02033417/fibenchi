"""TWSE official reference-data provider for listed stocks and ETFs."""

import json
import logging
from collections.abc import Mapping, Sequence

import httpx

from app.services.symbol_providers.base import SymbolEntry, SymbolProvider

logger = logging.getLogger(__name__)

TWSE_BASE_URL = "https://openapi.twse.com.tw/v1"
TWSE_STOCKS_URL = f"{TWSE_BASE_URL}/opendata/t187ap03_L"
TWSE_ETFS_URL = f"{TWSE_BASE_URL}/opendata/t187ap47_L"

_STOCK_CODE_FIELDS = ("公司代號", "證券代號", "股票代號", "code", "Code")
_STOCK_NAME_FIELDS = ("公司簡稱", "公司名稱", "證券名稱", "name", "Name")
_STOCK_CATEGORY_FIELDS = ("證券類別", "證券種類", "商品類型", "類別", "type", "Type")

_ETF_CODE_FIELDS = ("基金代號", "證券代號", "基金代碼", "code", "Code")
_ETF_NAME_FIELDS = (
    "基金簡稱",
    "基金中文名稱",
    "基金名稱",
    "證券名稱",
    "name",
    "Name",
)
_ETF_CATEGORY_FIELDS = ("基金類型", "證券類別", "證券種類", "商品類型", "類別", "type", "Type")

_UNSUPPORTED_MARKERS = (
    "ETN",
    "ETC",
    "WARRANT",
    "OPTION",
    "權證",
    "選擇權",
    "興櫃",
)


def _rows(payload: object) -> list[Mapping[str, object]]:
    """Extract object rows from the list-shaped TWSE response."""
    if isinstance(payload, (str, bytes, bytearray)):
        try:
            payload = json.loads(payload)
        except (TypeError, json.JSONDecodeError):
            return []

    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        return [row for row in payload if isinstance(row, Mapping)]

    if isinstance(payload, Mapping):
        for key in ("data", "records", "items", "result"):
            nested = payload.get(key)
            if isinstance(nested, Sequence) and not isinstance(nested, (str, bytes, bytearray)):
                return [row for row in nested if isinstance(row, Mapping)]
    return []


def _value(row: Mapping[str, object], fields: Sequence[str]) -> str:
    for field in fields:
        value = row.get(field)
        if value is not None:
            text = str(value).strip()
            if text:
                return text
    return ""


def _has_unsupported_category(category: str) -> bool:
    normalized = category.strip().upper()
    return any(marker in normalized for marker in _UNSUPPORTED_MARKERS)


def _stock_category_allowed(category: str) -> bool:
    """Use official category metadata when present; never infer from the code."""
    if not category:
        return True
    normalized = category.upper()
    return not (
        _has_unsupported_category(category)
        or "ETF" in normalized
        or "FUND" in normalized
        or "基金" in category
        or "FUTURE" in normalized
        or "期貨" in category
        or "INDEX" in normalized
        or "指數" in category
    )


def _etf_category_allowed(category: str) -> bool:
    """Accept the official ETF/fund categories while excluding other products."""
    if not category:
        # t187ap47_L is already TWSE's ETF/fund master endpoint.
        return True
    normalized = category.strip().upper()
    if _has_unsupported_category(category):
        return False
    return "ETF" in normalized or "基金" in category


def parse_twse_stocks(payload: object) -> list[SymbolEntry]:
    """Normalize TWSE's listed-company JSON payload into raw TSE stock entries."""
    results: list[SymbolEntry] = []
    seen: set[str] = set()

    for row in _rows(payload):
        symbol = _value(row, _STOCK_CODE_FIELDS)
        name = _value(row, _STOCK_NAME_FIELDS)
        category = _value(row, _STOCK_CATEGORY_FIELDS)
        if not symbol or not name or symbol in seen or not _stock_category_allowed(category):
            continue
        seen.add(symbol)
        results.append(
            SymbolEntry(
                symbol=symbol,
                name=name,
                exchange="TSE",
                currency="TWD",
                type="stock",
            )
        )
    return results


def parse_twse_etfs(payload: object) -> list[SymbolEntry]:
    """Normalize TWSE's ETF master JSON payload into raw TSE ETF entries."""
    results: list[SymbolEntry] = []
    seen: set[str] = set()

    for row in _rows(payload):
        symbol = _value(row, _ETF_CODE_FIELDS)
        name = _value(row, _ETF_NAME_FIELDS)
        category = _value(row, _ETF_CATEGORY_FIELDS)
        if not symbol or not name or symbol in seen or not _etf_category_allowed(category):
            continue
        seen.add(symbol)
        results.append(
            SymbolEntry(
                symbol=symbol,
                name=name,
                exchange="TSE",
                currency="TWD",
                type="etf",
            )
        )
    return results


class TWSEProvider(SymbolProvider):
    """Fetch and normalize TWSE's official stock and ETF reference data."""

    async def fetch_symbols(self, config: dict) -> list[SymbolEntry]:
        stocks_url = config.get("stocks_url", TWSE_STOCKS_URL)
        etfs_url = config.get("etfs_url", TWSE_ETFS_URL)
        timeout = config.get("timeout", 30.0)

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            stocks_response = await client.get(stocks_url)
            stocks_response.raise_for_status()
            etfs_response = await client.get(etfs_url)
            etfs_response.raise_for_status()

        stocks = parse_twse_stocks(json.loads(stocks_response.text))
        etfs = parse_twse_etfs(json.loads(etfs_response.text))
        results = stocks + etfs
        logger.info(
            "TWSE provider fetched %d symbols (%d stocks, %d ETFs)",
            len(results),
            len(stocks),
            len(etfs),
        )
        return results

    @staticmethod
    def available_markets() -> list[dict]:
        return [{"key": "tse", "label": "Taiwan Stock Exchange (TSE)"}]
