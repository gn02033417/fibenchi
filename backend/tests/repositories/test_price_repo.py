"""Tests for PriceRepository — date-range queries and aggregations against real SQLite DB."""

from datetime import date, timedelta

import pandas as pd
import pytest

from app.domain import AssetRef
from app.models import PriceHistory
from app.repositories.price_repo import PriceRepository
from tests.helpers import create_test_asset as _create_asset

pytestmark = pytest.mark.asyncio(loop_scope="function")


async def _seed_prices(db, asset_id: int, n_days: int = 30, base_price: float = 100.0) -> list[PriceHistory]:
    today = date.today()
    prices = []
    for i in range(n_days):
        d = today - timedelta(days=n_days - 1 - i)
        if d.weekday() >= 5:
            continue
        price = base_price + i * 0.5
        p = PriceHistory(
            asset_id=asset_id, date=d,
            open=round(price - 0.5, 4), high=round(price + 1.0, 4),
            low=round(price - 1.0, 4), close=round(price, 4),
            volume=1_000_000,
        )
        db.add(p)
        prices.append(p)
    await db.commit()
    return prices


async def test_list_by_asset_ordered(db):
    asset = await _create_asset(db)
    await _seed_prices(db, asset.id, n_days=10)

    repo = PriceRepository(db)
    result = await repo.list_by_asset(asset.id)
    assert len(result) > 0
    dates = [p.date for p in result]
    assert dates == sorted(dates)


async def test_list_by_asset_since(db):
    asset = await _create_asset(db)
    await _seed_prices(db, asset.id, n_days=30)

    since = date.today() - timedelta(days=10)
    repo = PriceRepository(db)
    result = await repo.list_by_asset_since(asset.id, since)
    assert all(p.date >= since for p in result)


async def test_get_dates_for_asset_between_is_inclusive_and_scoped(db):
    a1 = await _create_asset(db, "AAPL")
    a2 = await _create_asset(db, "MSFT")
    prices = await _seed_prices(db, a1.id, n_days=10)
    await _seed_prices(db, a2.id, n_days=10)
    start = prices[1].date
    end = prices[-2].date

    dates = await PriceRepository(db).get_dates_for_asset_between(a1.id, start, end)

    assert dates == {price.date for price in prices if start <= price.date <= end}


