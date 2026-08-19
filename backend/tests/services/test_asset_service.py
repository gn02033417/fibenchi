"""Unit tests for asset_service — local Taiwan directory contract."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.domain import UnitKind
from app.domain.provenance import FieldSource
from app.models import AssetType
from app.models.symbol_directory import SymbolDirectory
from app.services.asset_service import create_asset, delete_asset, list_assets, update_asset
from tests.helpers import make_model_asset as _make_asset

_ensure_patch = "app.services.asset_service.ensure_currency"

pytestmark = pytest.mark.asyncio(loop_scope="function")


def _make_default_group(assets=None):
    group = MagicMock()
    group.id = 1
    group.name = "Watchlist"
    group.is_default = True
    group.assets = list(assets or [])
    return group


def _directory(
    symbol="2330",
    name="台積電",
    exchange="TSE",
    asset_type="stock",
    active=True,
):
    return SymbolDirectory(
        symbol=symbol,
        name=name,
        exchange=exchange,
        type=asset_type,
        currency="TWD",
        active=active,
    )


@patch("app.services.asset_service.AssetRepository")
async def test_list_assets_delegates_to_repo(MockRepo):
    db = AsyncMock()
    mock_repo = MockRepo.return_value
    expected = [_make_asset()]
    mock_repo.list_all = AsyncMock(return_value=expected)

    result = await list_assets(db)

    MockRepo.assert_called_once_with(db)
    mock_repo.list_all.assert_awaited_once()
    assert result == expected


@patch("app.services.yahoo.yahoo_client.validate", new_callable=AsyncMock)
@patch("app.services.shioaji.client.ShioajiClient.list_contracts", new_callable=AsyncMock)
@patch(_ensure_patch, new_callable=AsyncMock)
@patch("app.services.asset_service.AssetRepository")
async def test_create_asset_copies_directory_metadata_without_external_validation(
    MockAssetRepo,
    mock_ensure,
    list_contracts,
    yahoo_validate,
):
    db = AsyncMock()
    mock_repo = MockAssetRepo.return_value
    mock_repo.find_directory_by_symbol = AsyncMock(return_value=_directory())
    mock_repo.find_by_symbol = AsyncMock(return_value=None)
    mock_repo.create = AsyncMock(return_value=_make_asset(symbol="2330", name="台積電"))

    await create_asset(db, symbol="2330", name="caller supplied name", asset_type=AssetType.ETF)

    kwargs = mock_repo.create.call_args.kwargs
    assert kwargs["symbol"] == "2330"
    assert kwargs["name"] == "台積電"
    assert kwargs["exchange"] == "TSE"
    assert kwargs["type"] is AssetType.STOCK
    assert kwargs["type_source"] is FieldSource.AUTO
    assert kwargs["currency"] == "TWD"
    assert kwargs["unit_kind"] is UnitKind.CURRENCY
    mock_ensure.assert_awaited_once_with(db, "TWD")
    yahoo_validate.assert_not_awaited()
    list_contracts.assert_not_awaited()


@patch(_ensure_patch, new_callable=AsyncMock)
@patch("app.services.asset_service.AssetRepository")
async def test_create_asset_copies_etf_and_otc_directory_metadata(MockAssetRepo, mock_ensure):
    db = AsyncMock()
    mock_repo = MockAssetRepo.return_value
    mock_repo.find_by_symbol = AsyncMock(return_value=None)
    mock_repo.create = AsyncMock(side_effect=[
        _make_asset(symbol="0050", name="元大台灣50", type=AssetType.ETF),
        _make_asset(symbol="6488", name="環球晶", type=AssetType.STOCK),
    ])
    mock_repo.find_directory_by_symbol = AsyncMock(side_effect=[
        _directory("0050", "元大台灣50", "TSE", "etf"),
        _directory("6488", "環球晶", "OTC", "stock"),
    ])

    await create_asset(db, "0050", None)
    await create_asset(db, "6488", None)

    first, second = mock_repo.create.await_args_list
    assert first.kwargs["type"] is AssetType.ETF
    assert first.kwargs["exchange"] == "TSE"
    assert second.kwargs["type"] is AssetType.STOCK
    assert second.kwargs["exchange"] == "OTC"
    assert first.kwargs["currency"] == second.kwargs["currency"] == "TWD"
    assert mock_ensure.await_count == 2


@patch("app.services.asset_service.AssetRepository")
async def test_create_asset_rejects_non_taiwan_symbol(MockAssetRepo):
    db = AsyncMock()
    mock_repo = MockAssetRepo.return_value
    mock_repo.find_directory_by_symbol = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc_info:
        await create_asset(db, symbol="AAPL", name=None)

    assert exc_info.value.status_code == 404
    assert "Taiwan symbol directory" in exc_info.value.detail
    mock_repo.create.assert_not_called()


@pytest.mark.parametrize(
    "directory, expected_text",
    [
        (_directory("9000", "停牌商品", "TSE", "stock", active=False), "inactive"),
        (_directory("7777", "未知商品", "TSE", "unknown"), "supported"),
        (_directory("US01", "海外商品", "NASDAQ", "stock"), "supported"),
    ],
)
@patch("app.services.asset_service.AssetRepository")
async def test_create_asset_rejects_inactive_or_unsupported_directory(
    MockAssetRepo,
    directory,
    expected_text,
):
    db = AsyncMock()
    mock_repo = MockAssetRepo.return_value
    mock_repo.find_directory_by_symbol = AsyncMock(return_value=directory)

    with pytest.raises(HTTPException) as exc_info:
        await create_asset(db, directory.symbol, None)

    assert exc_info.value.status_code == 404
    assert expected_text in exc_info.value.detail
    mock_repo.create.assert_not_called()


@patch("app.services.asset_service.AssetRepository")
async def test_create_asset_existing_returns_record_without_group_mutation(MockAssetRepo):
    db = AsyncMock()
    mock_repo = MockAssetRepo.return_value
    mock_repo.find_directory_by_symbol = AsyncMock(return_value=_directory())
    existing = _make_asset(symbol="2330")
    mock_repo.find_by_symbol = AsyncMock(return_value=existing)

    with patch("app.services.asset_service.GroupRepository") as MockGroupRepo:
        result = await create_asset(db, symbol="2330", name="台積電")

    assert result is existing
    mock_repo.create.assert_not_called()
    MockGroupRepo.assert_not_called()


@patch(_ensure_patch, new_callable=AsyncMock)
@patch("app.services.asset_service.AssetRepository")
async def test_create_asset_does_not_touch_groups(MockAssetRepo, _mock_ensure):
    db = AsyncMock()
    mock_repo = MockAssetRepo.return_value
    mock_repo.find_directory_by_symbol = AsyncMock(return_value=_directory())
    mock_repo.find_by_symbol = AsyncMock(return_value=None)
    mock_repo.create = AsyncMock(return_value=_make_asset(symbol="2330"))

    with patch("app.services.asset_service.GroupRepository") as MockGroupRepo:
        await create_asset(db, symbol="2330", name=None)

    MockGroupRepo.assert_not_called()


@patch("app.services.asset_service.AssetRepository")
async def test_update_asset_partial_fields_left_untouched(MockAssetRepo):
    """Only fields explicitly provided are mutated; the rest stay as they were."""
    db = AsyncMock()
    asset = _make_asset(name="Old Name", type=AssetType.STOCK, currency="USD")
    db.get = AsyncMock(return_value=asset)
    mock_repo = MockAssetRepo.return_value
    mock_repo.save = AsyncMock(return_value=asset)

    await update_asset(db, asset_id=1, asset_type=AssetType.INDEX)

    assert asset.type == AssetType.INDEX
    assert asset.name == "Old Name"
    assert asset.currency == "USD"
    mock_repo.save.assert_awaited_once_with(asset)


@patch(_ensure_patch, new_callable=AsyncMock)
@patch("app.services.asset_service.AssetRepository")
async def test_update_asset_currency_ensures_registration(MockAssetRepo, mock_ensure):
    """Updating the currency must register it via ensure_currency before assigning."""
    db = AsyncMock()
    asset = _make_asset(currency="USD")
    db.get = AsyncMock(return_value=asset)
    mock_repo = MockAssetRepo.return_value
    mock_repo.save = AsyncMock(return_value=asset)

    await update_asset(db, asset_id=1, currency="EUR")

    mock_ensure.assert_awaited_once_with(db, "EUR")
    assert asset.currency == "EUR"


async def test_update_asset_missing_raises_404():
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc_info:
        await update_asset(db, asset_id=999, name="x")
    assert exc_info.value.status_code == 404


@patch("app.services.asset_service.GroupRepository")
@patch("app.services.asset_service.AssetRepository")
async def test_delete_asset_removes_from_default_group(MockAssetRepo, MockGroupRepo):
    db = AsyncMock()
    asset = _make_asset()
    default_group = _make_default_group(assets=[asset])

    mock_group_repo = MockGroupRepo.return_value
    mock_group_repo.get_default = AsyncMock(return_value=default_group)
    mock_group_repo.save = AsyncMock()

    with patch("app.services.asset_service.get_asset", new_callable=AsyncMock, return_value=asset):
        await delete_asset(db, "AAPL")

    assert asset not in default_group.assets
    mock_group_repo.save.assert_awaited_once()


@patch("app.services.asset_service.GroupRepository")
@patch("app.services.asset_service.AssetRepository")
async def test_delete_asset_raises_when_no_default_group(MockAssetRepo, MockGroupRepo):
    """A missing default group is a loud configuration error."""
    db = AsyncMock()
    asset = _make_asset()

    mock_group_repo = MockGroupRepo.return_value
    mock_group_repo.get_default = AsyncMock(return_value=None)
    mock_group_repo.save = AsyncMock()

    with patch("app.services.asset_service.get_asset", new_callable=AsyncMock, return_value=asset):
        with pytest.raises(HTTPException) as exc_info:
            await delete_asset(db, "AAPL")

    assert exc_info.value.status_code == 500
    mock_group_repo.save.assert_not_called()
