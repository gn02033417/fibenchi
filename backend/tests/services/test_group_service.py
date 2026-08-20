"""Unit tests for group_service — tests service logic with mocked repos."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.group_service import (
    add_assets,
    create_group,
    delete_group,
    list_groups,
    remove_asset,
    update_group,
)

pytestmark = pytest.mark.asyncio(loop_scope="function")

_PATCH_GET_GROUP = "app.services.group_service.get_group"


def _make_group(id: int = 1, name: str = "Tech", description: str = "Tech stocks", is_default: bool = False):
    group = MagicMock()
    group.id = id
    group.name = name
    group.description = description
    group.is_default = is_default
    group.realtime_priority = False
    group.assets = []
    return group


def _make_asset(id: int, symbol: str = "AAPL"):
    from tests.helpers import make_mock_asset
    return make_mock_asset(symbol=symbol, id=id)


@patch("app.services.group_service.GroupRepository")
async def test_list_groups_delegates_to_repo(MockRepo):
    db = AsyncMock()
    mock_repo = MockRepo.return_value
    expected = [_make_group(), _make_group(id=2, name="Energy")]
    mock_repo.list_all = AsyncMock(return_value=expected)

    result = await list_groups(db)

    MockRepo.assert_called_once_with(db)
    mock_repo.list_all.assert_awaited_once()
    assert result == expected


@patch("app.services.group_service.GroupRepository")
async def test_create_group_duplicate_raises_400(MockRepo):
    db = AsyncMock()
    mock_repo = MockRepo.return_value
    mock_repo.get_by_name = AsyncMock(return_value=_make_group())

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await create_group(db, name="Tech", description="Tech stocks")
    assert exc_info.value.status_code == 400


@patch("app.services.group_service.GroupRepository")
async def test_create_group_success(MockRepo):
    db = AsyncMock()
    mock_repo = MockRepo.return_value
    mock_repo.get_by_name = AsyncMock(return_value=None)
    new_group = _make_group()
    mock_repo.create = AsyncMock(return_value=new_group)

    result = await create_group(db, name="Tech", description="Tech stocks")

    mock_repo.create.assert_awaited_once_with(name="Tech", description="Tech stocks", icon=None)
    assert result == new_group


@patch("app.services.group_service.GroupRepository")
async def test_update_group_only_sets_provided_fields(MockRepo):
    """Fields not in the data dict (omitted by client) are untouched."""
    db = AsyncMock()
    group = _make_group(name="Old", description="Old desc")
    mock_repo = MockRepo.return_value
    mock_repo.save = AsyncMock(return_value=group)

    with patch(_PATCH_GET_GROUP, new_callable=AsyncMock, return_value=group):
        await update_group(db, group_id=1, data={"name": "New"})

    assert group.name == "New"
    assert group.description == "Old desc"
    mock_repo.save.assert_awaited_once_with(group)


@patch("app.services.group_service.GroupRepository")
async def test_update_group_can_clear_optional_field(MockRepo):
    """Explicitly sending None clears an optional field (exclude_unset pattern)."""
    db = AsyncMock()
    group = _make_group(name="Old", description="Old desc")
    mock_repo = MockRepo.return_value
    mock_repo.save = AsyncMock(return_value=group)

    with patch(_PATCH_GET_GROUP, new_callable=AsyncMock, return_value=group):
        await update_group(db, group_id=1, data={"description": None})

    assert group.name == "Old"
    assert group.description is None


@patch("app.services.group_service.GroupRepository")
async def test_update_group_patches_both_fields(MockRepo):
    db = AsyncMock()
    group = _make_group(name="Old", description="Old desc")
    mock_repo = MockRepo.return_value
    mock_repo.save = AsyncMock(return_value=group)

    with patch(_PATCH_GET_GROUP, new_callable=AsyncMock, return_value=group):
        await update_group(db, group_id=1, data={"name": "New", "description": "New desc"})

    assert group.name == "New"
    assert group.description == "New desc"


@patch("app.services.group_service.GroupRepository")
async def test_update_group_sets_realtime_priority(MockRepo):
    db = AsyncMock()
    group = _make_group()
    mock_repo = MockRepo.return_value
    mock_repo.save = AsyncMock(return_value=group)

    with patch(_PATCH_GET_GROUP, new_callable=AsyncMock, return_value=group):
        await update_group(db, group_id=1, data={"realtime_priority": True})

    assert group.realtime_priority is True
    mock_repo.save.assert_awaited_once_with(group)


@patch("app.services.group_service.AssetRepository")
@patch("app.services.group_service.GroupRepository")
async def test_add_assets_skips_existing(MockGroupRepo, MockAssetRepo):
    db = AsyncMock()
    existing_asset = _make_asset(id=1, symbol="AAPL")
    new_asset = _make_asset(id=2, symbol="MSFT")
    group = _make_group()
    group.assets = [existing_asset]

    mock_group_repo = MockGroupRepo.return_value
    mock_group_repo.save = AsyncMock(return_value=group)
    mock_asset_repo = MockAssetRepo.return_value
    mock_asset_repo.get_by_ids = AsyncMock(return_value=[existing_asset, new_asset])

    with patch(_PATCH_GET_GROUP, new_callable=AsyncMock, return_value=group):
        await add_assets(db, group_id=1, asset_ids=[1, 2])

    assert new_asset in group.assets
    assert group.assets.count(existing_asset) == 1
    mock_group_repo.save.assert_awaited_once()


@patch("app.services.group_service.GroupRepository")
async def test_remove_asset_filters_correctly(MockRepo):
    db = AsyncMock()
    asset1 = _make_asset(id=1, symbol="AAPL")
    asset2 = _make_asset(id=2, symbol="MSFT")
    group = _make_group()
    group.assets = [asset1, asset2]

    mock_repo = MockRepo.return_value
    mock_repo.save = AsyncMock(return_value=group)

    with patch(_PATCH_GET_GROUP, new_callable=AsyncMock, return_value=group):
        await remove_asset(db, group_id=1, asset_id=1)

    assert len(group.assets) == 1
    assert group.assets[0].id == 2
    mock_repo.save.assert_awaited_once()


# --- Default group protection ---

async def test_delete_default_group_raises_400():
    from fastapi import HTTPException

    db = AsyncMock()
    group = _make_group(is_default=True)

    with patch(_PATCH_GET_GROUP, new_callable=AsyncMock, return_value=group):
        with pytest.raises(HTTPException) as exc_info:
            await delete_group(db, group_id=1)
        assert exc_info.value.status_code == 400
        assert "default" in exc_info.value.detail.lower()


@patch("app.services.group_service.GroupRepository")
async def test_rename_default_group_raises_400(MockRepo):
    from fastapi import HTTPException

    db = AsyncMock()
    group = _make_group(name="Watchlist", is_default=True)

    with patch(_PATCH_GET_GROUP, new_callable=AsyncMock, return_value=group):
        with pytest.raises(HTTPException) as exc_info:
            await update_group(db, group_id=1, data={"name": "Renamed"})
        assert exc_info.value.status_code == 400


@patch("app.services.group_service.GroupRepository")
async def test_update_default_group_description_allowed(MockRepo):
    db = AsyncMock()
    group = _make_group(name="Watchlist", is_default=True)
    mock_repo = MockRepo.return_value
    mock_repo.save = AsyncMock(return_value=group)

    with patch(_PATCH_GET_GROUP, new_callable=AsyncMock, return_value=group):
        await update_group(db, group_id=1, data={"description": "Updated desc"})

    assert group.description == "Updated desc"
    mock_repo.save.assert_awaited_once()