async def test_delete_prices_after(db):
    """delete_prices_after removes only rows strictly after the cutoff date."""
    asset = await _create_asset(db)
    await _seed_prices(db, asset.id, n_days=20)
    repo = PriceRepository(db)

    all_rows = await repo.list_by_asset(asset.id)
    cutoff = all_rows[len(all_rows) // 2].date
    expected = sum(1 for p in all_rows if p.date > cutoff)

    deleted = await repo.delete_prices_after(asset.id, cutoff)

    assert deleted == expected
    assert deleted > 0  # the split actually left rows past the cutoff to delete
    remaining = await repo.list_by_asset(asset.id)
    assert all(p.date <= cutoff for p in remaining)


async def test_delete_prices_after_scoped_to_asset(db):
    """Deletion never touches another asset's rows."""
    a1 = await _create_asset(db, "AAPL")
    a2 = await _create_asset(db, "MSFT")
    await _seed_prices(db, a1.id, n_days=10)
    await _seed_prices(db, a2.id, n_days=10)
    repo = PriceRepository(db)

    await repo.delete_prices_after(a1.id, date(1900, 1, 1))  # wipe a1 entirely

    assert await repo.list_by_asset(a1.id) == []
    assert len(await repo.list_by_asset(a2.id)) > 0


async def test_list_by_assets_since(db):
    a1 = await _create_asset(db, "AAPL")
    a2 = await _create_asset(db, "MSFT")
    await _seed_prices(db, a1.id, n_days=20)
    await _seed_prices(db, a2.id, n_days=20)

    since = date.today() - timedelta(days=10)
    repo = PriceRepository(db)
    result = await repo.list_by_assets_since([a1.id, a2.id], since)
    asset_ids = {p.asset_id for p in result}
    assert a1.id in asset_ids
    assert a2.id in asset_ids
    assert all(p.date >= since for p in result)


async def test_get_latest_date(db):
    asset = await _create_asset(db)
    await _seed_prices(db, asset.id, n_days=20)

    repo = PriceRepository(db)
    latest = await repo.get_latest_date([asset.id])
    assert latest is not None
    # Latest date should be today or very close (weekday adjustments)
    assert latest >= date.today() - timedelta(days=3)


async def test_get_latest_date_no_data(db):
    repo = PriceRepository(db)
    result = await repo.get_latest_date([999])
    assert result is None


async def test_get_first_dates(db):
    a1 = await _create_asset(db, "AAPL")
    a2 = await _create_asset(db, "MSFT")
    await _seed_prices(db, a1.id, n_days=30)
    await _seed_prices(db, a2.id, n_days=30)

    since = date.today() - timedelta(days=15)
    repo = PriceRepository(db)
    first_dates = await repo.get_first_dates([a1.id, a2.id], since)
    assert a1.id in first_dates
    assert a2.id in first_dates
    assert first_dates[a1.id] >= since


async def test_get_last_dates(db):
    a1 = await _create_asset(db, "AAPL")
    await _seed_prices(db, a1.id, n_days=30)

    repo = PriceRepository(db)
    last_dates = await repo.get_last_dates([a1.id])
    assert a1.id in last_dates


async def test_get_prices_at_dates(db):
    asset = await _create_asset(db)
    prices = await _seed_prices(db, asset.id, n_days=10)

    repo = PriceRepository(db)
    target_dates = {prices[0].date, prices[-1].date}
    result = await repo.get_prices_at_dates([asset.id], target_dates)
    assert (asset.id, prices[0].date) in result
    assert (asset.id, prices[-1].date) in result


async def test_upsert_prices_mocked(db):
    """upsert_prices uses pg_insert which is PostgreSQL-only, so we verify the
    empty-DataFrame shortcut works and mock the rest."""
    repo = PriceRepository(db)
    count = await repo.upsert_prices(AssetRef("AAPL", 1), pd.DataFrame())
    assert count == 0


async def test_build_price_rows_logs_nan_skips(caplog):
    """A NaN-OHLC bar is skipped but never silently — the skip is logged with
    its date so a hole in price_history is diagnosable (issue #559)."""
    idx = pd.bdate_range(end=date.today(), periods=3)
    df = pd.DataFrame({
        "open": [100.0, float("nan"), 102.0],
        "high": [101.0, 101.5, 103.0],
        "low": [99.0, 99.5, 101.0],
        "close": [100.5, 101.0, 102.5],
        "volume": [1_000, 1_000, 1_000],
    }, index=idx)

    with caplog.at_level("WARNING", logger="app.repositories.price_repo"):
        rows = PriceRepository.build_price_rows(AssetRef("MT.AS", 1), df)

    assert len(rows) == 2
    assert [r["date"] for r in rows] == [idx[0].date(), idx[2].date()]
    assert len(caplog.records) == 1
    assert idx[1].date().isoformat() in caplog.records[0].getMessage()
    assert "gap" in caplog.records[0].getMessage()
    assert "MT.AS" in caplog.records[0].getMessage()


async def test_build_price_rows_clean_df_no_warning(caplog):
    """No NaN rows -> no warning noise."""
    idx = pd.bdate_range(end=date.today(), periods=3)
    df = pd.DataFrame({
        "open": [100.0] * 3, "high": [101.0] * 3, "low": [99.0] * 3,
        "close": [100.5] * 3, "volume": [1_000] * 3,
    }, index=idx)
    with caplog.at_level("WARNING", logger="app.repositories.price_repo"):
        rows = PriceRepository.build_price_rows(AssetRef("AAPL", 1), df)
    assert len(rows) == 3
    assert not caplog.records
