"""TPEx official reference-data provider for OTC stocks and ETFs."""

import json
import logging
from collections.abc import Mapping, Sequence
from html.parser import HTMLParser

import httpx

from app.services.symbol_providers.base import SymbolEntry, SymbolProvider

logger = logging.getLogger(__name__)

TPEX_BASE_URL = "https://www.tpex.org.tw/openapi/v1"
TPEX_STOCKS_URL = f"{TPEX_BASE_URL}/mopsfin_t187ap03_O"
# TPEx publishes the ETF reference table through its official ETF InfoHub.
TPEX_ETFS_URL = "https://info.tpex.org.tw/ETF/zh/filter.html"

_STOCK_CODE_FIELDS = (
    "SecuritiesCompanyCode",
    "SecurityCompanyCode",
    "公司代號",
    "證券代號",
    "code",
    "Code",
)
_STOCK_NAME_FIELDS = (
    "CompanyAbbreviation",
    "CompanyName",
    "公司簡稱",
    "公司名稱",
    "證券名稱",
    "name",
    "Name",
)
_STOCK_CATEGORY_FIELDS = (
    "SecuritiesType",
    "SecurityType",
    "SecuritiesCategory",
    "SecurityCategory",
    "證券類別",
    "證券種類",
    "商品類型",
    "類別",
    "type",
    "Type",
)

_ETF_CODE_FIELDS = (
    "SecuritiesCode",
    "SecurityCode",
    "SecuritiesCompanyCode",
    "證券代號",
    "ETF代號",
    "基金代號",
    "code",
    "Code",
)
_ETF_NAME_FIELDS = (
    "ETFName",
    "ETF名稱",
    "SecuritiesAbbreviation",
    "證券簡稱",
    "證券名稱",
    "name",
    "Name",
)
_ETF_CATEGORY_FIELDS = (
    "ETFCategory",
    "ETF類別",
    "AssetClass",
    "資產類別",
    "證券類別",
    "證券種類",
    "type",
    "Type",
)

_STOCK_UNSUPPORTED_MARKERS = (
    "EMERGING",
    "興櫃",
    "WARRANT",
    "權證",
    "ETN",
    "ETC",
    "OPTION",
    "選擇權",
    "FUTURE",
    "期貨",
    "INDEX",
    "指數",
    "BOND",
    "債券",
    "ETF",
    "FUND",
    "基金",
)
_ETF_UNSUPPORTED_MARKERS = (
    "EMERGING",
    "興櫃",
    "WARRANT",
    "權證",
    "ETN",
    "ETC",
    "OPTION",
    "選擇權",
)


def _rows(payload: object) -> list[Mapping[str, object]]:
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


def _has_marker(value: str, markers: Sequence[str]) -> bool:
    normalized = value.strip().upper()
    return any(marker in normalized for marker in markers)


def _stock_category_allowed(category: str) -> bool:
    return not category or not _has_marker(category, _STOCK_UNSUPPORTED_MARKERS)


def _etf_category_allowed(category: str) -> bool:
    if not category:
        # The official ETF InfoHub endpoint is already an ETF-only source.
        return True
    if _has_marker(category, _ETF_UNSUPPORTED_MARKERS):
        return False
    normalized = category.upper()
    return (
        "ETF" in normalized
        or "基金" in category
        or "ASSET" in normalized
        or "EQUITY" in normalized
        or "BOND" in normalized
    )


class _TableRowsParser(HTMLParser):
    """Collect table rows without requiring a third-party HTML dependency."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in {"th", "td"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"th", "td"} and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if any(self._row):
                self.rows.append(self._row)
            self._row = None


def _parse_html_etf_rows(raw_html: str) -> list[dict[str, str]]:
    parser = _TableRowsParser()
    parser.feed(raw_html)

    for header_index, header in enumerate(parser.rows):
        normalized = [value.strip().lower() for value in header]
        code_index = next(
            (
                index
                for index, value in enumerate(normalized)
                if "證券代號" in value or "securities code" in value or "security code" in value
            ),
            None,
        )
        name_index = next(
            (
                index
                for index, value in enumerate(normalized)
                if "etf名稱" in value or "etf name" in value
            ),
            None,
        )
        if code_index is None or name_index is None:
            continue

        category_index = next(
            (
                index
                for index, value in enumerate(normalized)
                if "etf類別" in value or "asset class" in value or "資產類別" in value
            ),
            None,
        )
        rows: list[dict[str, str]] = []
        for row in parser.rows[header_index + 1 :]:
            if len(row) <= max(code_index, name_index):
                continue
            values = {
                "證券代號": row[code_index],
                "ETF名稱": row[name_index],
            }
            if category_index is not None and category_index < len(row):
                values["ETF類別"] = row[category_index]
            rows.append(values)
        return rows
    return []


def _etf_rows(payload: object) -> list[Mapping[str, object]]:
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="replace")
    if isinstance(payload, str):
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError:
            return _parse_html_etf_rows(payload)
        return _rows(decoded)
    return _rows(payload)


def parse_tpex_stocks(payload: object) -> list[SymbolEntry]:
    """Normalize TPEx's official OTC company JSON payload."""
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
                exchange="OTC",
                currency="TWD",
                type="stock",
            )
        )
    return results


def parse_tpex_etfs(payload: object) -> list[SymbolEntry]:
    """Normalize TPEx's official ETF InfoHub JSON or HTML table."""
    results: list[SymbolEntry] = []
    seen: set[str] = set()

    for row in _etf_rows(payload):
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
                exchange="OTC",
                currency="TWD",
                type="etf",
            )
        )
    return results


class TPEXProvider(SymbolProvider):
    """Fetch and normalize official TPEx OTC stock and ETF reference data."""

    async def fetch_symbols(self, config: dict) -> list[SymbolEntry]:
        stocks_url = config.get("stocks_url", TPEX_STOCKS_URL)
        etfs_url = config.get("etfs_url", TPEX_ETFS_URL)
        timeout = config.get("timeout", 30.0)

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            stocks_response = await client.get(stocks_url)
            stocks_response.raise_for_status()
            etfs_response = await client.get(etfs_url)
            etfs_response.raise_for_status()

        stocks = parse_tpex_stocks(stocks_response.text)
        if not stocks:
            raise RuntimeError("TPEx stock reference source returned no usable symbols")
        etfs = parse_tpex_etfs(etfs_response.text)
        if not etfs:
            raise RuntimeError("TPEx ETF reference source returned no usable symbols")
        results = stocks + etfs
        logger.info(
            "TPEx provider fetched %d symbols (%d stocks, %d ETFs)",
            len(results),
            len(stocks),
            len(etfs),
        )
        return results

    @staticmethod
    def available_markets() -> list[dict]:
        return [{"key": "otc", "label": "Taipei Exchange (OTC)"}]


# Keep both spellings available: TPEx is the exchange's official branding,
# while TPEX matches the module/provider key convention used by this package.
TPExProvider = TPEXProvider
