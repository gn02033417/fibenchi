"""Add 'INDEX' (uppercase) to assettype enum.

0012 mistakenly added the lowercase value ``'index'`` to the Postgres
``assettype`` enum, but SQLAlchemy's ``Enum(AssetType)`` column stores
the enum *name* (``'STOCK'``, ``'ETF'``, ``'INDEX'``), not the value.
That left writes of ``AssetType.INDEX`` raising ``invalid input value
for enum assettype: 'INDEX'`` while the orphan ``'index'`` value
hung around unused.

This migration adds the correct uppercase variant. The orphaned
lowercase ``'index'`` is harmless (no rows ever referenced it, since
the bug prevented inserts) and Postgres can't drop enum values, so
we leave it.

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-05
"""

from alembic import op


revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE assettype ADD VALUE IF NOT EXISTS 'INDEX'")


def downgrade() -> None:
    # PostgreSQL doesn't support removing enum values; downgrade is a no-op.
    pass
