"""Bounded, shared scheduling for Shioaji historical Kbars requests."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import date, timedelta
from typing import Protocol

from app.domain.assetref import AssetRef
from app.services.shioaji.client import (
    ShioajiClient,
    ShioajiClientError,
    ShioajiHTTPError,
    ShioajiTimeoutError,
    ShioajiUnavailableError,
)
from app.services.shioaji.kbars import MinuteBar

_MAX_KBARS_CALENDAR_DAYS = 30
_TAIWAN_EXCHANGES = frozenset({"TSE", "OTC"})


class KbarsClient(Protocol):
    """The narrow Shioaji client surface required by this queue."""

    async def kbars(
        self,
        contract: Mapping[str, str],
        *,
        start: date,
        end: date,
    ) -> list[MinuteBar]: ...


class HistoricalDataQueueError(RuntimeError):
    """A single requested Kbars range failed after its bounded retries."""

    def __init__(self, asset: AssetRef, start: date, end: date):
        self.asset = asset
        self.start = start
        self.end = end
        super().__init__(f"Historical Kbars request failed for {asset} from {start} through {end}")


class HistoricalDataQueue:
    """Centralize bounded Shioaji Kbars work without persistence concerns.

    ``fetch(asset, start, end)`` uses inclusive calendar dates at both ends.
    A 30-day request therefore spans ``start`` through ``start + 29 days``;
    larger ranges are split into adjacent, non-overlapping requests.
    """

    def __init__(
        self,
        client: KbarsClient | None = None,
        *,
        min_interval_seconds: float = 0.25,
        timeout_seconds: float = 10.0,
        retry_delays: tuple[float, ...] = (0.25, 0.5),
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        if min_interval_seconds < 0:
            raise ValueError("min_interval_seconds cannot be negative")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if any(delay < 0 for delay in retry_delays):
            raise ValueError("retry_delays cannot contain negative values")

        self._client = client or ShioajiClient()
        self._min_interval_seconds = min_interval_seconds
        self._timeout_seconds = timeout_seconds
        self._retry_delays = retry_delays
        self._clock = clock
        self._sleep = sleep
        self._next_request_at = 0.0
        self._rate_lock = asyncio.Lock()
        self._inflight_lock = asyncio.Lock()
        self._inflight: dict[tuple[str, str, date, date], asyncio.Task[tuple[MinuteBar, ...]]] = {}

    async def fetch(self, asset: AssetRef, start: date, end: date) -> list[MinuteBar]:
        """Fetch inclusive ``start``/``end`` minute bars for one Taiwan asset."""
        symbol, exchange = self._asset_identity(asset)
        if end < start:
            raise ValueError("end must be on or after start")

        key = (symbol, exchange, start, end)
        async with self._inflight_lock:
            task = self._inflight.get(key)
            if task is None:
                task = asyncio.create_task(self._fetch_range(asset, symbol, exchange, start, end))
                self._inflight[key] = task
                task.add_done_callback(
                    lambda completed, request_key=key: self._discard_completed(request_key, completed)
                )

        return list(await asyncio.shield(task))

    async def _fetch_range(
        self,
        asset: AssetRef,
        symbol: str,
        exchange: str,
        start: date,
        end: date,
    ) -> tuple[MinuteBar, ...]:
        contract = {"security_type": "STK", "exchange": exchange, "code": symbol}
        bars: list[MinuteBar] = []
        for chunk_start, chunk_end in self._chunks(start, end):
            bars.extend(await self._fetch_chunk(contract, asset, chunk_start, chunk_end))
        return tuple(sorted(bars, key=lambda bar: bar.timestamp))

    async def _fetch_chunk(
        self,
        contract: Mapping[str, str],
        asset: AssetRef,
        start: date,
        end: date,
    ) -> list[MinuteBar]:
        for retry_delay in (*self._retry_delays, None):
            try:
                await self._wait_for_rate_slot()
                return await self._request_with_timeout(contract, start, end)
            except ShioajiClientError as exc:
                if retry_delay is None or not self._is_retryable(exc):
                    raise HistoricalDataQueueError(asset, start, end) from exc
                await self._sleep(retry_delay)

        raise AssertionError("retry loop must return or raise")

    async def _request_with_timeout(
        self,
        contract: Mapping[str, str],
        start: date,
        end: date,
    ) -> list[MinuteBar]:
        try:
            return await asyncio.wait_for(
                self._client.kbars(contract, start=start, end=end),
                timeout=self._timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise ShioajiTimeoutError("Historical Kbars request timed out") from exc

    async def _wait_for_rate_slot(self) -> None:
        async with self._rate_lock:
            delay = self._next_request_at - self._clock()
            if delay > 0:
                await self._sleep(delay)
            self._next_request_at = max(self._next_request_at, self._clock()) + self._min_interval_seconds

    @staticmethod
    def _asset_identity(asset: AssetRef) -> tuple[str, str]:
        symbol = str(asset).strip().upper()
        exchange = asset.exchange.upper().strip() if asset.exchange else ""
        if not symbol:
            raise ValueError("asset symbol cannot be blank")
        if exchange not in _TAIWAN_EXCHANGES:
            raise ValueError("AssetRef.exchange must be TSE or OTC for Shioaji Kbars")
        return symbol, exchange

    @staticmethod
    def _chunks(start: date, end: date) -> list[tuple[date, date]]:
        chunks: list[tuple[date, date]] = []
        cursor = start
        while cursor <= end:
            chunk_end = min(cursor + timedelta(days=_MAX_KBARS_CALENDAR_DAYS - 1), end)
            chunks.append((cursor, chunk_end))
            cursor = chunk_end + timedelta(days=1)
        return chunks

    @staticmethod
    def _is_retryable(exc: ShioajiClientError) -> bool:
        if isinstance(exc, (ShioajiTimeoutError, ShioajiUnavailableError)):
            return True
        return isinstance(exc, ShioajiHTTPError) and exc.status_code >= 500

    def _discard_completed(
        self,
        key: tuple[str, str, date, date],
        task: asyncio.Task[tuple[MinuteBar, ...]],
    ) -> None:
        if self._inflight.get(key) is task:
            self._inflight.pop(key, None)


__all__ = ["HistoricalDataQueue", "HistoricalDataQueueError", "KbarsClient"]
