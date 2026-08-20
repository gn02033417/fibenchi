"""Merge official Taiwan reference rows with Shioaji contract availability."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.symbol_directory import TAIWAN_EXCHANGES, SymbolDirectory
from app.services.shioaji.client import ShioajiClient
from app.services.shioaji.contracts import TaiwanContract, fetch_stk_contracts
from app.services.symbol_providers import get_provider
from app.services.symbol_providers.base import SymbolEntry, SymbolProvider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TaiwanSymbolDirectorySyncResult:
    status: Literal["success", "failed"]
    reference_count: int = 0
    contract_count: int = 0
    active_count: int = 0
    inactive_count: int = 0
    error: str | None = None


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _reference_entries(entries: list[SymbolEntry]) -> dict[str, SymbolEntry]:
    result: dict[str, SymbolEntry] = {}
    for entry in entries:
        symbol = entry.symbol.strip()
        exchange = entry.exchange.strip().upper()
        if not symbol or exchange not in TAIWAN_EXCHANGES:
            continue
        previous = result.get(symbol)
        if previous is not None and previous.exchange.strip().upper() != exchange:
            raise RuntimeError(f"Taiwan reference sources disagree on exchange for {symbol}")
        result[symbol] = entry
    return result


def _contract_entries(contracts: list[TaiwanContract]) -> dict[str, TaiwanContract]:
    result: dict[str, TaiwanContract] = {}
    for contract in contracts:
        symbol = contract.code.strip()
        exchange = contract.exchange.strip().upper()
        previous = result.get(symbol)
        if previous is not None and previous.exchange.strip().upper() != exchange:
            raise RuntimeError(f"Shioaji contracts disagree on exchange for {symbol}")
        result[symbol] = contract
    return result


async def sync_taiwan_symbol_directory(
    db: AsyncSession,
    *,
    twse_provider: SymbolProvider | None = None,
    tpex_provider: SymbolProvider | None = None,
    contract_adapter=None,
    now: datetime | None = None,
) -> TaiwanSymbolDirectorySyncResult:
    """Synchronize a Taiwan directory atomically and preserve it on failure."""
    sync_time = now or _utc_now()
    try:
        twse_provider = twse_provider or get_provider("twse")
        tpex_provider = tpex_provider or get_provider("tpex")
        twse_entries = await twse_provider.fetch_symbols({})
        tpex_entries = await tpex_provider.fetch_symbols({})
        if not twse_entries or not tpex_entries:
            raise RuntimeError("Taiwan reference source returned no symbols")
        reference = _reference_entries(twse_entries + tpex_entries)
        if not reference:
            raise RuntimeError("Taiwan reference sources returned no usable symbols")

        if contract_adapter is None:
            contracts = await fetch_stk_contracts(ShioajiClient())
        else:
            contracts = await contract_adapter.fetch_stk()
        contract_map = _contract_entries(contracts)
        if not contract_map:
            raise RuntimeError("Shioaji returned no usable Taiwan contracts")
    except Exception as exc:
        logger.exception("Taiwan symbol directory refresh failed")
        return TaiwanSymbolDirectorySyncResult(status="failed", error=str(exc))

    merged_symbols = set(reference) | set(contract_map)
    active_count = 0

    try:
        existing_result = await db.execute(select(SymbolDirectory))
        existing = {row.symbol: row for row in existing_result.scalars().all()}

        for symbol in sorted(merged_symbols):
            reference_entry = reference.get(symbol)
            contract_entry = contract_map.get(symbol)
            exchange = (
                reference_entry.exchange
                if reference_entry is not None
                else contract_entry.exchange
            ).strip().upper()
            row = existing.get(symbol)
            if row is None:
                row = SymbolDirectory(symbol=symbol, name=symbol, exchange=exchange)
                db.add(row)
                existing[symbol] = row
            else:
                row.exchange = exchange

            if reference_entry is not None:
                row.name = reference_entry.name
                row.type = reference_entry.type
                row.currency = reference_entry.currency
                row.reference_updated_at = sync_time
            elif row.name == symbol:
                row.name = symbol
                row.type = "unknown"
                row.currency = "TWD"

            if contract_entry is not None:
                row.contract_updated_at = sync_time

            row.active = reference_entry is not None and contract_entry is not None
            row.last_seen = sync_time
            if row.active:
                active_count += 1

        for symbol, row in existing.items():
            if row.is_taiwan and symbol not in merged_symbols:
                row.active = False

        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.exception("Taiwan symbol directory write failed")
        return TaiwanSymbolDirectorySyncResult(status="failed", error=str(exc))

    return TaiwanSymbolDirectorySyncResult(
        status="success",
        reference_count=len(reference),
        contract_count=len(contract_map),
        active_count=active_count,
        inactive_count=len(merged_symbols) - active_count,
    )
