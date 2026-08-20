"""Disabled earnings cache for the pure Taiwan build.

The cache object remains as a compatibility seam for callers that still clear
legacy state, but this module has no external provider and never fetches data.
"""

from app.utils import TTLCache

_earnings_cache: TTLCache = TTLCache(default_ttl=86400, max_size=500, thread_safe=True)


async def get_earnings(symbol: str) -> dict[str, object] | None:
    """Return an explicitly pre-seeded compatibility value, if present."""
    upper = symbol.upper()
    return _earnings_cache.get_value(upper)
