from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SymbolEntry:
    """A single symbol fetched from an exchange data source."""

    symbol: str  # Raw provider symbol; Taiwan entries keep leading zeroes.
    name: str
    exchange: str  # Canonical exchange code or provider display name.
    currency: str
    type: str = "stock"  # "stock" or "etf"


class SymbolProvider(ABC):
    """Abstract base for exchange symbol list providers."""

    @abstractmethod
    async def fetch_symbols(self, config: dict) -> list[SymbolEntry]:
        """Fetch symbol listings from the data source.

        Args:
            config: Provider-specific configuration (e.g. which sub-markets to include).

        Returns:
            List of SymbolEntry objects ready for upsert into symbol_directory.
        """

    @staticmethod
    @abstractmethod
    def available_markets() -> list[dict]:
        """Return the list of selectable sub-markets for the UI.

        Each dict has: {"key": "amsterdam", "label": "Euronext Amsterdam"}
        """
