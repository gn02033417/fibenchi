"""Wire models for intraday bars (the SSE ``intraday`` event).

There is no REST endpoint for intraday bars — the quote stream is the only
egress. The payload is ``{symbol: [IntradayBar, ...]}``; the frontend mirror
is ``IntradayPoint`` in ``frontend/src/lib/types.ts``.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.domain.phases import Session

IntradayBarStatus = Literal["forming", "completed"]


class IntradayBar(BaseModel):
    """One 1-minute bar stored in the DB or pushed over SSE.

    ``price`` remains the chart-compatible close alias used by the existing
    frontend.  The optional OHLC fields and ``status`` make live aggregation
    explicit without requiring the chart to understand a new payload shape.
    """

    time: int = Field(description="Bar timestamp as Unix epoch seconds.")
    price: float = Field(description="Close price, currency-normalised.")
    volume: int = Field(description="Bar volume (0 when the feed omits it).")
    session: Session = Field(description="Trading session the bar falls in.")
    open: float | None = Field(default=None, description="Opening trade price.")
    high: float | None = Field(default=None, description="Highest trade price.")
    low: float | None = Field(default=None, description="Lowest trade price.")
    close: float | None = Field(default=None, description="Closing trade price.")
    status: IntradayBarStatus = Field(
        default="completed",
        description="Whether the current minute is still forming.",
    )
    gap: bool = Field(
        default=False,
        description="True when this bar follows an observed live-feed gap.",
    )
