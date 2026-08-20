"""Deterministic tests for the live Taiwan 1-minute intraday aggregator."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.schemas.quote import Quote
from app.services.intraday_aggregator import IntradayAggregator
from app.services.shioaji.stream import ShioajiQuoteUpdate

TAIPEI = ZoneInfo("Asia/Taipei")


def _update(
    when: datetime,
    *,
    price: float,
    tick_volume: int,
    total_volume: int | None,
    event_id: str,
    symbol: str = "2330",
) -> ShioajiQuoteUpdate:
    return ShioajiQuoteUpdate(
        quote=Quote(
            symbol=symbol,
            price=price,
            volume=total_volume,
            currency="TWD",
            data_status="LIVE",
            updated_at=when,
        ),
        timestamp=when,
        tick_volume=tick_volume,
        total_volume=total_volume,
        event_id=event_id,
    )


def test_exact_ohlcv_is_emitted_as_forming_then_completed_minute_bars():
    aggregator = IntradayAggregator()
    events = [
        _update(datetime(2026, 8, 20, 9, 0, 5, tzinfo=TAIPEI), price=100, tick_volume=3, total_volume=3, event_id="a"),
        _update(datetime(2026, 8, 20, 9, 0, 20, tzinfo=TAIPEI), price=101, tick_volume=4, total_volume=7, event_id="b"),
        _update(datetime(2026, 8, 20, 9, 0, 59, tzinfo=TAIPEI), price=99, tick_volume=2, total_volume=9, event_id="c"),
        _update(datetime(2026, 8, 20, 9, 1, tzinfo=TAIPEI), price=102, tick_volume=5, total_volume=14, event_id="d"),
    ]

    emitted = [bar for event in events for bar in aggregator.ingest(event)]
    completed = [bar for bar in emitted if bar.status == "completed"]
    forming = [bar for bar in emitted if bar.status == "forming"]

    assert completed[-1].timestamp == datetime(2026, 8, 20, 9, 0, tzinfo=TAIPEI)
    assert completed[-1].open == 100
    assert completed[-1].high == 101
    assert completed[-1].low == 99
    assert completed[-1].close == 99
    assert completed[-1].volume == 9
    assert forming[-1].timestamp == datetime(2026, 8, 20, 9, 1, tzinfo=TAIPEI)
    assert forming[-1].open == forming[-1].high == forming[-1].low == forming[-1].close == 102
    assert forming[-1].volume == 5


def test_duplicate_quote_event_does_not_inflate_volume():
    aggregator = IntradayAggregator()
    event = _update(
        datetime(2026, 8, 20, 9, 0, tzinfo=TAIPEI),
        price=100,
        tick_volume=4,
        total_volume=4,
        event_id="same-event",
    )

    assert len(aggregator.ingest(event)) == 1
    assert aggregator.ingest(event) == ()
    assert aggregator.current("2330").volume == 4


@pytest.mark.parametrize(
    ("when", "expected"),
    [
        (datetime(2026, 8, 20, 8, 59, tzinfo=TAIPEI), "pre"),
        (datetime(2026, 8, 20, 9, 0, tzinfo=TAIPEI), "regular"),
        (datetime(2026, 8, 20, 13, 29, tzinfo=TAIPEI), "regular"),
        (datetime(2026, 8, 20, 13, 30, tzinfo=TAIPEI), "post"),
    ],
)
def test_xtai_session_boundaries(when: datetime, expected: str):
    aggregator = IntradayAggregator()

    [bar] = aggregator.ingest(
        _update(when, price=100, tick_volume=1, total_volume=1, event_id=when.isoformat())
    )

    assert bar.session == expected


def test_reconnect_gap_is_flagged_without_synthesizing_missing_minutes():
    aggregator = IntradayAggregator()
    first = _update(
        datetime(2026, 8, 20, 9, 0, tzinfo=TAIPEI),
        price=100,
        tick_volume=5,
        total_volume=5,
        event_id="before-disconnect",
    )
    after_reconnect = _update(
        datetime(2026, 8, 20, 9, 3, tzinfo=TAIPEI),
        price=103,
        tick_volume=2,
        total_volume=10,
        event_id="after-reconnect",
    )

    aggregator.ingest(first)
    aggregator.mark_disconnected()
    emitted = aggregator.ingest(after_reconnect)

    assert [bar.timestamp.minute for bar in emitted] == [0, 3]
    assert emitted[-1].gap is True
    # The cumulative-volume jump during the disconnected interval is unknown;
    # only the post-reconnect tick itself is counted.
    assert emitted[-1].volume == 2
    assert aggregator.bars("2330")
    assert all(bar.timestamp.minute not in {1, 2} for bar in aggregator.bars("2330"))
