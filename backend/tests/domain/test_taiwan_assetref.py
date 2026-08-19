"""Stored Taiwan identity must resolve from verified metadata."""

import pytest

from app.domain import AssetKind, AssetRef
from app.repositories.asset_repo import AssetRepository
from app.repositories.group_repo import GroupRepository
from tests.helpers import create_test_asset


def test_stored_tse_asset_ref_uses_exchange_metadata():
    ref = AssetRef("2330", 1, exchange="TSE", currency="TWD")

    assert ref.exchange == "TSE"
    assert ref.kind is AssetKind.EQUITY
    assert ref.calendar_name == "XTAI"
    assert ref.currency == "TWD"


def test_stored_otc_asset_ref_uses_exchange_metadata():
    ref = AssetRef("6488", 2, exchange="OTC", currency="TWD")

    assert ref.kind is AssetKind.EQUITY
    assert ref.calendar_name == "XTAI"
    assert ref.currency == "TWD"


def test_unsuffixed_unbound_ref_keeps_legacy_shape_classification():
    assert AssetRef("2330").calendar_name == "XNYS"
    assert AssetRef("2330").currency == "USD"


@pytest.mark.asyncio
async def test_repository_refs_carry_stored_market_metadata(db):
    asset = await create_test_asset(db, "2330", exchange="TSE", currency="TWD")
    default_group = await GroupRepository(db).get_default()
    default_group.assets.append(asset)
    await db.commit()

    repo = AssetRepository(db)
    refs = await repo.list_in_any_group_refs()
    assert refs[0].calendar_name == "XTAI"
    assert refs[0].currency == "TWD"

    refs = await repo.list_in_group_refs(default_group.id)
    assert refs[0].exchange == "TSE"
    assert refs[0].calendar_name == "XTAI"

    refs = await repo.list_refs_by_symbols(["2330"])
    assert refs[0].kind is AssetKind.EQUITY
    assert refs[0].currency == "TWD"


def test_asset_ref_of_preserves_stored_market_metadata():
    class StoredAsset:
        id = 3
        symbol = "0050"
        exchange = "TSE"
        currency = "TWD"

    ref = AssetRef.of(StoredAsset())

    assert ref.exchange == "TSE"
    assert ref.calendar_name == "XTAI"
    assert ref.currency == "TWD"
