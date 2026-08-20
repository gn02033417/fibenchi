"""Compatibility cache for fundamentals, without an active external provider.

Taiwan runtime indicators retain the in-memory merge seam so cached values can
still be consumed by existing code, but this build does not fetch or warm
fundamentals from Yahoo or any replacement provider.
"""

from app.schemas.price import IndicatorSnapshotBase, SymbolIndicatorSnapshot
from app.utils import TTLCache

# Per-symbol fundamentals cache: keyed by uppercase symbol, value is
# dict[field, value].  24h TTL since fundamentals change at most daily.
_fundamentals_cache: TTLCache = TTLCache(default_ttl=86400, max_size=500)

# Track in-flight background fetches to avoid duplicate work
_pending_symbols: set[str] = set()


def get_cached_fundamentals(symbols: list[str]) -> dict[str, dict[str, float | None]]:
    """Return cached fundamentals for the given symbols.

    Only symbols that have a cache entry are included in the result.
    Missing symbols are silently omitted.
    """
    result: dict[str, dict[str, float | None]] = {}
    for sym in symbols:
        cached = _fundamentals_cache.get_value(sym.upper())
        if cached is not None:
            result[sym.upper()] = cached
    return result


def get_uncached_symbols(symbols: list[str]) -> list[str]:
    """Return symbols that are NOT in the cache."""
    return [s for s in symbols if _fundamentals_cache.get_value(s.upper()) is None]


async def warm_fundamentals_cache(symbols: list[str]) -> None:
    """Keep the compatibility entry point, but do not perform provider I/O."""
    return


def _schedule_background_fetch(symbols: list[str]) -> None:
    """Retain the seam while preventing background provider calls."""
    return


def merge_fundamentals_from_cache(
    symbols: list[str],
    target: dict[str, IndicatorSnapshotBase],
) -> None:
    """Merge only already-cached fundamentals into snapshots.

    For each symbol in target, if fundamentals are cached, merge them into
    ``target[symbol].values`` (in-place — the snapshots may already sit in
    the indicator cache). Missing symbols remain without fundamentals.
    """
    cached = get_cached_fundamentals(symbols)

    for sym in symbols:
        upper = sym.upper()
        fund = cached.get(upper)
        if fund and sym in target:
            target[sym].values.update(fund)


def merge_fundamentals_into_rows(symbol: str, rows: list) -> None:
    """Merge cached fundamentals into the last indicator row."""
    upper = symbol.upper()
    cached = _fundamentals_cache.get_value(upper)
    if cached and rows:
        rows[-1].values.update(cached)


def merge_fundamentals_into_batch(results: list[SymbolIndicatorSnapshot]) -> None:
    """Merge cached fundamentals into batch indicator snapshots (in place)."""
    cached = get_cached_fundamentals([e.symbol for e in results])
    for entry in results:
        sym = entry.symbol.upper()
        fund = cached.get(sym)
        if fund:
            entry.values.update(fund)
