from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, select

from app.models.asset import Asset, AssetType
from app.models.group import Group, group_assets
from app.models.note import Note
from app.models.price import PriceHistory
from app.models.symbol_directory import SymbolDirectory
from app.models.tag import Tag
from app.models.thesis import Thesis
from app.services.taiwan_symbol_migration import (
    TaiwanSymbolMigrationError,
    normalize_legacy_taiwan_symbol,
    normalize_legacy_taiwan_symbols,
)


def _load_0022_revision():
    path = Path(__file__).parents[2] / "alembic" / "versions" / "0022_normalize_taiwan_symbols.py"
    spec = importlib.util.spec_from_file_location("migration_0022", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_normalize_legacy_taiwan_symbol_accepts_only_numeric_taiwan_suffixes():
    assert normalize_legacy_taiwan_symbol("2330.TW") == "2330"
    assert normalize_legacy_taiwan_symbol("6488.TWO") == "6488"
    assert normalize_legacy_taiwan_symbol("0050.TW") == "0050"
    assert normalize_legacy_taiwan_symbol("AAPL.TW") is None
    assert normalize_legacy_taiwan_symbol("2330") is None
    assert normalize_legacy_taiwan_symbol("AAPL") is None


async def test_normalizes_in_place_and_preserves_fk_relationships(db):
    default_group = (await db.execute(select(Group).where(Group.is_default.is_(True)))).scalar_one()
    asset = Asset(
        symbol="2330.TW",
        name="台積電",
        type=AssetType.STOCK,
        exchange="TSE",
        currency="TWD",
    )
    tag = Tag(name="半導體", color="#123456")
    thesis = Thesis(name="台股核心", opened_at=date(2026, 8, 19))
    directory = SymbolDirectory(
        symbol="2330.TW",
        name="台積電",
        exchange="TSE",
        type="stock",
        currency="TWD",
        active=True,
    )
    foreign_asset = Asset(symbol="AAPL", name="Apple", type=AssetType.STOCK, currency="USD")
    foreign_directory = SymbolDirectory(
        symbol="AAPL",
        name="Apple",
        exchange="NASDAQ",
        type="stock",
        currency="USD",
        active=True,
    )
    asset.tags = [tag]
    asset.theses = [thesis]
    asset.note = Note(content="保留這個 note")
    asset.prices = [
        PriceHistory(
            date=date(2026, 8, 18),
            open=900,
            high=910,
            low=890,
            close=905,
            volume=1000,
        )
    ]
    db.add_all([asset, tag, thesis, directory, foreign_asset, foreign_directory])
    default_group.assets.append(asset)
    await db.commit()

    asset_id = asset.id
    directory_id = directory.id

    result = await normalize_legacy_taiwan_symbols(db)

    assert result == {"assets": 1, "symbol_directory": 1}
    migrated_asset = await db.get(Asset, asset_id)
    migrated_directory = await db.get(SymbolDirectory, directory_id)
    assert migrated_asset is not None
    assert migrated_directory is not None
    assert migrated_asset.symbol == "2330"
    assert migrated_directory.symbol == "2330"
    assert migrated_asset.id == asset_id
    assert migrated_directory.id == directory_id
    assert migrated_asset.tags[0].name == "半導體"
    assert migrated_asset.theses[0].name == "台股核心"
    assert migrated_asset.note is not None
    assert migrated_asset.note.content == "保留這個 note"
    assert migrated_asset.prices[0].close == 905

    group_link = (
        await db.execute(
            select(group_assets).where(
                group_assets.c.group_id == default_group.id,
                group_assets.c.asset_id == asset_id,
            )
        )
    ).first()
    assert group_link is not None
    assert (await db.get(Asset, foreign_asset.id)).symbol == "AAPL"
    assert (await db.get(SymbolDirectory, foreign_directory.id)).symbol == "AAPL"


async def test_collision_fails_before_changing_any_row(db):
    db.add_all([
        Asset(symbol="2330", name="Raw", type=AssetType.STOCK, currency="TWD"),
        Asset(symbol="2330.TW", name="Legacy", type=AssetType.STOCK, currency="TWD"),
    ])
    await db.commit()

    with pytest.raises(TaiwanSymbolMigrationError, match="2330"):
        await normalize_legacy_taiwan_symbols(db)

    symbols = list((await db.execute(select(Asset.symbol).order_by(Asset.symbol))).scalars())
    assert symbols == ["2330", "2330.TW"]


def test_0022_alembic_migration_updates_rows_in_place():
    engine = create_engine("sqlite://")
    metadata = sa.MetaData()
    assets = sa.Table(
        "assets",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("symbol", sa.String(20), unique=True, nullable=False),
    )
    directory = sa.Table(
        "symbol_directory",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("symbol", sa.String(20), unique=True, nullable=False),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(assets.insert().values(id=10, symbol="6488.TWO"))
        connection.execute(assets.insert().values(id=11, symbol="NVDA"))
        connection.execute(directory.insert().values(id=20, symbol="6488.TWO"))

        migration = _load_0022_revision()
        context = MigrationContext.configure(connection)
        operations = Operations(context)
        original_op = migration.op
        migration.op = operations
        try:
            migration.upgrade()
        finally:
            migration.op = original_op

        asset_rows = connection.execute(sa.select(assets).order_by(assets.c.id)).mappings().all()
        directory_rows = connection.execute(sa.select(directory)).mappings().all()
        assert [(row["id"], row["symbol"]) for row in asset_rows] == [(10, "6488"), (11, "NVDA")]
        assert [(row["id"], row["symbol"]) for row in directory_rows] == [(20, "6488")]
