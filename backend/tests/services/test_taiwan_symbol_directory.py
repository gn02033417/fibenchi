"""Offline tests for Taiwan reference/contract directory synchronization."""

from datetime import datetime

import pytest
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.background_tasks import all_tasks
from app.models.symbol_directory import SymbolDirectory
from app.services.shioaji.contracts import TaiwanContract
from app.services.symbol_providers.base import SymbolEntry
from app.services.taiwan_symbol_directory import sync_taiwan_symbol_directory


def _entries() -> list[SymbolEntry]:
    return [
        SymbolEntry(symbol="2330", name="台積電", exchange="TSE", currency="TWD", type="stock"),
        SymbolEntry(symbol="0050", name="元大台灣50", exchange="TSE", currency="TWD", type="etf"),
        SymbolEntry(symbol="6488", name="環球晶", exchange="OTC", currency="TWD", type="stock"),
        SymbolEntry(symbol="9000", name="只有官方名冊", exchange="OTC", currency="TWD", type="stock"),
    ]


def _contracts() -> list[TaiwanContract]:
    return [
        TaiwanContract(code="2330", exchange="TSE"),
        TaiwanContract(code="0050", exchange="TSE"),
        TaiwanContract(code="6488", exchange="OTC"),
        TaiwanContract(code="7777", exchange="OTC"),
    ]


class FakeProvider:
    def __init__(self, entries=None, error: Exception | None = None):
        self.entries = entries or []
        self.error = error

    async def fetch_symbols(self, config):
        if self.error is not None:
            raise self.error
        return self.entries


class FakeContractAdapter:
    def __init__(self, contracts=None, error: Exception | None = None):
        self.contracts = contracts or []
        self.error = error

    async def fetch_stk(self):
        if self.error is not None:
            raise self.error
        return self.contracts


async def _rows(db) -> dict[tuple[str, str], SymbolDirectory]:
    result = await db.execute(select(SymbolDirectory))
    return {(row.symbol, row.exchange): row for row in result.scalars().all()}


@pytest.mark.asyncio
async def test_merges_reference_and_contract_truth_with_active_intersection(db):
    now = datetime(2026, 8, 19, 9, 0, 0)

    result = await sync_taiwan_symbol_directory(
        db,
        twse_provider=FakeProvider(_entries()[:2]),
        tpex_provider=FakeProvider(_entries()[2:]),
        contract_adapter=FakeContractAdapter(_contracts()),
        now=now,
    )

    assert result.status == "success"
    assert result.reference_count == 4
    assert result.contract_count == 4
    assert result.active_count == 3
    assert result.inactive_count == 2

    rows = await _rows(db)
    assert set(rows) == {
        ("2330", "TSE"),
        ("0050", "TSE"),
        ("6488", "OTC"),
        ("9000", "OTC"),
        ("7777", "OTC"),
    }
    assert rows[("2330", "TSE")].active is True
    assert rows[("0050", "TSE")].type == "etf"
    assert rows[("6488", "OTC")].active is True
    assert rows[("9000", "OTC")].active is False
    assert rows[("7777", "OTC")].active is False
    assert rows[("7777", "OTC")].type == "unknown"
    assert rows[("2330", "TSE")].reference_updated_at == now
    assert rows[("2330", "TSE")].contract_updated_at == now
    assert rows[("9000", "OTC")].reference_updated_at == now
    assert rows[("7777", "OTC")].contract_updated_at == now


@pytest.mark.asyncio
async def test_sync_is_idempotent_and_does_not_duplicate_directory_rows(db):
    kwargs = {
        "twse_provider": FakeProvider(_entries()[:2]),
        "tpex_provider": FakeProvider(_entries()[2:]),
        "contract_adapter": FakeContractAdapter(_contracts()),
    }

    first = await sync_taiwan_symbol_directory(db, now=datetime(2026, 8, 19, 9, 0), **kwargs)
    second = await sync_taiwan_symbol_directory(db, now=datetime(2026, 8, 19, 9, 1), **kwargs)

    assert first.status == second.status == "success"
    assert len(await _rows(db)) == 5


@pytest.mark.asyncio
async def test_reconciles_existing_symbol_when_exchange_metadata_changes(db):
    existing = SymbolDirectory(
        symbol="2330",
        name="舊名稱",
        exchange="OTC",
        type="stock",
        currency="TWD",
        active=True,
    )
    db.add(existing)
    await db.commit()
    existing_id = existing.id

    result = await sync_taiwan_symbol_directory(
        db,
        twse_provider=FakeProvider(_entries()[:1]),
        tpex_provider=FakeProvider(_entries()[2:]),
        contract_adapter=FakeContractAdapter(_contracts()),
        now=datetime(2026, 8, 19, 9, 0),
    )

    assert result.status == "success"
    rows = await _rows(db)
    assert ("2330", "OTC") not in rows
    assert rows[("2330", "TSE")].id == existing_id
    assert rows[("2330", "TSE")].active is True


@pytest.mark.asyncio
async def test_failed_refresh_preserves_last_known_good_rows(db):
    before_now = datetime(2026, 8, 19, 9, 0, 0)
    await sync_taiwan_symbol_directory(
        db,
        twse_provider=FakeProvider(_entries()[:2]),
        tpex_provider=FakeProvider(_entries()[2:]),
        contract_adapter=FakeContractAdapter(_contracts()),
        now=before_now,
    )
    before = {
        key: (row.name, row.exchange, row.type, row.currency, row.active,
              row.reference_updated_at, row.contract_updated_at)
        for key, row in (await _rows(db)).items()
    }

    result = await sync_taiwan_symbol_directory(
        db,
        twse_provider=FakeProvider(error=RuntimeError("TWSE unavailable")),
        tpex_provider=FakeProvider(_entries()[2:]),
        contract_adapter=FakeContractAdapter(_contracts()),
        now=datetime(2026, 8, 19, 10, 0, 0),
    )

    after = {
        key: (row.name, row.exchange, row.type, row.currency, row.active,
              row.reference_updated_at, row.contract_updated_at)
        for key, row in (await _rows(db)).items()
    }
    assert result.status == "failed"
    assert "TWSE unavailable" in (result.error or "")
    assert after == before


def test_daily_taiwan_sync_is_registered_without_replacing_existing_jobs():
    tasks = {task.id: task for task in all_tasks()}

    assert "symbol_directory_sync" in tasks
    assert "taiwan_symbol_directory_sync" in tasks
    assert isinstance(tasks["taiwan_symbol_directory_sync"].resolve_trigger(), CronTrigger)

