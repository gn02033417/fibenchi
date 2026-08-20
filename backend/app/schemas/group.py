import datetime

from pydantic import BaseModel, Field

from app.schemas.asset import AssetResponse


class GroupCreate(BaseModel):
    name: str = Field(max_length=100, description="Unique group name")
    description: str | None = Field(default=None, max_length=500, description="Optional group description")
    icon: str | None = Field(default=None, max_length=50, description="Lucide icon name (e.g. 'briefcase', 'globe')")


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=100, description="New group name")
    description: str | None = Field(default=None, max_length=500, description="New description")
    icon: str | None = Field(default=None, max_length=50, description="Lucide icon name")
    realtime_priority: bool | None = Field(
        default=None,
        description="Whether assets in this group receive realtime priority",
    )


class GroupReorder(BaseModel):
    group_ids: list[int] = Field(description="Ordered list of group IDs (position derived from index)")


class GroupAddAssets(BaseModel):
    asset_ids: list[int] = Field(description="List of asset IDs to add to the group")


class GroupResponse(BaseModel):
    id: int = Field(description="Group ID")
    name: str = Field(description="Group name")
    description: str | None = Field(description="Group description")
    icon: str | None = Field(description="Lucide icon name")
    is_default: bool = Field(description="Whether this is the protected default group (Watchlist)")
    realtime_priority: bool = Field(default=False, description="Whether assets in this group receive realtime priority")
    position: int = Field(description="Display order position (0 = first)")
    created_at: datetime.datetime = Field(description="Creation timestamp")
    assets: list[AssetResponse] = Field(default=[], description="Assets in this group")

    model_config = {"from_attributes": True}
