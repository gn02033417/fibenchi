"""Typed Quote subscription and SSE ingestion for the Shioaji sidecar."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date as Date
from datetime import datetime as DateTime
from datetime import time as Time
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, StrictStr, TypeAdapter, ValidationError

from app.config import settings
from app.models.symbol_directory import TAIWAN_EXCHANGES
from app.schemas.quote import Quote
from app.services.shioaji.client import (
    ShioajiHTTPError,
    ShioajiPayloadError,
    ShioajiTimeoutError,
    ShioajiUnavailableError,
)

TAIPEI = ZoneInfo("Asia/Taipei")


@dataclass(frozen=True, slots=True)
class ShioajiQuoteSubscription:
    """One Quote-only Taiwan stock subscription at the sidecar boundary."""

    code: str
    exchange: str
    security_type: str = "STK"
    quote_type: str = "Quote"

    def __post_init__(self) -> None:
        code = str(self.code).strip().upper()
        exchange = str(self.exchange).strip().upper()
        if not code:
            raise ValueError("Shioaji subscription code is required")
        if exchange not in TAIWAN_EXCHANGES:
            raise ValueError(f"Unsupported Taiwan exchange: {exchange}")
        if self.security_type != "STK":
            raise ValueError("Only STK subscriptions are supported")
        if self.quote_type != "Quote":
            raise ValueError("Only Quote subscriptions are supported")
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "exchange", exchange)

    def payload(self) -> dict[str, str]:
        return {
            "security_type": self.security_type,
            "exchange": self.exchange,
            "code": self.code,
            "quote_type": self.quote_type,
        }


class ShioajiQuoteEvent(BaseModel):
    """The fields from a ``quote_stk`` SSE event needed by Fibenchi."""

    code: StrictStr
    exchange: StrictStr
    datetime: DateTime | None = None
    date: Date | None = None
    time: Time | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    previous_close: float | None = None
    reference: float | None = None
    price_chg: float | None = None
    pct_chg: float | None = None
    volume: int | float | None = None
    total_volume: int | float | None = None
    bid_price: list[float | None] = Field(default_factory=list)
    bid_volume: list[int | float | None] = Field(default_factory=list)
    ask_price: list[float | None] = Field(default_factory=list)
    ask_volume: list[int | float | None] = Field(default_factory=list)
    market_state: str | None = None
    session_state: str | None = None

    model_config = ConfigDict(extra="ignore")


@dataclass(frozen=True, slots=True)
class ShioajiQuoteUpdate:
    """One normalized quote plus the raw trade-volume semantics.

    Shioaji's ``volume`` is the volume of this tick while ``total_volume`` is
    cumulative from the market open.  The public ``Quote`` contract keeps the
    cumulative value for the quote UI; the intraday aggregator consumes both
    values through this internal adapter so a reconnect cannot turn an
    unknown cumulative jump into fabricated minute volume.
    """

    quote: Quote
    timestamp: DateTime | None = None
    tick_volume: int | None = None
    total_volume: int | None = None
    event_id: str = ""

    @property
    def symbol(self) -> str:
        return self.quote.symbol

    @classmethod
    def from_quote(cls, quote: Quote) -> "ShioajiQuoteUpdate":
        timestamp = quote.updated_at
        event_id = _event_identity(
            symbol=quote.symbol,
            timestamp=timestamp,
            price=quote.price,
            tick_volume=None,
            total_volume=quote.volume,
        )
        return cls(
            quote=quote,
            timestamp=timestamp,
            tick_volume=None,
            total_volume=quote.volume,
            event_id=event_id,
        )


def _event_timestamp(event: ShioajiQuoteEvent) -> DateTime | None:
    if event.datetime is not None:
        if event.datetime.tzinfo is None:
            return event.datetime.replace(tzinfo=TAIPEI)
        return event.datetime.astimezone(TAIPEI)
    if event.date is not None and event.time is not None:
        return DateTime.combine(event.date, event.time, tzinfo=TAIPEI)
    return None


def _as_int(value: int | float | None) -> int | None:
    return int(value) if value is not None else None


def _first(values: list[Any]) -> Any | None:
    return next((value for value in values if value is not None), None)


def _event_identity(
    *,
    symbol: str,
    timestamp: DateTime | None,
    price: float | None,
    tick_volume: int | None,
    total_volume: int | None,
) -> str:
    return "|".join(
        (
            symbol.strip().upper(),
            timestamp.isoformat() if timestamp is not None else "",
            repr(price),
            repr(tick_volume),
            repr(total_volume),
        )
    )


def _map_quote_event(event: ShioajiQuoteEvent) -> Quote:
    """Normalize one live Shioaji Quote event into Fibenchi's contract."""
    updated_at = _event_timestamp(event)
    previous_close = event.previous_close if event.previous_close is not None else event.reference
    if previous_close is None and event.close is not None and event.price_chg is not None:
        previous_close = event.close - event.price_chg

    change = event.price_chg
    if change is None and event.close is not None and previous_close is not None:
        change = event.close - previous_close

    change_percent = None
    if change is not None and previous_close not in (None, 0):
        change_percent = change / previous_close * 100

    return Quote(
        symbol=event.code,
        price=event.close,
        previous_close=previous_close,
        change=change,
        change_percent=change_percent,
        volume=_as_int(event.total_volume if event.total_volume is not None else event.volume),
        currency="TWD",
        market_state=event.market_state or event.session_state or "REGULAR",
        open=event.open,
        high=event.high,
        low=event.low,
        bid=_first(event.bid_price),
        bid_volume=_as_int(_first(event.bid_volume)),
        ask=_first(event.ask_price),
        ask_volume=_as_int(_first(event.ask_volume)),
        data_status="LIVE",
        updated_at=updated_at,
        session_date=(
            updated_at.date().isoformat()
            if updated_at is not None
            else event.date.isoformat() if event.date is not None else None
        ),
    )


