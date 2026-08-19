"""Add Taiwan market metadata and realtime-priority fields.

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-19
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("assets", sa.Column("exchange", sa.String(length=20), nullable=True))
    op.add_column(
        "groups",
        sa.Column("realtime_priority", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "symbol_directory",
        sa.Column("currency", sa.String(length=10), nullable=False, server_default="USD"),
    )
    op.add_column(
        "symbol_directory",
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column("symbol_directory", sa.Column("contract_updated_at", sa.DateTime(), nullable=True))
    op.add_column("symbol_directory", sa.Column("reference_updated_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("symbol_directory", "reference_updated_at")
    op.drop_column("symbol_directory", "contract_updated_at")
    op.drop_column("symbol_directory", "active")
    op.drop_column("symbol_directory", "currency")
    op.drop_column("groups", "realtime_priority")
    op.drop_column("assets", "exchange")
