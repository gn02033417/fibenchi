"""AssetRef — the domain identity of an asset.

One object for both faces of "an asset" in application code: the ticker
with its venue traits, and (optionally) the stored row it belongs to.
"""

from __future__ import annotations

from functools import cached_property

from app.domain.instrument import AssetKind, Instrument, UnitKind, classify
from app.services.market_calendar.venue import Venue, _venue_for


class AssetRef(str):
    """A Yahoo ticker that knows its venue traits, optionally bound to its
    stored asset id: ``AssetRef("IWDA.AS").venue``, ``AssetRef.of(asset).id``.

    A ``str`` subclass, so it drops in anywhere a plain symbol string is
    used (dict keys, comparisons, serialization, provider calls) — equality
    and hashing are the ticker's, and ``id`` is metadata that never affects
    them. Note that str operations (``.upper()`` etc.) return plain ``str``
    — re-wrap if you still need the traits afterwards.

    Deliberately not the ORM ``Asset``: batch loops isolate per-symbol
    failures with rollbacks, and a rollback expires every live instance in
    the session — touching an expired attribute then raises
    ``MissingGreenlet`` (the 2026-08-05 hole-heal crash). An ``AssetRef``
    is captured once while the row is live (``AssetRef.of(asset)``) and is
    immune by construction.

    Venue resolution is cached on the instance; the Venue itself is shared
    per calendar. Ticker shape is only ever interpreted in
    ``app.domain.instrument.classify``.
    """

    id: int | None
    _exchange: str | None
    _stored_currency: str | None

    def __new__(
        cls,
        ticker: str,
        id: int | None = None,
        *,
        exchange: str | None = None,
        currency: str | None = None,
    ) -> AssetRef:
        self = super().__new__(cls, ticker)
        self.id = id
        self._exchange = exchange.upper().strip() if exchange else None
        self._stored_currency = currency
        return self

    @classmethod
    def of(cls, asset) -> AssetRef:
        """Build from anything with ``symbol`` and ``id`` attributes (an ORM
        ``Asset`` — while it's live — or another ref)."""
        return cls(
            asset.symbol,
            asset.id,
            exchange=getattr(asset, "exchange", None),
            currency=getattr(asset, "currency", None),
        )

    @property
    def symbol(self) -> str:
        """The ticker — i.e. the string itself. Exists so anything shaped
        like an asset (ORM ``Asset``, this ref) exposes the same
        ``symbol``/``id`` pair, which is what ``of`` duck-types on."""
        return str(self)

    @property
    def exchange(self) -> str | None:
        """Verified stored venue metadata, when this ref came from an asset."""
        return self._exchange

    def __repr__(self) -> str:
        if self.id is None:
            return f"AssetRef({str.__repr__(self)})"
        return f"AssetRef({str.__repr__(self)}, id={self.id})"

    @cached_property
    def _instrument(self) -> Instrument:
        return classify(
            self,
            exchange=self._exchange,
            currency=self._stored_currency,
        )

    @property
    def kind(self) -> AssetKind:
        """What kind of instrument the ticker's shape says this is —
        ``ref.kind.is_future`` etc., never re-inspect the characters."""
        return self._instrument.kind

    @property
    def unit(self) -> UnitKind:
        """How this ticker's price number should be read (currency/percent/
        points) — the shape's recommendation, not the stored choice."""
        return self._instrument.unit

    @property
    def calendar_name(self) -> str | None:
        """The exchange_calendars name for this ticker, or None."""
        return self._instrument.calendar

    @property
    def currency(self) -> str | None:
        """The venue/pair currency inferred from ticker shape, or None.

        A fallback only — Yahoo's own currency field wins when present (see
        ``resolve_currency``); this answers when Yahoo doesn't.
        """
        return self._instrument.currency

    @cached_property
    def venue(self) -> Venue | None:
        """This ticker's trading venue, or None when it can't be resolved."""
        name = self.calendar_name
        return _venue_for(name) if name else None
