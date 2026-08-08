"""create_market_snapshots_table

Revision ID: b8e1f4a2c9d0
Revises: a3d9f17c2b6e
Create Date: 2026-08-08 00:00:01.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "b8e1f4a2c9d0"
down_revision: Union[str, Sequence[str], None] = "a3d9f17c2b6e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "market_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("asset_symbol", sa.String(length=32), nullable=False),
        sa.Column("exchange", postgresql.ENUM(name="exchange", create_type=False), nullable=True),
        sa.Column("asset_type", postgresql.ENUM(name="asset_type", create_type=False), nullable=True),
        sa.Column("currency", postgresql.ENUM(name="currency", create_type=False), nullable=False),
        sa.Column("asset_price", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("price_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("volume", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("market_cap", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("market_data", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(op.f("ix_market_snapshots_user_id"), "market_snapshots", ["user_id"], unique=False)
    op.create_index(
        "ix_market_snapshots_user_captured_at",
        "market_snapshots",
        ["user_id", "captured_at"],
        unique=False,
    )
    op.create_index(
        "ix_market_snapshots_user_asset_symbol_captured_at",
        "market_snapshots",
        ["user_id", "asset_symbol", "captured_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_market_snapshots_user_asset_symbol_captured_at", table_name="market_snapshots")
    op.drop_index("ix_market_snapshots_user_captured_at", table_name="market_snapshots")
    op.drop_index(op.f("ix_market_snapshots_user_id"), table_name="market_snapshots")
    op.drop_table("market_snapshots")
