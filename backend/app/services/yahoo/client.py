"""Single client for all Yahoo Finance access.

Every Yahoo HTTP call in the codebase goes through :data:`yahoo_client`.
That gives us one place to apply the throttle (:mod:`rate_limit`),
quote/holdings caches, and the retry-once-with-fresh-session pattern.

Direct ``from yahooquery import Ticker`` imports anywhere else in the
codebase are a code smell — route the call through this client instead.

The client's behaviour is split across one mixin per concern
(``_quotes.py``, ``_history.py``, …) so each file stays small and
focused. They all reach the upstream library through :meth:`_ticker`,
which is the single place ``Ticker`` is instantiated — tests patch
``app.services.yahoo.client.Ticker`` to substitute the upstream library
across every operation in one shot.
"""

import logging
import threading
import time
from typing import Any, Callable, TypeVar

try:
    from yahooquery import Ticker
except ImportError:  # pragma: no cover - exercised by the Taiwan runtime gate
    Ticker = None  # type: ignore[assignment,misc]

from app.services.yahoo._base import _YahooBase
from app.services.yahoo._earnings import _EarningsMixin
from app.services.yahoo._fundamentals import _FundamentalsMixin
from app.services.yahoo._history import _HistoryMixin
from app.services.yahoo._holdings import _HoldingsMixin
from app.services.yahoo._intraday import _IntradayMixin
from app.services.yahoo._quotes import _QuotesMixin
from app.services.yahoo._search import _SearchMixin
from app.services.yahoo._validation import _ValidationMixin
from app.services.yahoo.rate_limit import (
    CrumbRejected,
    YahooThrottle,
)
from app.services.yahoo.rate_limit import (
    yahoo_throttle as _shared_throttle,
)
from app.utils import TTLCache

logger = logging.getLogger(__name__)

# Quote response cache TTL — slightly longer than the SSE stream's
# market-hours interval (15s) so back-to-back ticks for the same symbol
# set hit the cache instead of going upstream. 12s was too tight: the
# SSE generator's 15s sleep meant cache misses on every tick.
QUOTE_CACHE_TTL = 16.0

# Holdings change at most quarterly, so a long TTL is safe and saves
# many Yahoo round trips.
HOLDINGS_CACHE_TTL = 86_400  # 24h

# How long to keep one ``Ticker`` (and its underlying ``curl_cffi`` session,
# crumb, and consent cookies) alive before forcing a fresh one. Reusing the
# session lets every ``_call`` after the first skip the consent + crumb
# bootstrap (~2 HTTP calls saved per call). Refreshing periodically rotates
# the random browser fingerprint and renews the crumb before Yahoo expires it.
SESSION_TTL = 600.0  # 10 min

_T = TypeVar("_T")


class YahooClient(
    _QuotesMixin,
    _HistoryMixin,
    _FundamentalsMixin,
    _ValidationMixin,
    _HoldingsMixin,
    _SearchMixin,
    _EarningsMixin,
    _IntradayMixin,
    _YahooBase,
):
    """Single point of access for Yahoo Finance.

    Owns the throttle, retry policy, and provider-side caches; per-
    concern operations live on the inherited mixin classes.
    """

    def __init__(
        self,
        throttle: YahooThrottle | None = None,
        quote_cache_ttl: float = QUOTE_CACHE_TTL,
        holdings_cache_ttl: float = HOLDINGS_CACHE_TTL,
        session_ttl: float = SESSION_TTL,
    ):
        self._throttle = throttle or _shared_throttle
        self._quote_cache = TTLCache(default_ttl=quote_cache_ttl, thread_safe=True)
        self._holdings_cache = TTLCache(
            default_ttl=holdings_cache_ttl, max_size=100, thread_safe=True,
        )
        self._session_ttl = session_ttl
        self._session_lock = threading.Lock()
        self._cached_ticker: Any | None = None
        self._session_created_at: float = 0.0

    def _ticker(self, symbols: list[str] | str) -> Any:
        """Return a ``Ticker`` for ``symbols``, reusing the underlying
        session/crumb across calls.

        Yahoo's auth handshake (consent + crumb) costs 2-3 HTTP requests.
        Holding one ``Ticker`` and mutating its ``symbols`` property lets
        every subsequent ``_call`` skip that overhead. The session is
        refreshed every :data:`SESSION_TTL` seconds (rotates the random
        browser fingerprint and renews the crumb before Yahoo expires
        it) and on demand via :meth:`_invalidate_session` (e.g. when a
        ``CrumbRejected`` indicates the crumb has gone stale).
        """
        with self._session_lock:
            now = time.monotonic()
            expired = now - self._session_created_at > self._session_ttl
            if self._cached_ticker is None or expired:
                if Ticker is None:
                    raise RuntimeError("The legacy Yahoo provider requires the optional yahooquery package")
                self._cached_ticker = Ticker(symbols)
                self._session_created_at = now
            else:
                self._cached_ticker.symbols = symbols
            return self._cached_ticker

    def _invalidate_session(self) -> None:
        """Drop the cached ``Ticker`` so the next ``_ticker()`` call
        builds a fresh session, crumb, and browser fingerprint."""
        with self._session_lock:
            self._cached_ticker = None
            self._session_created_at = 0.0

    def _call(
        self,
        fetch: Callable[[], _T],
        fallback: Callable[[], _T],
        *,
        retries: int = 1,
    ) -> _T:
        """Run ``fetch`` under the throttle and circuit breaker.

        - If the breaker is tripped, returns ``fallback()`` immediately.
        - Otherwise waits for throttle clearance, then runs ``fetch``.
        - On :class:`CrumbRejected`, retries up to ``retries`` more times
          (each preceded by a fresh throttle wait) before tripping the
          breaker and returning ``fallback()``.
        - Any other exception propagates so transient errors aren't masked.
        """
        if self._throttle.is_blocked():
            return fallback()

        for attempt in range(retries + 1):
            self._throttle.wait()
            try:
                result = fetch()
            except CrumbRejected:
                self._invalidate_session()
                if attempt < retries:
                    logger.warning(
                        "Yahoo crumb rejected — retry %d/%d with fresh session",
                        attempt + 1, retries,
                    )
                    continue
                self._throttle.record_invalid_crumb()
                return fallback()
            self._throttle.record_success()
            return result

        return fallback()  # unreachable; quiets the type checker


# Process-wide singleton — every consumer imports this.
yahoo_client = YahooClient()


__all__ = [
    "QUOTE_CACHE_TTL",
    "HOLDINGS_CACHE_TTL",
    "YahooClient",
    "yahoo_client",
]
