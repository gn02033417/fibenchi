"""Add 'index' value to assettype enum

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-04
"""

from alembic import op


revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE assettype ADD VALUE IF NOT EXISTS 'index'")


def downgrade() -> None:
    # PostgreSQL doesn't support removing enum values; downgrade is a no-op.
    pass
