"""One-time normalization for legacy Yahoo-style Taiwan symbols."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.symbol_directory import SymbolDirectory


class TaiwanSymbolMigrationError(ValueError):
    """Raised when normalizing a symbol would overwrite an existing row."""


def normalize_legacy_taiwan_symbol(symbol: str) -> str | None:
    """Return the raw Taiwan code for a proven numeric Yahoo-style symbol.

    A suffix alone is not enough to classify arbitrary text as a Taiwan
    security. The numeric code check keeps values such as ``AAPL.TW`` outside
    this one-time migration and preserves leading zeroes by slicing the source
    string rather than converting it to an integer.
    """
    upper = symbol.upper()
    for suffix in (".TWO", ".TW"):
        if not upper.endswith(suffix):
            continue
        code = upper[: -len(suffix)]
        return code if code and code.isdecimal() else None
    return None


def _plan_rows(rows: Iterable[object], table_name: str) -> list[tuple[object, str]]:
    rows = list(rows)
    untouched = {
        row.symbol
        for row in rows
        if normalize_legacy_taiwan_symbol(row.symbol) is None
    }
    targets: dict[str, object] = {}
    plan: list[tuple[object, str]] = []
    for row in rows:
        target = normalize_legacy_taiwan_symbol(row.symbol)
        if target is None:
            continue
        if target in untouched:
            raise TaiwanSymbolMigrationError(
                f"Cannot normalize {table_name} symbol {row.symbol!r} to {target!r}: "
                f"{table_name} already contains {target!r}; no rows were changed."
            )
        previous = targets.get(target)
        if previous is not None:
            raise TaiwanSymbolMigrationError(
                f"Cannot normalize {table_name} symbols {previous.symbol!r} and {row.symbol!r} "
                f"to the same target {target!r}; no rows were changed."
            )
        targets[target] = row
        plan.append((row, target))
    return plan


async def normalize_legacy_taiwan_symbols(db: AsyncSession) -> dict[str, int]:
    """Normalize proven Taiwan rows atomically and preserve their identities."""
    assets = list((await db.execute(select(Asset).order_by(Asset.id))).scalars().all())
    directories = list(
        (await db.execute(select(SymbolDirectory).order_by(SymbolDirectory.id))).scalars().all()
    )

    # Build both plans before mutating either table so a collision in one table
    # cannot leave the other table partially normalized.
    asset_plan = _plan_rows(assets, "assets")
    directory_plan = _plan_rows(directories, "symbol_directory")

    for asset, target in asset_plan:
        asset.symbol = target
    for directory, target in directory_plan:
        directory.symbol = target

    await db.commit()
    return {"assets": len(asset_plan), "symbol_directory": len(directory_plan)}
