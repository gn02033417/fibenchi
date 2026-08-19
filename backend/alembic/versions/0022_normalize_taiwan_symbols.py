"""Normalize proven Yahoo-style Taiwan symbols in place.

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-19
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _normalize_details(symbol: str) -> tuple[str, str] | None:
    upper = symbol.upper()
    for suffix, exchange in ((".TWO", "OTC"), (".TW", "TSE")):
        if upper.endswith(suffix):
            code = upper[: -len(suffix)]
            return (code, exchange) if code and code.isdecimal() else None
    return None


def _normalize(symbol: str) -> str | None:
    details = _normalize_details(symbol)
    return details[0] if details is not None else None


def _plan(bind, table_name: str) -> list[tuple[int, str, str]]:
    table = sa.table(
        table_name,
        sa.column("id", sa.Integer),
        sa.column("symbol", sa.String),
    )
    rows = list(bind.execute(sa.select(table.c.id, table.c.symbol)).mappings())
    untouched = {row["symbol"] for row in rows if _normalize(row["symbol"]) is None}
    targets: dict[str, str] = {}
    plan: list[tuple[int, str, str]] = []
    for row in rows:
        details = _normalize_details(row["symbol"])
        if details is None:
            continue
        target, exchange = details
        if target in untouched:
            raise RuntimeError(
                f"Cannot normalize {table_name} symbol {row['symbol']!r} to {target!r}: "
                f"{table_name} already contains {target!r}; no rows were changed."
            )
        if target in targets:
            raise RuntimeError(
                f"Cannot normalize multiple {table_name} rows to {target!r}; no rows were changed."
            )
        targets[target] = row["symbol"]
        plan.append((row["id"], target, exchange))
    return plan


def _apply_table(bind, table_name: str, plan: list[tuple[int, str, str]]) -> None:
    table = sa.table(
        table_name,
        sa.column("id", sa.Integer),
        sa.column("symbol", sa.String),
        sa.column("exchange", sa.String),
    )
    for row_id, target, exchange in plan:
        bind.execute(
            sa.update(table)
            .where(table.c.id == row_id)
            .values(symbol=target, exchange=exchange)
        )


def upgrade() -> None:
    bind = op.get_bind()
    asset_plan = _plan(bind, "assets")
    directory_plan = _plan(bind, "symbol_directory")
    _apply_table(bind, "assets", asset_plan)
    _apply_table(bind, "symbol_directory", directory_plan)


def downgrade() -> None:
    # Raw symbols do not carry enough information to reconstruct whether the
    # original suffix was .TW or .TWO. The migration is intentionally forward-only.
    pass

