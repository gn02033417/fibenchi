from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect

from app.domain.instrument import UnitKind
from app.domain.provenance import FieldSource
from app.models.asset import Asset, AssetType
from app.models.group import Group
from app.models.symbol_directory import SymbolDirectory
from app.schemas.asset import AssetResponse
from app.schemas.group import GroupResponse


def _load_0021_revision():
    path = Path(__file__).parents[2] / "alembic" / "versions" / "0021_taiwan_market_metadata.py"
    spec = importlib.util.spec_from_file_location("migration_0021", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_taiwan_metadata_models_and_response_schemas_round_trip():
    asset = Asset(
        id=1,
        symbol="2330",
        name="台積電",
        type=AssetType.STOCK,
        currency="TWD",
        exchange="TSE",
        unit_kind=UnitKind.CURRENCY,
        type_source=FieldSource.AUTO,
        unit_source=FieldSource.AUTO,
        created_at=datetime(2026, 8, 19, 8, 0),
    )
    group = Group(
        id=1,
        name="Realtime",
        is_default=False,
        position=0,
        created_at=datetime(2026, 8, 19, 8, 0),
        realtime_priority=True,
    )
    directory = SymbolDirectory(
        symbol="0050",
        name="元大台灣50",
        exchange="TSE",
        type="etf",
        currency="TWD",
        active=True,
        contract_updated_at=datetime(2026, 8, 19, 8, 0),
        reference_updated_at=datetime(2026, 8, 19, 8, 1),
    )

    assert asset.exchange == "TSE"
    assert group.realtime_priority is True
    assert directory.currency == "TWD"
    assert directory.active is True
    assert directory.contract_updated_at is not None
    assert directory.reference_updated_at is not None

    asset_response = AssetResponse.model_validate(asset, from_attributes=True)
    group_response = GroupResponse.model_validate(group, from_attributes=True)
    assert asset_response.exchange == "TSE"
    assert group_response.realtime_priority is True


def test_group_realtime_priority_defaults_false():
    column = Group.__table__.c.realtime_priority
    assert column.default.arg is False
    assert str(column.server_default.arg) == "false"


def test_0021_migration_adds_columns_and_preserves_existing_rows():
    engine = create_engine("sqlite://")
    metadata = sa.MetaData()
    assets = sa.Table(
        "assets",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("symbol", sa.String(20), nullable=False),
    )
    groups = sa.Table(
        "groups",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
    )
    directory = sa.Table(
        "symbol_directory",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("exchange", sa.String(100), nullable=False),
        sa.Column("type", sa.String(10), nullable=False),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(assets.insert().values(id=1, symbol="0050"))
        connection.execute(groups.insert().values(id=1, name="Watchlist"))
        connection.execute(
            directory.insert().values(
                id=1, symbol="0050", name="元大台灣50", exchange="TSE", type="etf"
            )
        )

        migration = _load_0021_revision()
        context = MigrationContext.configure(connection)
        operations = Operations(context)
        original_op = migration.op
        migration.op = operations
        try:
            migration.upgrade()
        finally:
            migration.op = original_op

        column_names = {
            table: {column["name"] for column in inspect(connection).get_columns(table)}
            for table in ("assets", "groups", "symbol_directory")
        }
        assert "exchange" in column_names["assets"]
        assert "realtime_priority" in column_names["groups"]
        assert {"currency", "active", "contract_updated_at", "reference_updated_at"} <= column_names[
            "symbol_directory"
        ]

        reflected = sa.MetaData()
        reflected.reflect(connection, only=("assets", "groups", "symbol_directory"))
        existing_asset = connection.execute(sa.select(reflected.tables["assets"])).mappings().one()
        existing_group = connection.execute(sa.select(reflected.tables["groups"])).mappings().one()
        existing_directory = connection.execute(sa.select(reflected.tables["symbol_directory"])).mappings().one()
        assert existing_asset["symbol"] == "0050"
        assert existing_asset["exchange"] is None
        assert existing_group["realtime_priority"] is False
        assert existing_directory["currency"] == "USD"
        assert existing_directory["active"] is True

        migration = _load_0021_revision()
        context = MigrationContext.configure(connection)
        operations = Operations(context)
        original_op = migration.op
        migration.op = operations
        try:
            migration.downgrade()
        finally:
            migration.op = original_op

        downgraded_columns = {
            table: {column["name"] for column in inspect(connection).get_columns(table)}
            for table in ("assets", "groups", "symbol_directory")
        }
        assert "exchange" not in downgraded_columns["assets"]
        assert "realtime_priority" not in downgraded_columns["groups"]
        assert not {"currency", "active", "contract_updated_at", "reference_updated_at"} & downgraded_columns[
            "symbol_directory"
        ]
