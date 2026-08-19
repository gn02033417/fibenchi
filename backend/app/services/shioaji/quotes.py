"""Typed Shioaji snapshot models and pure Fibenchi quote mapping."""

from __future__ import annotations

from datetime import datetime as DateTime
from datetime import timezone
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, StrictStr, model_validator

from app.schemas.quote import Quote

TAIPEI = ZoneInfo("Asia/Taipei")


class ShioajiSnapshot(BaseModel):
    """HTTP representation of the official Shioaji stock snapshot."""

    datetime: DateTime | None = None
    ts: int | float | None = None
    code: StrictStr
    exchange: StrictStr
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    change_price: float | None = None
    change_rate: float | None = None
    previous_close: float | None = None
    reference: float | None = None
    average_price: float | None = None
    volume: int | float | None = None
    total_volume: int | float | None = None
    yesterday_volume: int | float | None = None
    buy_price: float | None = None
    buy_volume: int | float | None = None
    sell_price: float | None = None
    sell_volume: int | float | None = None
    market_state: str | None = None
    session_state: str | None = None

    model_config = ConfigDict(extra="ignore")


class ShioajiSnapshotsResponse(BaseModel):
    snapshots: list[ShioajiSnapshot]

    model_config = ConfigDict(extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def accept_snapshot_list(cls, value):
        if isinstance(value, list):
            return {"snapshots": value}
        return value


def _snapshot_timestamp(snapshot: ShioajiSnapshot) -> DateTime | None:
    """Return an explicit Taiwan-local timestamp from HTTP ``datetime``/``ts``."""
    value = snapshot.datetime
    if value is not None:
        if value.tzinfo is None:
            return value.replace(tzinfo=TAIPEI)
        return value.astimezone(TAIPEI)

    if snapshot.ts is None:
        return None

    raw = float(snapshot.ts)
    if abs(raw) >= 1e14:
        raw /= 1_000_000_000
    elif abs(raw) >= 1e11:
        raw /= 1_000
    try:
        return DateTime.fromtimestamp(raw, tz=timezone.utc).astimezone(TAIPEI)
    except (OverflowError, OSError, ValueError):
        return None


def _as_int(value: int | float | None) -> int | None:
    return int(value) if value is not None else None


def map_snapshot_to_quote(snapshot: ShioajiSnapshot) -> Quote:
    """Map one Shioaji stock snapshot without claiming it is a live stream."""
    updated_at = _snapshot_timestamp(snapshot)
    if snapshot.close is None:
        return Quote.placeholder(snapshot.code, currency="TWD")

    previous_close = (
        snapshot.previous_close
        if snapshot.previous_close is not None
        else snapshot.reference
    )
    if previous_close is None and snapshot.change_price is not None:
        previous_close = snapshot.close - snapshot.change_price

    change = snapshot.change_price
    if change is None and previous_close is not None:
        change = snapshot.close - previous_close

    change_percent = snapshot.change_rate
    if change_percent is None and change is not None and previous_close:
        change_percent = change / previous_close * 100

    return Quote(
        symbol=snapshot.code,
        price=snapshot.close,
        previous_close=previous_close,
        change=change,
        change_percent=change_percent,
        volume=_as_int(
            snapshot.total_volume
            if snapshot.total_volume is not None
            else snapshot.volume
        ),
        avg_volume=None,
        currency="TWD",
        market_state=snapshot.market_state or snapshot.session_state,
        open=snapshot.open,
        high=snapshot.high,
        low=snapshot.low,
        bid=snapshot.buy_price,
        bid_volume=_as_int(snapshot.buy_volume),
        ask=snapshot.sell_price,
        ask_volume=_as_int(snapshot.sell_volume),
        # The official endpoint documents snapshots as request-type queries,
        # not real-time quote subscriptions. Only future stream events may be
        # promoted to LIVE by the realtime state layer.
        data_status="CACHED" if updated_at is not None else "DISCONNECTED",
        updated_at=updated_at,
        session_date=updated_at.date().isoformat() if updated_at else None,
    )


__all__ = [
    "ShioajiSnapshot",
    "ShioajiSnapshotsResponse",
    "map_snapshot_to_quote",
]
