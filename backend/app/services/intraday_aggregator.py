"""Event-driven Taiwan 1-minute intraday aggregation.

The upstream Quote event exposes both the volume of the current tick and the
cumulative volume since the market opened.  This module owns the only place
where those values become intraday bar volume.  It deliberately keeps the
current minute in memory as ``forming`` and emits the previous minute as
``completed`` when a later minute is observed.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from app.domain.phases import Session
from app.schemas.intraday import IntradayBar, IntradayBarStatus
from app.schemas.quote import Quote
from app.services.shioaji.stream import ShioajiQuoteUpdate

TAIPEI = ZoneInfo("Asia/Taipei")
IntradayBucketStatus = Literal["forming", "completed"]


@dataclass(slots=True)
class IntradayBucket:
    """Mutable OHLCV state for one XTAI minute."""

    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    session: Session
    status: IntradayBucketStatus = "forming"
    gap: bool = False
    first_event_at: datetime = field(repr=False, compare=False, default_factory=lambda: datetime.min)

    def as_bar(self) -> IntradayBar:
        """Convert the mutable bucket into the existing chart wire model."""
        status: IntradayBarStatus = self.status
        return IntradayBar(
            time=int(self.timestamp.timestamp()),
            price=self.close,
            volume=self.volume,
            session=self.session,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            status=status,
            gap=self.gap,
        )


@dataclass(frozen=True, slots=True)
class IntradayUpdate:
    """One symbol-scoped bar update delivered to browser SSE subscribers."""

    symbol: str
    bar: IntradayBar


class IntradayAggregator:
    """Aggregate normalized Shioaji Quote updates into XTAI minute buckets."""

    def __init__(self, *, max_seen_events: int = 8192) -> None:
        if max_seen_events <= 0:
            raise ValueError("max_seen_events must be greater than zero")
        self._max_seen_events = max_seen_events
        self._buckets: dict[str, dict[datetime, IntradayBucket]] = {}
        self._current: dict[str, IntradayBucket] = {}
        self._last_total_volume: dict[str, int] = {}
        self._needs_gap: set[str] = set()
        self._seen_event_ids: dict[str, deque[str]] = {}
        self._seen_event_sets: dict[str, set[str]] = {}
        self._listeners: set[asyncio.Queue[IntradayUpdate]] = set()

    @asynccontextmanager
    async def subscribe(
        self,
        *,
        max_queue_size: int = 64,
    ) -> AsyncIterator[asyncio.Queue[IntradayUpdate]]:
        """Subscribe to live forming/completed bar updates."""
        if max_queue_size <= 0:
            raise ValueError("max_queue_size must be greater than zero")
        queue: asyncio.Queue[IntradayUpdate] = asyncio.Queue(maxsize=max_queue_size)
        self._listeners.add(queue)
        try:
            yield queue
        finally:
            self._listeners.discard(queue)

    def ingest(self, update: ShioajiQuoteUpdate | Quote) -> tuple[IntradayBucket, ...]:
        """Apply one live quote and return only changed bars.

        Duplicate event ids are ignored before volume accounting.  If the
        event arrives after a disconnect, the cumulative-volume jump is not
        assigned to the new minute; only that event's explicit tick volume is
        counted.  Missing minutes are left absent and the next real bucket is
        marked with ``gap=True``.
        """
        if isinstance(update, Quote):
            update = ShioajiQuoteUpdate.from_quote(update)

        timestamp = _as_taipei(update.timestamp or update.quote.updated_at)
        price = update.quote.price
        symbol = update.symbol.strip().upper()
        if timestamp is None or price is None or not symbol:
            return ()

        event_id = update.event_id or _fallback_event_id(update, timestamp)
        if not self._remember_event(symbol, event_id):
            return ()

        was_disconnected = symbol in self._needs_gap
        volume_delta = self._volume_delta(update, symbol, was_disconnected)
        if was_disconnected:
            self._needs_gap.discard(symbol)

        bucket_timestamp = timestamp.replace(second=0, microsecond=0)
        session = _xtai_session(timestamp)
        by_timestamp = self._buckets.setdefault(symbol, {})
        current = self._current.get(symbol)
        emitted: list[IntradayBucket] = []
        gap = was_disconnected

        if current is not None and bucket_timestamp > current.timestamp:
            current.status = "completed"
            emitted.append(current)
            if (
                bucket_timestamp > current.timestamp + timedelta(minutes=1)
                and current.session == session
                and current.timestamp.date() == bucket_timestamp.date()
            ):
                gap = True

        bucket = by_timestamp.get(bucket_timestamp)
        if bucket is None:
            bucket = IntradayBucket(
                symbol=symbol,
                timestamp=bucket_timestamp,
                open=float(price),
                high=float(price),
                low=float(price),
                close=float(price),
                volume=volume_delta,
                session=session,
                gap=gap,
                first_event_at=timestamp,
            )
            by_timestamp[bucket_timestamp] = bucket
        else:
            if timestamp < bucket.first_event_at:
                bucket.first_event_at = timestamp
                bucket.open = float(price)
            bucket.high = max(bucket.high, float(price))
            bucket.low = min(bucket.low, float(price))
            bucket.close = float(price)
            bucket.volume += volume_delta
            if gap:
                bucket.gap = True

        self._current[symbol] = bucket
        for old_timestamp in tuple(by_timestamp):
            if old_timestamp.date() < bucket_timestamp.date():
                del by_timestamp[old_timestamp]
        emitted.append(bucket)
        self._publish(symbol, emitted)
        return tuple(emitted)

    def mark_disconnected(self, symbols: tuple[str, ...] | list[str] | None = None) -> None:
        """Remember that the next real event follows an upstream gap."""
        targets = symbols or tuple(set(self._current) | set(self._last_total_volume))
        self._needs_gap.update(symbol.strip().upper() for symbol in targets if symbol.strip())

    def current(self, symbol: str) -> IntradayBucket | None:
        """Return the current forming bucket for one symbol, if any."""
        return self._current.get(symbol.strip().upper())

    def bars(self, symbol: str | None = None) -> list[IntradayBucket]:
        """Return observed buckets in timestamp order without filling gaps."""
        symbols = [symbol.strip().upper()] if symbol is not None else sorted(self._buckets)
        return [
            bucket
            for current_symbol in symbols
            for bucket in sorted(self._buckets.get(current_symbol, {}).values(), key=lambda item: item.timestamp)
        ]

    def _volume_delta(
        self,
        update: ShioajiQuoteUpdate,
        symbol: str,
        was_disconnected: bool,
    ) -> int:
        tick_volume = max(0, int(update.tick_volume or 0))
        total_volume = update.total_volume
        if total_volume is None:
            return tick_volume

        total_volume = max(0, int(total_volume))
        previous = self._last_total_volume.get(symbol)
        self._last_total_volume[symbol] = total_volume
        if was_disconnected or previous is None or total_volume < previous:
            return tick_volume
        return max(0, total_volume - previous)

    def _remember_event(self, symbol: str, event_id: str) -> bool:
        seen = self._seen_event_sets.setdefault(symbol, set())
        if event_id in seen:
            return False
        seen.add(event_id)
        ordered = self._seen_event_ids.setdefault(symbol, deque())
        ordered.append(event_id)
        if len(ordered) > self._max_seen_events:
            seen.discard(ordered.popleft())
        return True

    def _publish(self, symbol: str, buckets: list[IntradayBucket]) -> None:
        for bucket in buckets:
            update = IntradayUpdate(symbol=symbol, bar=bucket.as_bar())
            for queue in tuple(self._listeners):
                if queue.full():
                    queue.get_nowait()
                queue.put_nowait(update)


def _as_taipei(timestamp: datetime | None) -> datetime | None:
    if timestamp is None:
        return None
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=TAIPEI)
    return timestamp.astimezone(TAIPEI)


def _xtai_session(timestamp: datetime) -> Session:
    local_time = timestamp.astimezone(TAIPEI).time()
    if local_time < time(9, 0):
        return Session.PRE
    if local_time >= time(13, 30):
        return Session.POST
    return Session.REGULAR


def _fallback_event_id(update: ShioajiQuoteUpdate, timestamp: datetime) -> str:
    return "|".join(
        (
            update.symbol.strip().upper(),
            timestamp.isoformat(),
            repr(update.quote.price),
            repr(update.tick_volume),
            repr(update.total_volume),
        )
    )


__all__ = [
    "IntradayAggregator",
    "IntradayBucket",
    "IntradayBucketStatus",
    "IntradayUpdate",
]
