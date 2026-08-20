"""Bounded, diff-based reconciliation for the Shioaji Quote subscription pool."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Protocol

from app.config import settings
from app.schemas.quote import Quote
from app.services.live_quote_store import LiveQuoteStore
from app.services.shioaji.client import ShioajiClientError
from app.services.shioaji.stream import ShioajiQuoteSubscription

logger = logging.getLogger(__name__)


class QuoteStream(Protocol):
    async def subscribe(self, subscription: ShioajiQuoteSubscription) -> None: ...

    async def unsubscribe(self, subscription: ShioajiQuoteSubscription) -> None: ...

    def quote_events(self) -> AsyncIterator[Quote]: ...


WantedProvider = Callable[
    [],
    Iterable[ShioajiQuoteSubscription] | Awaitable[Iterable[ShioajiQuoteSubscription]],
]


@dataclass(frozen=True, slots=True)
class SubscriptionDiff:
    """The exact sidecar operations completed by one reconciliation."""

    subscribed: tuple[str, ...]
    unsubscribed: tuple[str, ...]
    wanted: tuple[str, ...]


class SubscriptionManager:
    """Maintain one bounded Quote subscription set and restore it after reconnects."""

    HARD_MAX_SUBSCRIPTIONS = 200

    def __init__(
        self,
        stream: QuoteStream,
        store: LiveQuoteStore,
        *,
        max_subscriptions: int | None = None,
        reconnect_initial_delay: float = 1.0,
        reconnect_max_delay: float = 30.0,
    ) -> None:
        limit = settings.shioaji_max_subscriptions if max_subscriptions is None else max_subscriptions
        if not 1 <= limit <= self.HARD_MAX_SUBSCRIPTIONS:
            raise ValueError("max_subscriptions must be between 1 and 200")
        if reconnect_initial_delay <= 0 or reconnect_max_delay < reconnect_initial_delay:
            raise ValueError("invalid reconnect delay bounds")
        self._stream = stream
        self._store = store
        self._max_subscriptions = limit
        self._reconnect_initial_delay = reconnect_initial_delay
        self._reconnect_max_delay = reconnect_max_delay
        self._current: dict[str, ShioajiQuoteSubscription] = {}

    @property
    def current_symbols(self) -> tuple[str, ...]:
        return tuple(self._current)

    async def reconcile(
        self,
        wanted: Iterable[ShioajiQuoteSubscription],
    ) -> SubscriptionDiff:
        """Apply only the subscribe/unsubscribe operations required by ``wanted``."""
        target = self._bounded_target(wanted)
        to_unsubscribe = [
            subscription
            for symbol, subscription in self._current.items()
            if symbol not in target
        ]
        to_subscribe = [
            subscription
            for symbol, subscription in target.items()
            if symbol not in self._current
        ]

        # Free slots before adding replacements so the upstream cap is never exceeded.
        for subscription in to_unsubscribe:
            await self._stream.unsubscribe(subscription)
            self._current.pop(subscription.code, None)
        if to_unsubscribe:
            await self._store.mark_cached(subscription.code for subscription in to_unsubscribe)

        for subscription in to_subscribe:
            await self._stream.subscribe(subscription)
            self._current[subscription.code] = subscription

        return SubscriptionDiff(
            subscribed=tuple(subscription.code for subscription in to_subscribe),
            unsubscribed=tuple(subscription.code for subscription in to_unsubscribe),
            wanted=tuple(target),
        )

    async def mark_disconnected(self) -> None:
        """Keep last-known values but make current upstream loss explicit."""
        await self._store.mark_disconnected(tuple(self._current))
        self._current.clear()

    async def restore_after_reconnect(self, wanted_provider: WantedProvider) -> SubscriptionDiff:
        """Recompute desired subscriptions because demand may have changed while offline."""
        self._current.clear()
        return await self.reconcile(await _resolve_wanted(wanted_provider))

    async def run_forever(self, wanted_provider: WantedProvider) -> None:
        """Consume one upstream SSE connection, reconnecting only after it fails or closes."""
        delay = self._reconnect_initial_delay
        while True:
            try:
                await self.restore_after_reconnect(wanted_provider)
                async for quote in self._stream.quote_events():
                    await self._store.update(quote)
                    delay = self._reconnect_initial_delay
                raise ShioajiStreamDisconnected("Shioaji Quote SSE stream closed")
            except asyncio.CancelledError:
                raise
            except (ShioajiClientError, ShioajiStreamDisconnected) as exc:
                logger.warning("Shioaji Quote SSE disconnected: %s", exc)
                await self.mark_disconnected()
                await asyncio.sleep(delay)
                delay = min(delay * 2, self._reconnect_max_delay)
            else:
                delay = self._reconnect_initial_delay

    def _bounded_target(
        self,
        wanted: Iterable[ShioajiQuoteSubscription],
    ) -> dict[str, ShioajiQuoteSubscription]:
        target: dict[str, ShioajiQuoteSubscription] = {}
        for subscription in wanted:
            if not isinstance(subscription, ShioajiQuoteSubscription):
                raise TypeError("wanted subscriptions must be ShioajiQuoteSubscription values")
            if subscription.code in target:
                continue
            target[subscription.code] = subscription
            if len(target) == self._max_subscriptions:
                break
        return target


class ShioajiStreamDisconnected(ShioajiClientError):
    """The upstream Quote SSE stream ended and needs a reconnect."""


async def _resolve_wanted(wanted_provider: WantedProvider) -> Iterable[ShioajiQuoteSubscription]:
    result = wanted_provider()
    if inspect.isawaitable(result):
        return await result
    return result


__all__ = [
    "ShioajiStreamDisconnected",
    "SubscriptionDiff",
    "SubscriptionManager",
]
