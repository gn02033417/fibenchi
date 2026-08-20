"""Offline Taiwan settled-price sync tests."""

from datetime import date, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.constants import PERIOD_DAYS, WARMUP_DAYS
from app.domain import AssetRef
from app.models import Asset, AssetType
from app.services.price_sync import sync_all_prices, sync_asset_prices, sync_asset_prices_range
from app.services.shioaji.kbars import MinuteBar

TAIPEI = ZoneInfo("Asia/Taipei")
AFTER_CLOSE = datetime(2025, 1, 3, 16, tzinfo=TAIPEI)


def _bar(day: date, *, close: float = 100.0) -> MinuteBar:
    return MinuteBar(
        timestamp=datetime(day.year, day.month, day.day, 9, 1, tzinfo=TAIPEI),
        open=close - 1,
        high=close + 1,
        low=close - 2,
        close=close,
        volume=100,
        amount=close * 100,
    )


class FakeHistoricalQueue:
    def __init__(self, responses: dict[str, list[MinuteBar] | Exception]):
        self.responses = responses
        self.calls: list[tuple[AssetRef, date, date]] = []

    async def fetch(self, asset: AssetRef, start: date, end: date) -> list[MinuteBar]:
        self.calls.append((asset, start, end))
        response = self.responses[str(asset)]
        if isinstance(response, Exception):
            raise response
        return response


class FakePriceRepository:
    def __init__(self, stored_dates: dict[int, set[date]] | None = None):
        self.stored_dates = stored_dates or {}
        self.upserted = []

    async def get_dates_for_asset_between(self, asset_id: int, start: date, end: date) -> set[date]:
        return {
            stored
            for stored in self.stored_dates.get(asset_id, set())
            if start <= stored <= end
        }

    async def upsert_prices(self, ref: AssetRef, frame) -> int:
        self.upserted.append((ref, frame.copy()))
        dates = {
            index.date() if hasattr(index, "date") else index
            for index in frame.index
        }
        self.stored_dates.setdefault(ref.id, set()).update(dates)
        return len(frame)


@pytest.mark.asyncio
async def test_initial_taiwan_sync_requests_at_least_one_year_plus_warmup(db):
    ref = AssetRef("2330", 1, exchange="TSE")
    queue = FakeHistoricalQueue({"2330": []})
    repo = FakePriceRepository()

    with patch("app.services.price_sync.PriceRepository", return_value=repo):
        await sync_asset_prices(
            db,
            ref,
            period="3mo",
            historical_queue=queue,
            as_of=AFTER_CLOSE,
        )

    _, start, end = queue.calls[0]
    expected_days = PERIOD_DAYS["1y"] + WARMUP_DAYS
    assert end - start >= timedelta(days=expected_days - 7)


@pytest.mark.asyncio
async def test_taiwan_range_sync_aggregates_and_persists_only_settled_daily_bar(db):
    ref = AssetRef("2330", 1, exchange="TSE")
    queue = FakeHistoricalQueue(
        {
            "2330": [
                _bar(date(2025, 1, 2), close=100.0),
                _bar(date(2025, 1, 2), close=103.0),
            ]
        }
    )
    repo = FakePriceRepository()

    with patch("app.services.price_sync.PriceRepository", return_value=repo), patch(
        "app.services.price_sync.invalidate_indicator_cache"
    ) as invalidate:
        count = await sync_asset_prices_range(
            db,
            ref,
            date(2025, 1, 2),
            date(2025, 1, 2),
            historical_queue=queue,
            as_of=AFTER_CLOSE,
        )

    assert count == 1
    assert [(str(asset), start, end) for asset, start, end in queue.calls] == [
        ("2330", date(2025, 1, 2), date(2025, 1, 2))
    ]
    frame = repo.upserted[0][1]
    assert frame.loc[date(2025, 1, 2)].to_dict() == {
        "open": 99.0,
        "high": 104.0,
        "low": 98.0,
        "close": 103.0,
        "volume": 200.0,
    }
    invalidate.assert_called_once()


@pytest.mark.asyncio
async def test_open_xtai_session_is_not_requested_or_persisted(db):
    ref = AssetRef("2330", 1, exchange="TSE")
    queue = FakeHistoricalQueue({"2330": [_bar(date(2025, 1, 2))]})
    repo = FakePriceRepository()

    with patch("app.services.price_sync.PriceRepository", return_value=repo), patch(
        "app.services.price_sync.invalidate_indicator_cache"
    ) as invalidate:
        count = await sync_asset_prices_range(
            db,
            ref,
            date(2025, 1, 2),
            date(2025, 1, 2),
            historical_queue=queue,
            as_of=datetime(2025, 1, 2, 10, tzinfo=TAIPEI),
        )

    assert count == 0
    assert queue.calls == []
    assert repo.upserted == []
    invalidate.assert_not_called()


@pytest.mark.asyncio
async def test_closed_xtai_session_is_eligible_for_settled_persistence(db):
    ref = AssetRef("2330", 1, exchange="TSE")
    session = date(2025, 1, 3)
    queue = FakeHistoricalQueue({"2330": [_bar(session)]})
    repo = FakePriceRepository()

    with patch("app.services.price_sync.PriceRepository", return_value=repo), patch(
        "app.services.price_sync.invalidate_indicator_cache"
    ) as invalidate:
        count = await sync_asset_prices_range(
            db,
            ref,
            session,
            session,
            historical_queue=queue,
            as_of=AFTER_CLOSE,
        )

    assert count == 1
    assert [(start, end) for _, start, end in queue.calls] == [(session, session)]
    invalidate.assert_called_once()


@pytest.mark.asyncio
async def test_repeated_taiwan_sync_with_no_missing_sessions_skips_history(db):
    ref = AssetRef("2330", 1, exchange="TSE")
    queue = FakeHistoricalQueue({"2330": [_bar(date(2025, 1, 2))]})
    repo = FakePriceRepository({1: {date(2025, 1, 2)}})

    with patch("app.services.price_sync.PriceRepository", return_value=repo), patch(
        "app.services.price_sync.invalidate_indicator_cache"
    ) as invalidate:
        count = await sync_asset_prices_range(
            db,
            ref,
            date(2025, 1, 2),
            date(2025, 1, 2),
            historical_queue=queue,
            as_of=AFTER_CLOSE,
        )

    assert count == 0
    assert queue.calls == []
    assert invalidate.call_count == 0


@pytest.mark.asyncio
async def test_taiwan_batch_isolates_one_symbol_failure(db):
    bad = Asset(symbol="2330", name="Bad", type=AssetType.STOCK, exchange="TSE", currency="TWD")
    good = Asset(symbol="2317", name="Good", type=AssetType.STOCK, exchange="TSE", currency="TWD")
    db.add_all([bad, good])
    await db.commit()

    queue = FakeHistoricalQueue(
        {
            "2330": RuntimeError("fixture failure"),
            "2317": [_bar(date(2025, 1, 2), close=200.0)],
        }
    )
    repo = FakePriceRepository()

    with patch("app.services.price_sync.PriceRepository", return_value=repo), patch(
        "app.services.price_sync.invalidate_indicator_cache"
    ) as invalidate:
        counts = await sync_all_prices(
            db,
            historical_queue=queue,
            as_of=AFTER_CLOSE,
        )

    assert counts == {"2317": 1}
    assert {str(asset) for asset, _, _ in queue.calls} == {"2330", "2317"}
    invalidate.assert_called_once()
