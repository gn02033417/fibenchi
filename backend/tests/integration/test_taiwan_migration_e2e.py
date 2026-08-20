"""Migrated-install gate for legacy Taiwan symbols and relationships."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from app.models.asset import Asset, AssetType
from app.models.group import Group, group_assets
from app.models.note import Note
from app.models.price import PriceHistory
from app.models.symbol_directory import SymbolDirectory
from app.models.tag import Tag
from app.models.thesis import Thesis
from app.services.taiwan_symbol_migration import (
    TaiwanSymbolMigrationError,
    normalize_legacy_taiwan_symbols,
)

pytestmark = pytest.mark.asyncio(loop_scope="function")


async def test_migrated_taiwan_rows_keep_ids_and_relationships(db):
    default_group = (
        await db.execute(select(Group).where(Group.is_default.is_(True)))
    ).scalar_one()
    stock = Asset(
        symbol="2330.TW",
        name="台積電",
        type=AssetType.STOCK,
        exchange="TSE",
        currency="TWD",
    )
    otc = Asset(
        symbol="0050.TWO",
        name="元大台灣50",
        type=AssetType.ETF,
        exchange="OTC",
        currency="TWD",
    )
    stock_directory = SymbolDirectory(
        symbol="2330.TW",
        name="台積電",
        exchange="TSE",
        type="stock",
        currency="TWD",
        active=True,
    )
    otc_directory = SymbolDirectory(
        symbol="0050.TWO",
        name="元大台灣50",
        exchange="OTC",
        type="etf",
        currency="TWD",
        active=True,
    )
    foreign_asset = Asset(symbol="AAPL", name="Apple", type=AssetType.STOCK, currency="USD")
    foreign_directory = SymbolDirectory(
        symbol="AAPL.TW",
        name="Foreign-looking text",
        exchange="NASDAQ",
        type="stock",
        currency="USD",
        active=True,
    )
    stock.tags = [Tag(name="半導體", color="#123456")]
    stock.theses = [Thesis(name="台股核心", opened_at=date(2026, 8, 19))]
    stock.note = Note(content="保留 migration 關聯")
    stock.prices = [
        PriceHistory(
            date=date(2026, 8, 19),
            open=1000,
            high=1010,
            low=990,
            close=1005,
            volume=1000,
        )
    ]
    db.add_all([
        stock,
        otc,
        stock_directory,
        otc_directory,
        foreign_asset,
        foreign_directory,
    ])
    default_group.assets.extend([stock, otc])
    await db.commit()

    stock_id = stock.id
    otc_id = otc.id
    stock_directory_id = stock_directory.id
    otc_directory_id = otc_directory.id

    result = await normalize_legacy_taiwan_symbols(db)

    assert result == {"assets": 2, "symbol_directory": 2}
    migrated_stock = await db.get(Asset, stock_id)
    migrated_otc = await db.get(Asset, otc_id)
    migrated_stock_directory = await db.get(SymbolDirectory, stock_directory_id)
    migrated_otc_directory = await db.get(SymbolDirectory, otc_directory_id)
    assert migrated_stock is not None
    assert migrated_otc is not None
    assert migrated_stock_directory is not None
    assert migrated_otc_directory is not None
    assert migrated_stock.symbol == migrated_stock_directory.symbol == "2330"
    assert migrated_otc.symbol == migrated_otc_directory.symbol == "0050"
    assert migrated_stock.id == stock_id
    assert migrated_otc.id == otc_id
    assert migrated_stock_directory.id == stock_directory_id
    assert migrated_otc_directory.id == otc_directory_id
    assert migrated_stock.tags[0].name == "半導體"
    assert migrated_stock.theses[0].name == "台股核心"
    assert migrated_stock.note is not None
    assert migrated_stock.note.content == "保留 migration 關聯"
    assert migrated_stock.prices[0].close == 1005
    group_links = (
        await db.execute(
            select(group_assets).where(
                group_assets.c.group_id == default_group.id,
                group_assets.c.asset_id.in_([stock_id, otc_id]),
            )
        )
    ).all()
    assert {
        (link.group_id, link.asset_id)
        for link in group_links
    } == {(default_group.id, stock_id), (default_group.id, otc_id)}
    assert (await db.get(Asset, foreign_asset.id)).symbol == "AAPL"
    assert (await db.get(SymbolDirectory, foreign_directory.id)).symbol == "AAPL.TW"


async def test_migrated_install_collision_is_atomic_across_tables(db):
    db.add_all([
        Asset(symbol="2330", name="Raw", type=AssetType.STOCK, currency="TWD"),
        Asset(symbol="2330.TW", name="Legacy", type=AssetType.STOCK, currency="TWD"),
        SymbolDirectory(
            symbol="6488.TWO",
            name="環球晶",
            exchange="OTC",
            type="stock",
            currency="TWD",
            active=True,
        ),
    ])
    await db.commit()

    with pytest.raises(TaiwanSymbolMigrationError, match="2330"):
        await normalize_legacy_taiwan_symbols(db)

    asset_symbols = list(
        (await db.execute(select(Asset.symbol).order_by(Asset.symbol))).scalars()
    )
    directory_symbols = list(
        (await db.execute(select(SymbolDirectory.symbol))).scalars()
    )
    assert asset_symbols == ["2330", "2330.TW"]
    assert directory_symbols == ["6488.TWO"]