def map_quote_event_to_update(event: ShioajiQuoteEvent) -> ShioajiQuoteUpdate:
    """Keep the raw tick and cumulative volume alongside the public Quote."""
    quote = _map_quote_event(event)
    timestamp = quote.updated_at
    tick_volume = _as_int(event.volume)
    total_volume = _as_int(event.total_volume)
    return ShioajiQuoteUpdate(
        quote=quote,
        timestamp=timestamp,
        tick_volume=tick_volume,
        total_volume=total_volume,
        event_id=_event_identity(
            symbol=event.code,
            timestamp=timestamp,
            price=event.close,
            tick_volume=tick_volume,
            total_volume=total_volume,
        ),
    )


def map_quote_event_to_quote(event: ShioajiQuoteEvent) -> Quote:
    """Backward-compatible public mapper for the normalized Quote contract."""
    return map_quote_event_to_update(event).quote


class ShioajiQuoteStream:
    """One sidecar client for Quote subscription changes and the SSE feed."""

    SUBSCRIBE_PATH = "/api/v1/stream/subscribe"
    UNSUBSCRIBE_PATH = "/api/v1/stream/unsubscribe"
    QUOTE_STREAM_PATH = "/api/v1/stream/data/quote_stk"

    def __init__(
        self,
        base_url: str | AnyHttpUrl | None = None,
        *,
        timeout: float | httpx.Timeout | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        raw_base_url = base_url or settings.shioaji_base_url
        try:
            self.base_url: AnyHttpUrl = TypeAdapter(AnyHttpUrl).validate_python(raw_base_url)
        except ValidationError as exc:
            raise ValueError("SHIOAJI_BASE_URL must be a valid HTTP(S) URL") from exc

        raw_timeout = timeout if timeout is not None else settings.shioaji_timeout_seconds
        if isinstance(raw_timeout, httpx.Timeout):
            self.timeout = raw_timeout
        else:
            if raw_timeout <= 0:
                raise ValueError("Shioaji timeout must be greater than zero")
            self.timeout = httpx.Timeout(raw_timeout)
        self._transport = transport

    async def subscribe(self, subscription: ShioajiQuoteSubscription) -> None:
        await self._post(self.SUBSCRIBE_PATH, subscription.payload())

    async def unsubscribe(self, subscription: ShioajiQuoteSubscription) -> None:
        await self._post(self.UNSUBSCRIBE_PATH, subscription.payload())

    async def quote_updates(self) -> AsyncIterator[ShioajiQuoteUpdate]:
        """Yield normalized quote updates from one upstream SSE connection."""
        try:
            async with httpx.AsyncClient(
                base_url=str(self.base_url),
                timeout=self.timeout,
                transport=self._transport,
            ) as client:
                async with client.stream("GET", self.QUOTE_STREAM_PATH) as response:
                    if response.is_error:
                        raise ShioajiHTTPError(response.status_code, self.QUOTE_STREAM_PATH)

                    event_name: str | None = None
                    data_lines: list[str] = []
                    async for line in response.aiter_lines():
                        if not line:
                            update = self._decode_quote_update(event_name, data_lines)
                            if update is not None:
                                yield update
                            event_name = None
                            data_lines = []
                            continue
                        if line.startswith(":"):
                            continue
                        field, _, value = line.partition(":")
                        if value.startswith(" "):
                            value = value[1:]
                        if field == "event":
                            event_name = value
                        elif field == "data":
                            data_lines.append(value)

                    update = self._decode_quote_update(event_name, data_lines)
                    if update is not None:
                        yield update
        except httpx.TimeoutException as exc:
            raise ShioajiTimeoutError(
                f"Shioaji sidecar timed out for {self.QUOTE_STREAM_PATH}"
            ) from exc
        except httpx.RequestError as exc:
            raise ShioajiUnavailableError(
                f"Shioaji sidecar unavailable for {self.QUOTE_STREAM_PATH}"
            ) from exc

    async def quote_events(self) -> AsyncIterator[Quote]:
        """Yield only the public Quote portion of each live update."""
        async for update in self.quote_updates():
            yield update.quote

    async def _post(self, path: str, payload: dict[str, str]) -> None:
        try:
            async with httpx.AsyncClient(
                base_url=str(self.base_url),
                timeout=self.timeout,
                transport=self._transport,
            ) as client:
                response = await client.post(path, json=payload)
        except httpx.TimeoutException as exc:
            raise ShioajiTimeoutError(f"Shioaji sidecar timed out for {path}") from exc
        except httpx.RequestError as exc:
            raise ShioajiUnavailableError(f"Shioaji sidecar unavailable for {path}") from exc

        if response.is_error:
            raise ShioajiHTTPError(response.status_code, path)

    @classmethod
    def _decode_quote_event(
        cls,
        event_name: str | None,
        data_lines: list[str],
    ) -> Quote | None:
        update = cls._decode_quote_update(event_name, data_lines)
        return update.quote if update is not None else None

    @classmethod
    def _decode_quote_update(
        cls,
        event_name: str | None,
        data_lines: list[str],
    ) -> ShioajiQuoteUpdate | None:
        if event_name != "quote_stk" or not data_lines:
            return None
        try:
            payload = json.loads("\n".join(data_lines))
            event = ShioajiQuoteEvent.model_validate(payload)
        except (ValueError, ValidationError) as exc:
            raise ShioajiPayloadError(cls.QUOTE_STREAM_PATH, exc) from exc
        return map_quote_event_to_update(event)


__all__ = [
    "ShioajiQuoteEvent",
    "ShioajiQuoteUpdate",
    "ShioajiQuoteStream",
    "ShioajiQuoteSubscription",
    "map_quote_event_to_update",
    "map_quote_event_to_quote",
]
