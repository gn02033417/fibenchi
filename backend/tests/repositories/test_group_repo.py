"""Tests for GroupRepository — query methods against real SQLite DB."""

import pytest

from app.repositories.group_repo import GroupRepository

pytestmark = pytest.mark.asyncio(loop_scope="function")


async def test_list_all_returns_groups_ordered_by_position_then_name(db):
    repo = GroupRepository(db)
    await repo.create(name="Zinc Holdings", description="Z group")
    await repo.create(name="Alpha Fund", description="A group")
    await repo.create(name="Beta Portfolio", description="B group")

    result = await repo.list_all()
    names = [g.name for g in result]
    # Watchlist (position=0) comes first, then the rest ordered by name (position=0)
    assert names == ["Alpha Fund", "Beta Portfolio", "Watchlist", "Zinc Holdings"]


async def test_list_all_includes_default_group(db):
    """The seeded default Watchlist group is always present."""
    repo = GroupRepository(db)
    result = await repo.list_all()
    assert len(result) == 1
    assert result[0].name == "Watchlist"
    assert result[0].is_default is True


async def test_list_realtime_priority_groups_uses_stable_group_order(db):
    repo = GroupRepository(db)
    later = await repo.create(name="Later", description=None)
    earlier = await repo.create(name="Earlier", description=None)
    later.realtime_priority = True
    later.position = 2
    earlier.realtime_priority = True
    earlier.position = 1
    await repo.save_all()

    result = await repo.list_realtime_priority_groups()

    assert [group.name for group in result] == ["Earlier", "Later"]


async def test_get_by_id_found(db):
    repo = GroupRepository(db)
    created = await repo.create(name="Tech Stocks", description="Technology sector")

    result = await repo.get_by_id(created.id)
    assert result is not None
    assert result.name == "Tech Stocks"


async def test_get_by_id_not_found(db):
    repo = GroupRepository(db)
    result = await repo.get_by_id(9999)
    assert result is None


async def test_get_by_name_found(db):
    repo = GroupRepository(db)
    await repo.create(name="Dividends", description="Dividend payers")

    result = await repo.get_by_name("Dividends")
    assert result is not None
    assert result.name == "Dividends"
    assert result.description == "Dividend payers"


async def test_get_by_name_not_found(db):
    repo = GroupRepository(db)
    result = await repo.get_by_name("Nonexistent")
    assert result is None


async def test_create_and_verify_fields(db):
    repo = GroupRepository(db)
    group = await repo.create(name="Energy", description="Energy sector stocks")

    assert group.id is not None
    assert group.name == "Energy"
    assert group.description == "Energy sector stocks"


async def test_save_updates_group(db):
    repo = GroupRepository(db)
    group = await repo.create(name="Healthcare", description="Original description")

    group.description = "Updated description"
    saved = await repo.save(group)

    assert saved.description == "Updated description"

    fetched = await repo.get_by_id(group.id)
    assert fetched.description == "Updated description"


async def test_delete_removes_group(db):
    repo = GroupRepository(db)
    group = await repo.create(name="Delete Me")
    group_id = group.id

    await repo.delete(group)

    result = await repo.get_by_id(group_id)
    assert result is None
