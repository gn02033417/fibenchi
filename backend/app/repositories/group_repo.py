from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Group


class GroupRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all(self) -> list[Group]:
        result = await self.db.execute(
            select(Group).order_by(Group.position, Group.name)
        )
        return list(result.scalars().all())

    async def list_realtime_priority_groups(self) -> list[Group]:
        """Priority groups in the same stable order used by the UI."""
        result = await self.db.execute(
            select(Group)
            .where(Group.realtime_priority.is_(True))
            .order_by(Group.position, Group.name)
        )
        return list(result.scalars().all())

    async def get_default(self) -> Group | None:
        result = await self.db.execute(
            select(Group).where(Group.is_default.is_(True))
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, group_id: int) -> Group | None:
        result = await self.db.execute(
            select(Group).where(Group.id == group_id)
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Group | None:
        result = await self.db.execute(
            select(Group).where(Group.name == name)
        )
        return result.scalar_one_or_none()

    async def create(self, **kwargs) -> Group:
        group = Group(**kwargs)
        self.db.add(group)
        await self.db.commit()
        await self.db.refresh(group)
        return group

    async def save(self, group: Group) -> Group:
        await self.db.commit()
        await self.db.refresh(group)
        return group

    async def save_all(self) -> None:
        await self.db.commit()

    async def delete(self, group: Group) -> None:
        await self.db.delete(group)
        await self.db.commit()
