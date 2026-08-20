"""Connection-scoped browser demand for the bounded realtime quote pool."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass

logger = logging.getLogger(__name__)

RefreshCallback = Callable[[], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class RealtimeDemandSnapshot:
    """The union of active browser views at one point in time."""

    active_assets: tuple[str, ...] = ()
    active_group_ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class _RealtimeDemand:
    active_assets: tuple[str, ...]
    active_group_ids: tuple[int, ...]


class RealtimeDemandController:
    """Register SSE-view demand and reconcile subscriptions whenever it changes."""

    def __init__(self, refresh_callback: RefreshCallback) -> None:
        self._refresh_callback = refresh_callback
        self._demands: dict[object, _RealtimeDemand] = {}
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def register(
        self,
        *,
        active_assets: Iterable[str] = (),
        active_group_ids: Iterable[int] = (),
    ) -> AsyncIterator[None]:
        demand = _RealtimeDemand(
            active_assets=_normalize_symbols(active_assets),
            active_group_ids=_normalize_group_ids(active_group_ids),
        )
        if not demand.active_assets and not demand.active_group_ids:
            yield
            return

        token = object()
        async with self._lock:
            self._demands[token] = demand
        await self.refresh()
        try:
            yield
        finally:
            async with self._lock:
                removed = self._demands.pop(token, None) is not None
            if removed:
                await self.refresh()

    async def snapshot(self) -> RealtimeDemandSnapshot:
        async with self._lock:
            active_assets = tuple(sorted({symbol for demand in self._demands.values() for symbol in demand.active_assets}))
            active_group_ids = tuple(sorted({group_id for demand in self._demands.values() for group_id in demand.active_group_ids}))
        return RealtimeDemandSnapshot(
            active_assets=active_assets,
            active_group_ids=active_group_ids,
        )

    async def refresh(self) -> None:
        """Reconcile without making a browser SSE connection fail on an upstream error."""
        try:
            await self._refresh_callback()
        except Exception:
            logger.exception("Could not refresh Shioaji subscriptions after realtime demand changed")


def _normalize_symbols(symbols: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()}))


def _normalize_group_ids(group_ids: Iterable[int]) -> tuple[int, ...]:
    normalized: set[int] = set()
    for value in group_ids:
        try:
            group_id = int(value)
        except (TypeError, ValueError):
            continue
        if group_id > 0:
            normalized.add(group_id)
    return tuple(sorted(normalized))


__all__ = ["RealtimeDemandController", "RealtimeDemandSnapshot"]
