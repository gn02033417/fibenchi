"""Yahoo symbol search on :class:`YahooClient`."""

import asyncio
from typing import Any

try:
    from yahooquery import search as _yq_search
except ImportError:  # pragma: no cover - exercised by the Taiwan runtime gate
    _yq_search = None

from app.services.yahoo._base import _YahooBase


class _SearchMixin(_YahooBase):
    async def search(self, query: str, **kwargs: Any) -> dict:
        """Search Yahoo Finance for ticker symbols. Returns Yahoo's raw payload."""
        if _yq_search is None:
            return {}

        def _fetch() -> dict:
            return _yq_search(query, **kwargs)

        return await asyncio.to_thread(self._call, _fetch, lambda: {})
