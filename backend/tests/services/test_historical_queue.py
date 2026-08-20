"""Offline unit tests for bounded, de-duplicated Kbars requests."""

import asyncio
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.domain.assetref import AssetRef
from app.services.historical_queue import HistoricalDataQueue, HistoricalDataQueueError
from app.services.shioaji.client import ShioajiTimeoutError, ShioajiUnavailableError
from app.services.shioaji.kbars import MinuteBar

TAIPEI = ZoneInfo("Asia/Taipei")


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


class RecordingKbarsClient:
    def __init__(self):
        self.calls: list[tuple[dict[str, str], date, date]] = []

    async def kbars(
        self,
        contract: dict[str, str],
        *,
        start: date,
        end: date,
    ) -> list[MinuteBar]:
        self.calls.append((dict(contract), start, end))
        return []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("start", "end", "expected_ranges"),
    [
        (date(2026, 1, 1), date(2026, 1, 30), [(date(2026, 1, 1), date(2026, 1, 30))]),
        (
            date(2026, 1, 1),
            date(2026, 1, 31),
            [(date(2026, 1, 1), date(2026, 1, 30)), (date(2026, 1, 31), date(2026, 1, 31))],
        ),
        (
            date(2026, 1, 1),
            date(2026, 3, 2),
            [
                (date(2026, 1, 1), date(2026, 1, 30)),
                (date(2026, 1, 31), date(2026, 3, 1)),
                (date(2026, 3, 2), date(2026, 3, 2)),
            ],
        ),
    ],
)
async def test_fetch_splits_inclusive_date_ranges_into_at_most_thirty_days(
    start: date,
    end: date,
    expected_ranges: list[tuple[date, date]],
):
    client = RecordingKbarsClient()
    queue = HistoricalDataQueue(client, min_interval_seconds=0, retry_delays=())

    bars = await queue.fetch(AssetRef("2330", exchange="TSE"), start, end)

    assert bars == []
    assert [(call_start, call_end) for _, call_start, call_end in client.calls] == expected_ranges
    assert all(
        contract == {"security_type": "STK", "exchange": "TSE", "code": "2330"}
        for contract, _, _ in client.calls
    )


@pytest.mark.asyncio
async def test_identical_in_flight_requests_share_one_upstream_job():
    class BlockingKbarsClient:
        def __init__(self):
            self.calls = 0
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def kbars(self, contract, *, start, end) -> list[MinuteBar]:
            self.calls += 1
            self.started.set()
            await self.release.wait()
            return [_bar(start)]

    client = BlockingKbarsClient()
    queue = HistoricalDataQueue(client, min_interval_seconds=0, retry_delays=())
    asset = AssetRef("2330", exchange="TSE")

    first = asyncio.create_task(queue.fetch(asset, date(2026, 5, 18), date(2026, 5, 18)))
    await client.started.wait()
    second = asyncio.create_task(queue.fetch(asset, date(2026, 5, 18), date(2026, 5, 18)))
    await asyncio.sleep(0)

    assert client.calls == 1
    client.release.set()
    first_bars, second_bars = await asyncio.gather(first, second)

    assert first_bars == second_bars == [_bar(date(2026, 5, 18))]
    assert first_bars is not second_bars


@pytest.mark.asyncio
async def test_timeout_is_retried_deterministically_with_the_configured_bound(monkeypatch):
    class FlakyKbarsClient:
        def __init__(self):
            self.calls = 0

        async def kbars(self, contract, *, start, end) -> list[MinuteBar]:
            self.calls += 1
            if self.calls == 1:
                raise ShioajiTimeoutError("sidecar timed out")
            return [_bar(start)]

    requested_timeouts: list[float] = []

    async def no_wait(awaitable, timeout: float):
        requested_timeouts.append(timeout)
        return await awaitable

    retry_sleeps: list[float] = []

    async def record_sleep(delay: float) -> None:
        retry_sleeps.append(delay)

    monkeypatch.setattr("app.services.historical_queue.asyncio.wait_for", no_wait)
    client = FlakyKbarsClient()
    queue = HistoricalDataQueue(
        client,
        min_interval_seconds=0,
        timeout_seconds=7.5,
        retry_delays=(0.125,),
        sleep=record_sleep,
    )

    bars = await queue.fetch(AssetRef("2330", exchange="TSE"), date(2026, 5, 18), date(2026, 5, 18))

    assert bars == [_bar(date(2026, 5, 18))]
    assert client.calls == 2
    assert requested_timeouts == [7.5, 7.5]
    assert retry_sleeps == [0.125]


@pytest.mark.asyncio
async def test_rate_limit_is_shared_between_unrelated_symbol_requests():
    class ManualClock:
        def __init__(self):
            self.value = 0.0
            self.sleeps: list[float] = []

        def now(self) -> float:
            return self.value

        async def sleep(self, delay: float) -> None:
            self.sleeps.append(delay)
            self.value += delay

    clock = ManualClock()
    client = RecordingKbarsClient()
    queue = HistoricalDataQueue(
        client,
        min_interval_seconds=0.5,
        retry_delays=(),
        clock=clock.now,
        sleep=clock.sleep,
    )

    await queue.fetch(AssetRef("2330", exchange="TSE"), date(2026, 5, 18), date(2026, 5, 18))
    await queue.fetch(AssetRef("2317", exchange="TSE"), date(2026, 5, 18), date(2026, 5, 18))

    assert len(client.calls) == 2
    assert clock.sleeps == [0.5]


@pytest.mark.asyncio
async def test_one_symbol_failure_does_not_abort_an_unrelated_request():
    class MixedKbarsClient:
        async def kbars(self, contract, *, start, end) -> list[MinuteBar]:
            if contract["code"] == "2330":
                raise ShioajiUnavailableError("sidecar unavailable")
            return [_bar(start, close=200.0)]

    queue = HistoricalDataQueue(MixedKbarsClient(), min_interval_seconds=0, retry_delays=())
    failed = asyncio.create_task(
        queue.fetch(AssetRef("2330", exchange="TSE"), date(2026, 5, 18), date(2026, 5, 18))
    )
    succeeded = asyncio.create_task(
        queue.fetch(AssetRef("2317", exchange="TSE"), date(2026, 5, 18), date(2026, 5, 18))
    )

    with pytest.raises(HistoricalDataQueueError):
        await failed
    assert await succeeded == [_bar(date(2026, 5, 18), close=200.0)]
