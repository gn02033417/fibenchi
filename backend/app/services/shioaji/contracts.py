"""Normalize Shioaji STK contracts into the Taiwan reference-sync seam."""

from dataclasses import dataclass
from typing import Literal

from app.services.shioaji.client import (
    ShioajiClient,
    ShioajiClientError,
    ShioajiContract,
    ShioajiContractsPage,
)


class ShioajiContractSyncError(RuntimeError):
    """A contract sync could not produce a safe replacement set."""


@dataclass(frozen=True, slots=True)
class TaiwanContract:
    """A verified Taiwan stock contract; stock-vs-ETF is intentionally absent."""

    code: str
    exchange: Literal["TSE", "OTC"]


class ShioajiContractsAdapter:
    """Retrieve and filter STK contracts without treating filtering as classification."""

    _MAX_PAGES = 10_000

    def __init__(self, client: ShioajiClient):
        self.client = client

    async def fetch_stk(self, *, page_size: int | None = None) -> list[TaiwanContract]:
        if page_size is not None and page_size <= 0:
            raise ValueError("page_size must be greater than zero")

        contracts = await self._retrieve_contracts(page_size=page_size)
        results = self._normalize(contracts)
        if not results:
            raise ShioajiContractSyncError("contract retrieval returned no usable TSE/OTC STK contracts")
        return results

    async def _retrieve_contracts(self, *, page_size: int | None) -> list[ShioajiContract]:
        if page_size is None:
            page = await self._request_page()
            return page.contracts

        all_contracts: list[ShioajiContract] = []
        page_number = 1
        while True:
            page = await self._request_page(page=page_number, page_size=page_size)
            if not page.contracts:
                if page_number == 1:
                    return []
                break

            all_contracts.extend(page.contracts)
            if page.max_page is not None and page_number >= page.max_page:
                break
            if page.total is not None and len(all_contracts) >= page.total:
                break
            if page.max_page is None and page.total is None and len(page.contracts) < page_size:
                break

            page_number += 1
            if page_number > self._MAX_PAGES:
                raise ShioajiContractSyncError("contract retrieval exceeded the pagination safety limit")
        return all_contracts

    async def _request_page(
        self,
        *,
        page: int | None = None,
        page_size: int | None = None,
    ) -> ShioajiContractsPage:
        try:
            return await self.client.list_contracts("STK", page=page, page_size=page_size)
        except ShioajiClientError as exc:
            raise ShioajiContractSyncError("contract retrieval failed") from exc

    @staticmethod
    def _normalize(contracts: list[ShioajiContract]) -> list[TaiwanContract]:
        results: list[TaiwanContract] = []
        seen: set[tuple[str, str]] = set()

        for contract in contracts:
            security_type = contract.security_type.strip().upper()
            region = contract.region.strip().upper() if contract.region is not None else None
            exchange = contract.exchange.strip().upper()
            code = contract.code.strip()
            if not security_type or not exchange or not code or region == "":
                raise ShioajiContractSyncError("malformed contract record")
            if security_type != "STK" or (region is not None and region != "TW"):
                continue
            if exchange not in {"TSE", "OTC"}:
                continue

            identity = (exchange, code)
            if identity in seen:
                continue
            seen.add(identity)
            results.append(TaiwanContract(code=code, exchange=exchange))
        return results


async def fetch_stk_contracts(
    client: ShioajiClient,
    *,
    page_size: int | None = None,
) -> list[TaiwanContract]:
    """Fetch a safe STK contract set in full or paginated mode."""
    return await ShioajiContractsAdapter(client).fetch_stk(page_size=page_size)
