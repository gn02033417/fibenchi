"""Connection-lifetime coverage for browser realtime demand."""

from unittest.mock import AsyncMock

import pytest

from app.services.realtime_demand import RealtimeDemandController

pytestmark = pytest.mark.asyncio(loop_scope="function")


async def test_registering_and_leaving_views_updates_the_aggregate_demand():
    refresh = AsyncMock()
    controller = RealtimeDemandController(refresh)

    assert await controller.snapshot() == controller_snapshot()

    async with controller.register(active_assets=("2330", " 0050 "), active_group_ids=(7, 7)):
        assert await controller.snapshot() == controller_snapshot(("0050", "2330"), (7,))
        async with controller.register(active_assets=("2317",), active_group_ids=(2,)):
            assert await controller.snapshot() == controller_snapshot(("0050", "2317", "2330"), (2, 7))
        assert await controller.snapshot() == controller_snapshot(("0050", "2330"), (7,))

    assert await controller.snapshot() == controller_snapshot()
    assert refresh.await_count == 4


def controller_snapshot(active_assets: tuple[str, ...] = (), active_group_ids: tuple[int, ...] = ()):
    from app.services.realtime_demand import RealtimeDemandSnapshot

    return RealtimeDemandSnapshot(
        active_assets=active_assets,
        active_group_ids=active_group_ids,
    )
