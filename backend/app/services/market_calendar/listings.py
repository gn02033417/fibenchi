"""Venue trait data — pure tables, no behavior.

Everything venue-specific that isn't a schedule computation lives here, so
adding or correcting a venue is a data edit that cannot change logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True)
class Listing:
    """Venue traits of a Yahoo exchange suffix: trading calendar + currency.

    ``calendar`` is None for venues exchange_calendars doesn't model (their
    symbols keep the business-day fallback); ``currency`` is the *venue*
    currency, used only as a fallback when Yahoo doesn't report one (see
    ``resolve_currency`` — subunits like GBp are Yahoo-side and handled there).
    """

    calendar: str | None
    currency: str | None


# The one venue table: Yahoo suffix (the part after the last '.') →
# (exchange_calendars name, ISO 4217 currency). Formerly two independently
# maintained tables (SUFFIX_CALENDARS here, EXCHANGE_CURRENCY_MAP in
# yahoo/currency.py) over the same key space.
SUFFIX_LISTINGS: dict[str, Listing] = {
    # Euronext
    "AS": Listing("XAMS", "EUR"),   # Amsterdam
    "BR": Listing("XBRU", "EUR"),   # Brussels
    "PA": Listing("XPAR", "EUR"),   # Paris
    "LS": Listing("XLIS", "EUR"),   # Lisbon
    "IR": Listing("XDUB", "EUR"),   # Dublin
    # Rest of Europe
    "DE": Listing("XETR", "EUR"),   # Xetra
    "F": Listing("XFRA", "EUR"),    # Frankfurt floor
    "MI": Listing("XMIL", "EUR"),   # Borsa Italiana
    "L": Listing("XLON", "GBP"),    # London
    "IL": Listing("XLON", "GBP"),   # London IOB
    "SW": Listing("XSWX", "CHF"),   # SIX Swiss
    "MC": Listing("XMAD", "EUR"),   # Madrid
    "VI": Listing("XWBO", "EUR"),   # Vienna
    "ST": Listing("XSTO", "SEK"),   # Stockholm
    "HE": Listing("XHEL", "EUR"),   # Helsinki
    "OL": Listing("XOSL", "NOK"),   # Oslo
    "CO": Listing("XCSE", "DKK"),   # Copenhagen
    "IC": Listing("XICE", "ISK"),   # Iceland
    "WA": Listing("XWAR", "PLN"),   # Warsaw
    "PR": Listing("XPRA", "CZK"),   # Prague
    "BD": Listing("XBUD", "HUF"),   # Budapest
    "AT": Listing("ASEX", "EUR"),   # Athens
    "IS": Listing("XIST", "TRY"),   # Istanbul
    # Middle East & Africa
    "TA": Listing("XTAE", "ILS"),   # Tel Aviv
    "SR": Listing("XSAU", "SAR"),   # Saudi (Tadawul)
    "QA": Listing(None, "QAR"),     # Qatar — no exchange_calendars calendar
    "JO": Listing("XJSE", "ZAR"),   # Johannesburg
    # Americas
    "TO": Listing("XTSE", "CAD"),   # Toronto
    "V": Listing("XTSE", "CAD"),    # TSX Venture — shares Toronto's schedule
    "MX": Listing("XMEX", "MXN"),   # Mexico
    "SA": Listing("BVMF", "BRL"),   # São Paulo
    "BA": Listing("XBUE", "ARS"),   # Buenos Aires
    "SN": Listing("XSGO", "CLP"),   # Santiago
    # Asia-Pacific
    "T": Listing("XTKS", "JPY"),    # Tokyo
    "HK": Listing("XHKG", "HKD"),   # Hong Kong
    "SS": Listing("XSHG", "CNY"),   # Shanghai
    "SZ": Listing("XSHG", "CNY"),   # Shenzhen — no own calendar; same holidays
    "KS": Listing("XKRX", "KRW"),   # Korea (KOSPI)
    "KQ": Listing("XKRX", "KRW"),   # KOSDAQ (same holidays)
    "TW": Listing("XTAI", "TWD"),   # Taiwan (TWSE)
    "TWO": Listing("XTAI", "TWD"),  # Taiwan OTC (same holidays)
    "SI": Listing("XSES", "SGD"),   # Singapore
    "AX": Listing("XASX", "AUD"),   # Australia
    "NZ": Listing("XNZE", "NZD"),   # New Zealand
    "JK": Listing("XIDX", "IDR"),   # Jakarta
    "BK": Listing("XBKK", "THB"),   # Bangkok
    # South Asia
    "NS": Listing("XBOM", "INR"),   # NSE India — XBOM (BSE) shares holidays
    "BO": Listing("XBOM", "INR"),   # BSE India
}

# Stored Taiwan assets carry verified exchange metadata instead of a Yahoo
# suffix. Both supported venues share the XTAI calendar and TWD quotation.
EXCHANGE_LISTINGS: dict[str, Listing] = {
    "TSE": Listing("XTAI", "TWD"),
    "OTC": Listing("XTAI", "TWD"),
}

# Common Yahoo index symbols → calendar of the venue they track.
INDEX_CALENDARS: dict[str, str] = {
    "^AEX": "XAMS",
    "^BFX": "XBRU",
    "^FCHI": "XPAR",
    "^GDAXI": "XETR",
    "^STOXX50E": "XETR",
    "^FTSE": "XLON",
    "^SSMI": "XSWX",
    "^IBEX": "XMAD",
    "^GSPC": "XNYS",
    "^DJI": "XNYS",
    "^IXIC": "XNYS",
    "^NDX": "XNYS",
    "^RUT": "XNYS",
    "^VIX": "XNYS",
    "^N225": "XTKS",
    "^HSI": "XHKG",
}

# Indices quoted as a rate rather than a level: the number *is* a percentage,
# so "4.63" means 4.63%, not 4.63 points and certainly not $4.63. Every other
# index is a level in points and carries no unit at all.
#
# This lived in the frontend as a hardcoded set in format.ts, which meant a
# yield index outside those four rendered as bare points with no way for the
# user to say otherwise. It's venue-adjacent trait data keyed by symbol, same
# as INDEX_CALENDARS above, so it belongs in the same table file.
PERCENT_QUOTED_INDICES: frozenset[str] = frozenset({
    "^TYX",   # CBOE 30-year Treasury yield
    "^TNX",   # CBOE 10-year Treasury yield
    "^FVX",   # CBOE 5-year Treasury yield
    "^IRX",   # CBOE 13-week T-bill rate
})

# Unsuffixed Yahoo symbols are US listings (NYSE/NASDAQ share the holiday set).
DEFAULT_US_CALENDAR = "XNYS"

# Quote currencies Yahoo uses in crypto pair symbols (BTC-USD, ETH-EUR, SOL-BTC).
# A hyphen alone is NOT crypto — US class shares (BRK-B, BF-B) and preferreds
# (BAC-PL) are hyphenated too; those must fall through to the US default.
# European share classes carry a suffix after the hyphenated part (NOVO-B.CO),
# so the '.' branch resolves them before the hyphen could matter.
CRYPTO_QUOTE_CURRENCIES = frozenset({
    "USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "BTC", "ETH", "USDT", "USDC",
})
# The fiat subset — a BTC-quoted pair has no meaningful display currency.
FIAT_QUOTES = frozenset({"USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF"})


@dataclass(frozen=True)
class ExtendedHours:
    """A venue's extended-trading window, anchored to the regular session.

    ``pre_offset`` — how long before the regular open premarket starts;
    ``post_offset`` — how long after the regular close aftermarket ends.
    Anchoring to the *actual* schedule (not wall-clock constants) keeps
    half-days correct: on a US early-close day (13:00 ET) aftermarket ends
    17:00 ET, and DST is handled because the calendar's open/close move.
    """

    pre_offset: timedelta
    post_offset: timedelta


# Venues with a real extended-hours session, keyed by calendar name — a data
# table, not per-ticker conditionals. US listings: premarket 4:00 ET
# (= open − 5:30), aftermarket until 20:00 ET (= close + 4:00), matching the
# window Yahoo's PRE/POST market states cover. European venues have auction
# phases, not retail extended sessions, so they are deliberately absent.
EXTENDED_HOURS: dict[str, ExtendedHours] = {
    "XNYS": ExtendedHours(
        pre_offset=timedelta(hours=5, minutes=30), post_offset=timedelta(hours=4)
    ),
}
