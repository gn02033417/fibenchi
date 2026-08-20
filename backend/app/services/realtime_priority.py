"""Pure, deterministic selection for the bounded Shioaji subscription pool."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from app.config import settings


def compute_wanted_symbols(
    *,
    active_asset: str | None = None,
    realtime_priority_groups: Sequence[Iterable[str]] = (),
    active_group_symbols: Iterable[str] = (),
    recent_symbols: Iterable[str] = (),
    tracked_symbols: Iterable[str] = (),
    cap: int | None = None,
) -> list[str]:
    """Return the deterministic, de-duplicated subscription wanted set.

    Priority is active asset, realtime-priority groups (in caller-supplied
    stable group order), active group, recent symbols, then all remaining
    tracked symbols. Ties within every non-recency tier sort by raw symbol;
    ``recent_symbols`` preserves its caller-provided newest-first order.
    """
    limit = settings.shioaji_max_subscriptions if cap is None else cap
    if limit <= 0:
        raise ValueError("subscription cap must be greater than zero")

    selected: list[str] = []
    seen: set[str] = set()

    def add(symbols: Iterable[str], *, preserve_order: bool) -> None:
        candidates = _ordered_symbols(symbols) if preserve_order else _sorted_symbols(symbols)
        for symbol in candidates:
            if symbol in seen:
                continue
            seen.add(symbol)
            selected.append(symbol)
            if len(selected) == limit:
                return

    if active_asset is not None:
        add((active_asset,), preserve_order=True)
    for group_symbols in realtime_priority_groups:
        if len(selected) == limit:
            return selected
        add(group_symbols, preserve_order=False)
    if len(selected) < limit:
        add(active_group_symbols, preserve_order=False)
    if len(selected) < limit:
        add(recent_symbols, preserve_order=True)
    if len(selected) < limit:
        add(tracked_symbols, preserve_order=False)
    return selected


def _sorted_symbols(symbols: Iterable[str]) -> list[str]:
    return sorted({_normalize_symbol(symbol) for symbol in symbols if _normalize_symbol(symbol)})


def _ordered_symbols(symbols: Iterable[str]) -> list[str]:
    if isinstance(symbols, (set, frozenset)):
        return _sorted_symbols(symbols)

    result: list[str] = []
    seen: set[str] = set()
    for raw_symbol in symbols:
        symbol = _normalize_symbol(raw_symbol)
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        result.append(symbol)
    return result


def _normalize_symbol(symbol: str) -> str:
    return str(symbol).strip().upper()


__all__ = ["compute_wanted_symbols"]
