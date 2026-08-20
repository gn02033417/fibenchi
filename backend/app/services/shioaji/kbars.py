"""Typed Shioaji Kbars models and normalized minute OHLCV values."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime as DateTime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

TAIPEI = ZoneInfo("Asia/Taipei")


@dataclass(frozen=True, slots=True)
class MinuteBar:
    """One normalized Shioaji minute OHLCV observation in Taiwan time."""

    timestamp: DateTime
    open: float
    high: float
    low: float
    close: float
    volume: int
    amount: float


class ShioajiKbarsResponse(BaseModel):
    """The official HTTP Kbars response, kept columnar at the boundary."""

    datetime: list[DateTime]
    open: list[float] = Field(alias="Open")
    high: list[float] = Field(alias="High")
    low: list[float] = Field(alias="Low")
    close: list[float] = Field(alias="Close")
    volume: list[int] = Field(alias="Volume")
    amount: list[float] = Field(alias="Amount")

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    @model_validator(mode="after")
    def has_aligned_columns(self) -> ShioajiKbarsResponse:
        lengths = {
            len(self.datetime),
            len(self.open),
            len(self.high),
            len(self.low),
            len(self.close),
            len(self.volume),
            len(self.amount),
        }
        if len(lengths) != 1:
            raise ValueError("Kbars response columns must have matching lengths")
        return self

    def minute_bars(self) -> list[MinuteBar]:
        """Convert HTTP arrays into timestamp-normalized minute observations."""
        return [
            MinuteBar(
                timestamp=_as_taipei(timestamp),
                open=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                volume=volume,
                amount=amount,
            )
            for (
                timestamp,
                open_price,
                high_price,
                low_price,
                close_price,
                volume,
                amount,
            ) in zip(
                self.datetime,
                self.open,
                self.high,
                self.low,
                self.close,
                self.volume,
                self.amount,
                strict=True,
            )
        ]


def _as_taipei(timestamp: DateTime) -> DateTime:
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=TAIPEI)
    return timestamp.astimezone(TAIPEI)


__all__ = ["MinuteBar", "ShioajiKbarsResponse"]
