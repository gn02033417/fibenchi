"""Price provider registry — resolves a provider name to a singleton instance."""

from app.config import settings
from app.services.price_providers.base import PriceProvider
from app.services.price_providers.shioaji import ShioajiPriceProvider

__all__ = [
    "PriceProvider",
    "ShioajiPriceProvider",
    "init_price_provider",
    "get_price_provider",
]

_PROVIDERS: dict[str, type[PriceProvider]] = {
    "shioaji": ShioajiPriceProvider,
}

_instance: PriceProvider | None = None


def init_price_provider() -> None:
    """Instantiate the configured price provider (called once at startup)."""
    global _instance
    name = settings.price_provider
    cls = _PROVIDERS.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown price provider: {name!r}. Available: {list(_PROVIDERS)}"
        )
    _instance = cls()


def get_price_provider() -> PriceProvider:
    """Return the active price provider singleton.

    Raises RuntimeError if init_price_provider() hasn't been called yet.
    """
    if _instance is None:
        raise RuntimeError(
            "Price provider not initialized — call init_price_provider() first"
        )
    return _instance
