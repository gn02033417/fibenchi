"""Taiwan quote provider backed by the isolated Shioaji sidecar."""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd

from app.models.symbol_directory import TAIWAN_EXCHANGES
from app.schemas.quote import Quote
from app.services.price_providers.base import PriceProvider
from app.services.shioaji.client import ShioajiClient, ShioajiClientError
from app.services.shioaji.quotes import ShioajiSnapshot, map_snapshot_to_quote

logger = logging.getLogger(__name__)

_TAIWAN_EXCHANGE_ORDER = ("TSE", "OTC")
_SNAPSHOT_BATCH_SIZE = 500


class ShioajiPriceProvider(PriceProvider):
    """PriceProvider implementation for supported Taiwan stock contracts."""

    def __init__(self, client: ShioajiClient | None = None):
        self.client = client or ShioajiClient()

    async def fetch_history(
        self,
        symbol: str,
        period: str = "3mo",
        interval: str = "1d",
        start: date | None = None,
        end: date | None = None,
    ) -> pd.DataFrame:
        raise ValueError(
            "Shioaji historical data is not available in the quote provider"
        )

    async def batch_fetch_history(
        self, symbols: list[str], period: str = "1y"
    ) -> dict[str, pd.DataFrame]:
        return {}

    async def batch_fetch_quotes(self, symbols: list[str]) -> list[Quote]:
        requested: list[tuple[str, tuple[str, ...]]] = []
        seen_symbols: set[str] = set()
        contracts: list[dict[str, str]] = []

        for symbol in symbols:
            raw_symbol = str(symbol).strip().upper()
            if not raw_symbol or raw_symbol in seen_symbols:
                continue
            seen_symbols.add(raw_symbol)

            exchange = getattr(symbol, "exchange", None)
            exchange = exchange.upper().strip() if exchange else None
            exchanges = (
                (exchange,)
                if exchange in TAIWAN_EXCHANGES
                else _TAIWAN_EXCHANGE_ORDER
            )
            requested.append((raw_symbol, exchanges))
            contracts.extend(
                {
                    "security_type": "STK",
                    "exchange": venue,
                    "code": raw_symbol,
                }
                for venue in exchanges
            )

        if not requested:
            return []

        snapshots_by_key: dict[tuple[str, str], ShioajiSnapshot] = {}
        for offset in range(0, len(contracts), _SNAPSHOT_BATCH_SIZE):
            batch = contracts[offset : offset + _SNAPSHOT_BATCH_SIZE]
            try:
                snapshots = await self.client.snapshots(batch)
            except ShioajiClientError as exc:
                logger.warning(
                    "Shioaji snapshot batch unavailable for %d contracts: %s",
                    len(batch),
                    exc,
                )
                continue

            for snapshot in snapshots:
                if snapshot.exchange not in TAIWAN_EXCHANGES:
                    continue
                snapshots_by_key[(snapshot.code, snapshot.exchange)] = snapshot

        results: list[Quote] = []
        for raw_symbol, exchanges in requested:
            snapshot = next(
                (
                    snapshots_by_key.get((raw_symbol, exchange))
                    for exchange in exchanges
                    if (raw_symbol, exchange) in snapshots_by_key
                ),
                None,
            )
            results.append(
                map_snapshot_to_quote(snapshot)
                if snapshot is not None
                else Quote.placeholder(raw_symbol, currency="TWD")
            )
        return results

    async def batch_fetch_currencies(self, symbols: list[str]) -> dict[str, str]:
        return {str(symbol): "TWD" for symbol in symbols}

    @staticmethod
    def map_snapshot(snapshot: ShioajiSnapshot) -> Quote:
        """Expose the pure mapper for fixture-driven contract tests."""
        return map_snapshot_to_quote(snapshot)


__all__ = ["ShioajiPriceProvider"]
