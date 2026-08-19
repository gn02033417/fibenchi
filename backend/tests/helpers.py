"""Shared test helpers — extracted from integration tests to avoid duplication."""

from datetime import date, timedelta
from unittest.mock import MagicMock

import numpy as np
import pandas as pd

from app.models import Asset, AssetType, PriceHistory
from app.models.symbol_directory import SymbolDirectory
from app.repositories.group_repo import GroupRepository


async def create_asset_via_api(
    client, symbol: str, name: str, attach_to_watchlist: bool = True, **kwargs
) -> dict:
    """Create an asset through the HTTP API and return the JSON response.

    ``POST /api/assets`` no longer attaches to any group. By default this
    helper also adds the new asset to the seeded Watchlist group so it
    appears in ``GET /api/assets`` listings (the historical behaviour most
    integration tests depend on). Pass ``attach_to_watchlist=False`` for
    tests that want a group-less asset.
    """
    resp = await client.post("/api/assets", json={"symbol": symbol, "name": name, **kwargs})
    asset = resp.json()
    if attach_to_watchlist and resp.status_code == 201:
        groups = (await client.get("/api/groups")).json()
        watchlist_id = next((g["id"] for g in groups if g["is_default"]), None)
        if watchlist_id is not None:
            await client.post(
                f"/api/groups/{watchlist_id}/assets",
                json={"asset_ids": [asset["id"]]},
            )
    return asset


async def seed_taiwan_directory(db, rows: list[dict[str, object]]) -> None:
    """Seed verified Taiwan directory rows for API integration fixtures."""
    db.add_all(
        SymbolDirectory(
            symbol=str(row["symbol"]),
            name=str(row["name"]),
            exchange=str(row.get("exchange", "TSE")),
            type=str(row.get("type", "stock")),
            currency="TWD",
            active=True,
        )
        for row in rows
    )
    await db.commit()


async def seed_asset_with_prices(
    db, symbol: str = "AAPL", name: str | None = None, n_days: int = 700,
    base_price: float = 150.0, add_to_group: bool = True,
) -> Asset:
    """Create an asset with n_days of realistic price data.

    When add_to_group is True (default), the asset is added to the default
    default group so it appears in group/portfolio queries.
    """
    asset = Asset(
        symbol=symbol, name=name or f"{symbol} Inc.",
        type=AssetType.STOCK, currency="USD",
    )
    db.add(asset)
    await db.flush()

    if add_to_group:
        default_group = await GroupRepository(db).get_default()
        if default_group:
            default_group.assets.append(asset)

    today = date.today()
    for i in range(n_days):
        d = today - timedelta(days=n_days - 1 - i)
        if d.weekday() >= 5:
            continue
        price = base_price + i * 0.1
        db.add(PriceHistory(
            asset_id=asset.id, date=d,
            open=round(price - 0.5, 4), high=round(price + 1.0, 4),
            low=round(price - 1.0, 4), close=round(price, 4),
            volume=1_000_000 + i * 1000,
        ))
    await db.commit()
    return asset


def make_yahoo_df(n_days: int = 60, base_price: float = 100.0) -> pd.DataFrame:
    """Create a DataFrame that looks like Yahoo Finance output."""
    dates = pd.bdate_range(end=date.today(), periods=n_days)
    prices = [base_price + i * 0.5 for i in range(n_days)]
    return pd.DataFrame({
        "open": [p - 0.5 for p in prices],
        "high": [p + 1.0 for p in prices],
        "low": [p - 1.0 for p in prices],
        "close": prices,
        "volume": [1_000_000] * n_days,
    }, index=dates)


def make_price_df(n: int = 100, start_price: float = 100.0) -> pd.DataFrame:
    """Generate synthetic price data for testing (seeded for reproducibility)."""
    np.random.seed(42)
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    returns = np.random.normal(0.001, 0.02, n)
    prices = start_price * np.cumprod(1 + returns)

    return pd.DataFrame({
        "open": prices * (1 - np.random.uniform(0, 0.01, n)),
        "high": prices * (1 + np.random.uniform(0, 0.02, n)),
        "low": prices * (1 - np.random.uniform(0, 0.02, n)),
        "close": prices,
        "volume": np.random.randint(1_000_000, 10_000_000, n),
    }, index=dates)


def make_series_from_returns(returns: list[float], start: float = 100.0) -> pd.Series:
    """Build a close series from a list of simple returns (cumulative product)."""
    closes = [start]
    for r in returns:
        closes.append(closes[-1] * (1 + r))
    return pd.Series(closes)


# ---------------------------------------------------------------------------
# Repository test helpers — real SQLAlchemy model instances (need db session)
# ---------------------------------------------------------------------------

async def create_test_asset(db, symbol: str = "AAPL", **kwargs) -> Asset:
    """Create and commit a real Asset row to the test database.

    Used in repository tests where a real DB session is available.
    """
    defaults = dict(name=f"{symbol} Inc.", type=AssetType.STOCK, currency="USD")
    defaults.update(kwargs)
    asset = Asset(symbol=symbol, **defaults)
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return asset


# ---------------------------------------------------------------------------
# Service test helpers — lightweight mock/model instances (no db needed)
# ---------------------------------------------------------------------------

def make_mock_asset(symbol: str = "AAPL", **overrides) -> Asset:
    """Create a MagicMock that quacks like an Asset.

    Used in service tests where repos are mocked and no real DB exists.
    """
    asset = MagicMock(spec=Asset)
    asset.id = overrides.pop("id", 1)
    asset.symbol = symbol
    asset.tags = overrides.pop("tags", [])
    for k, v in overrides.items():
        setattr(asset, k, v)
    return asset


def make_model_asset(**overrides) -> Asset:
    """Create a real Asset model instance (not persisted to any database).

    Used in service tests that patch repositories and need real model objects
    (e.g. asset_service tests that inspect attribute values).
    """
    defaults = dict(
        id=1, symbol="AAPL", name="Apple Inc.",
        type=AssetType.STOCK, currency="USD",
    )
    defaults.update(overrides)
    return Asset(**defaults)
