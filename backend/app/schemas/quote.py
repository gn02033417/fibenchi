from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

QuoteDataStatus = Literal["LIVE", "CACHED", "DISCONNECTED"]


class QuoteResponse(BaseModel):
    symbol: str = Field(description="Ticker symbol (e.g. AAPL)")
    price: float | None = Field(default=None, description="Latest traded price")
    previous_close: float | None = Field(default=None, description="Previous session close price")
    change: float | None = Field(default=None, description="Absolute price change from previous close")
    change_percent: float | None = Field(default=None, description="Percentage change from previous close")
    volume: int | None = Field(default=None, description="Current session trading volume")
    avg_volume: int | None = Field(default=None, description="10-day average daily volume")
    currency: str = Field(default="USD", description="ISO 4217 currency code")
    market_state: str | None = Field(
        default=None,
        description="Provider session state when the source exposes one",
    )
    open: float | None = Field(default=None, description="Session open price")
    high: float | None = Field(default=None, description="Session high price")
    low: float | None = Field(default=None, description="Session low price")
    bid: float | None = Field(default=None, description="Best bid price")
    bid_volume: int | None = Field(default=None, description="Best bid volume")
    ask: float | None = Field(default=None, description="Best ask price")
    ask_volume: int | None = Field(default=None, description="Best ask volume")
    data_status: QuoteDataStatus | None = Field(
        default=None,
        description="Freshness state: LIVE, CACHED, or DISCONNECTED",
    )
    updated_at: datetime | None = Field(
        default=None,
        description="Provider timestamp for the latest known quote",
    )


class Quote(QuoteResponse):
    """The full provider quote used by price sync and the SSE boundary.

    :class:`QuoteResponse` plus the internal reconciliation field — this is
    what circulates through the app (price-sync anchors, price heal, the SSE
    ``quotes`` event, ``SymbolBatchData.quote``). The REST ``GET /api/quotes``
    boundary re-validates into plain ``QuoteResponse``, dropping
    ``session_date``.

    ``market_state`` stays a raw string on purpose: providers may expose
    different session vocabularies, and unknown values degrade conservatively
    in the market-state domain helpers.
    """

    session_date: str | None = Field(
        default=None,
        description="Exchange-local ISO date of the quote's live session; "
        "internal aid for price-sync's settled-bar reconciliation.",
    )

    @classmethod
    def placeholder(
        cls,
        symbol: str,
        *,
        currency: str = "USD",
        data_status: QuoteDataStatus = "DISCONNECTED",
    ) -> "Quote":
        """Placeholder for a degraded fetch, with explicit freshness state."""
        return cls(symbol=symbol, currency=currency, data_status=data_status)

    @property
    def is_placeholder(self) -> bool:
        """True when the quote carries no market values beyond its symbol."""
        return all(
            value is None
            for value in (
                self.price,
                self.previous_close,
                self.change,
                self.change_percent,
                self.volume,
                self.open,
                self.high,
                self.low,
                self.bid,
                self.ask,
            )
        )
