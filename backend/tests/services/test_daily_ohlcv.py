"""Pure aggregation tests for settled Taiwan daily OHLCV."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.services.daily_ohlcv import aggregate_daily_ohlcv
from app.services.shioaji.kbars import MinuteBar

TAIPEI = ZoneInfo("Asia/Taipei")


class FixtureVenue:
    def __init__(self, sessions: set[date]):
        self.sessions = sessions

    def local_date(self, at: datetime) -> date:
        return at.astimezone(TAIPEI).date()

    def session_dates(self, start: date, end: date) -> set[date]:
        return {session for session in self.sessions if start <= session <= end}


def _bar(day: date, minute: int, *, open: float, high: float, low: float, close: float, volume: int) -> MinuteBar:
    return MinuteBar(
        timestamp=datetime(day.year, day.month, day.day, 9, minute, tzinfo=TAIPEI),
        open=open,
        high=high,
        low=low,
        close=close,
        volume=volume,
        amount=close * volume,
    )


def test_aggregate_daily_ohlcv_produces_exact_open_high_low_close_and_volume():
    session = date(2025, 1, 2)
    venue = FixtureVenue({session})
    minute_bars = [
        _bar(session, 3, open=103, high=106, low=102, close=105, volume=30),
        _bar(session, 1, open=100, high=102, low=99, close=101, volume=10),
        _bar(session, 2, open=101, high=104, low=100, close=103, volume=20),
    ]

    daily = aggregate_daily_ohlcv(minute_bars, venue)

    assert list(daily.index) == [session]
    assert daily.loc[session].to_dict() == {
        "open": 100.0,
        "high": 106.0,
        "low": 99.0,
        "close": 105.0,
        "volume": 60.0,
    }


def test_aggregate_daily_ohlcv_ignores_bars_outside_venue_sessions():
    session = date(2025, 1, 2)
    venue = FixtureVenue({session})
    daily = aggregate_daily_ohlcv(
        [
            _bar(date(2025, 1, 1), 1, open=1, high=1, low=1, close=1, volume=1),
            _bar(session, 1, open=100, high=102, low=99, close=101, volume=10),
        ],
        venue,
    )

    assert list(daily.index) == [session]
    assert daily.loc[session, "close"] == 101.0
