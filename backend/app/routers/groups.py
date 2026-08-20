from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import PeriodType
from app.database import get_db
from app.schemas.group import GroupAddAssets, GroupCreate, GroupReorder, GroupResponse, GroupUpdate
from app.schemas.price import IndicatorSnapshotBase, SparklinePointResponse
from app.services import group_service
from app.services.compute.group import compute_and_cache_indicators, get_batch_sparklines

router = APIRouter(prefix="/api/groups", tags=["groups"])


async def _refresh_realtime_demand(request: Request) -> None:
    controller = getattr(request.app.state, "realtime_demand_controller", None)
    if controller is not None:
        await controller.refresh()


@router.get("", response_model=list[GroupResponse], summary="List all groups")
async def list_groups(db: AsyncSession = Depends(get_db)):
    return await group_service.list_groups(db)


@router.post("", response_model=GroupResponse, status_code=201, summary="Create a group")
async def create_group(data: GroupCreate, db: AsyncSession = Depends(get_db)):
    return await group_service.create_group(db, data.name, data.description, data.icon)


@router.put("/reorder", response_model=list[GroupResponse], summary="Reorder groups")
async def reorder_groups(
    data: GroupReorder,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    groups = await group_service.reorder_groups(db, data.group_ids)
    await _refresh_realtime_demand(request)
    return groups


@router.get("/{group_id}", response_model=GroupResponse, summary="Get a group by ID")
async def get_group_detail(group_id: int, db: AsyncSession = Depends(get_db)):
    return await group_service.get_group_detail(db, group_id)


@router.put("/{group_id}", response_model=GroupResponse, summary="Update a group")
async def update_group(
    group_id: int,
    data: GroupUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    changes = data.model_dump(exclude_unset=True)
    group = await group_service.update_group(db, group_id, changes)
    if "realtime_priority" in changes:
        await _refresh_realtime_demand(request)
    return group


@router.delete("/{group_id}", status_code=204, summary="Delete a group")
async def delete_group(group_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    await group_service.delete_group(db, group_id)
    await _refresh_realtime_demand(request)


@router.post("/{group_id}/assets", response_model=GroupResponse, summary="Add assets to a group")
async def add_assets_to_group(
    group_id: int,
    data: GroupAddAssets,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    group = await group_service.add_assets(db, group_id, data.asset_ids)
    await _refresh_realtime_demand(request)
    return group


@router.delete("/{group_id}/assets/{asset_id}", response_model=GroupResponse, summary="Remove an asset from a group")
async def remove_asset_from_group(
    group_id: int,
    asset_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    group = await group_service.remove_asset(db, group_id, asset_id)
    await _refresh_realtime_demand(request)
    return group


@router.get("/{group_id}/sparklines", response_model=dict[str, list[SparklinePointResponse]], summary="Batch close prices for group assets")
async def group_sparklines(
    group_id: int,
    period: PeriodType = Query("3mo"),
    db: AsyncSession = Depends(get_db),
):
    """Return close-price sparkline data for every asset in the group."""
    return await get_batch_sparklines(db, period, group_id=group_id)


@router.get("/{group_id}/indicators", response_model=dict[str, IndicatorSnapshotBase], summary="Batch indicators for group assets")
async def group_indicators(
    group_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Return the latest indicator snapshot for every asset in the group."""
    return await compute_and_cache_indicators(db, group_id=group_id)
