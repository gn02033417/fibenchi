"""Pure XTAI minute-to-daily aggregation and settled-session helpers."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime

import pandas as pd

from app.services.shioaji.kbars import MinuteBar

_DAILY_COLUMNS = ["open", "high", "low", "close", "volume"]


def aggregate_daily_ohlcv(minute_bars: Sequence[MinuteBar], venue) -> pd.DataFrame:
    """Aggregate valid venue-session minute bars into daily OHLCV rows.

    This function has no database or sidecar dependency.  It filters input to
    dates the supplied venue identifies as sessions, then uses timestamp order
    for the daily open/close and sums minute volume.
    """
    if not minute_bars:
        return _empty_daily_frame()

    buckets: dict[date, list[MinuteBar]] = defaultdict(list)
    for bar in sorted(minute_bars, key=lambda item: item.timestamp):
        session_date = venue.local_date(bar.timestamp)
        if session_date is None:
            raise ValueError("Unable to map a minute bar timestamp to a venue-local date")
        buckets[session_date].append(bar)

    session_dates = venue.session_dates(min(buckets), max(buckets))
    if session_dates is None:
        raise ValueError("Unable to determine venue sessions for Kbars aggregation")

    rows: list[dict[str, float | int | date]] = []
    for session_date in sorted(session_dates & buckets.keys()):
        bars = buckets[session_date]
        rows.append(
            {
                "date": session_date,
                "open": bars[0].open,
                "high": max(bar.high for bar in bars),
                "low": min(bar.low for bar in bars),
                "close": bars[-1].close,
                "volume": sum(bar.volume for bar in bars),
            }
        )

    if not rows:
        return _empty_daily_frame()
    return pd.DataFrame(rows).set_index("date")[_DAILY_COLUMNS]


def completed_session_dates(
    venue,
    start: date,
    end: date,
    *,
    as_of: datetime | None = None,
) -> set[date]:
    """Return sessions known to be complete at ``as_of`` (or now).

    The active venue-local session is excluded during both pre-open and regular
    trading.  After its close, ``next_open`` belongs to a later local date and
    the session becomes eligible for settled-history persistence.
    """
    sessions = venue.session_dates(start, end)
    if sessions is None:
        raise ValueError("Unable to determine venue sessions for settled-price sync")

    completed = set(sessions)
    current_date = venue.local_date(as_of)
    if current_date not in completed:
        return completed

    if venue.is_open(as_of) is True:
        completed.discard(current_date)
        return completed

    next_open = venue.next_open(as_of)
    if next_open is None or venue.local_date(next_open) == current_date:
        completed.discard(current_date)
    return completed


def missing_session_ranges(
    sessions: set[date],
    stored_dates: set[date],
) -> list[tuple[date, date]]:
    """Coalesce missing sessions into inclusive Kbars request ranges."""
    ranges: list[tuple[date, date]] = []
    range_start: date | None = None
    range_end: date | None = None

    for session in sorted(sessions):
        if session not in stored_dates:
            if range_start is None:
                range_start = session
            range_end = session
            continue
        if range_start is not None and range_end is not None:
            ranges.append((range_start, range_end))
            range_start = None
            range_end = None

    if range_start is not None and range_end is not None:
        ranges.append((range_start, range_end))
    return ranges


def _empty_daily_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=_DAILY_COLUMNS, index=pd.Index([], name="date"))


__all__ = ["aggregate_daily_ohlcv", "completed_session_dates", "missing_session_ranges"]
