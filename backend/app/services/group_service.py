from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.asset_repo import AssetRepository
from app.repositories.group_repo import GroupRepository
from app.services.entity_lookups import get_group


async def list_groups(db: AsyncSession):
    return await GroupRepository(db).list_all()


async def create_group(db: AsyncSession, name: str, description: str | None, icon: str | None = None):
    repo = GroupRepository(db)
    if await repo.get_by_name(name):
        raise HTTPException(400, f"Group '{name}' already exists")
    return await repo.create(name=name, description=description, icon=icon)


async def get_group_detail(db: AsyncSession, group_id: int):
    return await get_group(group_id, db)


UPDATABLE_GROUP_FIELDS = {"name", "description", "icon", "realtime_priority"}


async def update_group(db: AsyncSession, group_id: int, data: dict):
    """Update a group using only the fields the client explicitly sent.

    ``data`` should come from ``GroupUpdate.model_dump(exclude_unset=True)``
    so that omitted fields are not touched and fields set to ``None`` are
    cleared (e.g. resetting description or icon to null).
    """
    group = await get_group(group_id, db)
    if group.is_default and "name" in data and data["name"] != group.name:
        raise HTTPException(400, "Cannot rename the default group")
    for field, value in data.items():
        if field in UPDATABLE_GROUP_FIELDS:
            setattr(group, field, value)
    return await GroupRepository(db).save(group)


async def delete_group(db: AsyncSession, group_id: int):
    group = await get_group(group_id, db)
    if group.is_default:
        raise HTTPException(400, "Cannot delete the default group")
    await GroupRepository(db).delete(group)


async def reorder_groups(db: AsyncSession, group_ids: list[int]):
    repo = GroupRepository(db)
    groups = await repo.list_all()
    id_to_group = {g.id: g for g in groups}
    for position, gid in enumerate(group_ids):
        if gid in id_to_group:
            id_to_group[gid].position = position
    await repo.save_all()
    return await repo.list_all()


async def add_assets(db: AsyncSession, group_id: int, asset_ids: list[int]):
    group = await get_group(group_id, db)
    assets = await AssetRepository(db).get_by_ids(asset_ids)
    existing_ids = {a.id for a in group.assets}
    for asset in assets:
        if asset.id not in existing_ids:
            group.assets.append(asset)
    return await GroupRepository(db).save(group)


async def remove_asset(db: AsyncSession, group_id: int, asset_id: int):
    group = await get_group(group_id, db)
    group.assets = [a for a in group.assets if a.id != asset_id]
    return await GroupRepository(db).save(group)
