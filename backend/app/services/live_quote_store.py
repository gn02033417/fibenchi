"""In-memory latest-value store for normalized Shioaji live quotes."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager

from app.schemas.quote import Quote, QuoteDataStatus


class LiveQuoteStore:
    """Keep the latest quote per symbol and notify async subscribers of changes."""

    def __init__(self) -> None:
        self._quotes: dict[str, Quote] = {}
        self._listeners: set[asyncio.Queue[Quote]] = set()

    def get(self, symbol: str) -> Quote | None:
        return self._quotes.get(_normalize_symbol(symbol))

    def snapshot(self) -> dict[str, Quote]:
        return dict(self._quotes)

    @asynccontextmanager
    async def subscribe(self, *, max_queue_size: int = 64) -> AsyncIterator[asyncio.Queue[Quote]]:
        """Register one listener and yield its update queue until context exit."""
        if max_queue_size <= 0:
            raise ValueError("max_queue_size must be greater than zero")
        queue: asyncio.Queue[Quote] = asyncio.Queue(maxsize=max_queue_size)
        self._listeners.add(queue)
        try:
            yield queue
        finally:
            self._listeners.discard(queue)

    async def update(self, quote: Quote) -> Quote:
        """Store and publish the latest normalized quote for its symbol."""
        symbol = _normalize_symbol(quote.symbol)
        stored = quote.model_copy(update={"symbol": symbol})
        self._quotes[symbol] = stored
        self._publish(stored)
        return stored

    async def mark_cached(self, symbols: Iterable[str]) -> None:
        await self._mark_status(symbols, "CACHED")

    async def mark_disconnected(self, symbols: Iterable[str]) -> None:
        await self._mark_status(symbols, "DISCONNECTED")

    async def _mark_status(self, symbols: Iterable[str], status: QuoteDataStatus) -> None:
        seen: set[str] = set()
        for raw_symbol in symbols:
            symbol = _normalize_symbol(raw_symbol)
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            existing = self._quotes.get(symbol)
            stored = (
                existing.model_copy(update={"data_status": status})
                if existing is not None
                else Quote.placeholder(symbol, currency="TWD", data_status=status)
            )
            self._quotes[symbol] = stored
            self._publish(stored)

    def _publish(self, quote: Quote) -> None:
        for queue in tuple(self._listeners):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(quote)


def _normalize_symbol(symbol: str) -> str:
    return str(symbol).strip().upper()


__all__ = ["LiveQuoteStore"]
