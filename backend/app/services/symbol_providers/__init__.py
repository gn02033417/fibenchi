"""Symbol provider registry — maps provider_type strings to provider classes."""

from app.services.symbol_providers.base import SymbolEntry, SymbolProvider
from app.services.symbol_providers.euronext import EuronextProvider
from app.services.symbol_providers.tpex import TPEXProvider, TPExProvider
from app.services.symbol_providers.twse import TWSEProvider
from app.services.symbol_providers.xetra import XetraProvider

__all__ = [
    "SymbolEntry",
    "SymbolProvider",
    "TPEXProvider",
    "TPExProvider",
    "TWSEProvider",
    "get_provider",
    "get_available_providers",
]

_PROVIDERS: dict[str, type[SymbolProvider]] = {
    "euronext": EuronextProvider,
    "tpex": TPEXProvider,
    "twse": TWSEProvider,
    "xetra": XetraProvider,
}


def get_provider(provider_type: str) -> SymbolProvider:
    """Instantiate a provider by its type key."""
    cls = _PROVIDERS.get(provider_type)
    if cls is None:
        raise ValueError(f"Unknown provider type: {provider_type!r}. Available: {list(_PROVIDERS)}")
    return cls()


def get_available_providers() -> dict[str, dict]:
    """Return metadata about all registered providers for the UI."""
    result = {}
    for key, cls in _PROVIDERS.items():
        provider = cls()
        result[key] = {
            "key": key,
            "label": key.title(),
            "markets": provider.available_markets(),
        }
    return result
