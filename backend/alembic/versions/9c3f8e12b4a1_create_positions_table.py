"""create_positions_table

Revision ID: 9c3f8e12b4a1
Revises: 14e0644c6547
Create Date: 2026-07-29 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "9c3f8e12b4a1"
down_revision: Union[str, Sequence[str], None] = "14e0644c6547"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "positions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("asset_symbol", sa.String(length=32), nullable=False),
        sa.Column(
            "exchange",
            postgresql.ENUM(name="exchange", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "asset_type",
            postgresql.ENUM(name="asset_type", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "currency",
            postgresql.ENUM(name="currency", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "remaining_quantity",
            sa.Numeric(precision=20, scale=8),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "remaining_cost_basis",
            sa.Numeric(precision=20, scale=8),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "average_cost",
            sa.Numeric(precision=20, scale=8),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "cumulative_realized_profit_loss",
            sa.Numeric(precision=20, scale=8),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("last_accounted_trade_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "average_cost >= 0",
            name="ck_positions_average_cost_non_negative",
        ),
        sa.CheckConstraint(
            "remaining_cost_basis >= 0",
            name="ck_positions_remaining_cost_basis_non_negative",
        ),
        sa.CheckConstraint(
            "remaining_quantity >= 0",
            name="ck_positions_remaining_quantity_non_negative",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "asset_symbol",
            "exchange",
            "asset_type",
            "currency",
            name="uq_positions_user_instrument",
        ),
    )

    op.create_index(op.f("ix_positions_asset_symbol"), "positions", ["asset_symbol"], unique=False)
    op.create_index(op.f("ix_positions_last_accounted_trade_timestamp"), "positions", ["last_accounted_trade_timestamp"], unique=False)
    op.create_index(op.f("ix_positions_user_id"), "positions", ["user_id"], unique=False)
    op.create_index("ix_positions_user_last_accounted_trade_timestamp", "positions", ["user_id", "last_accounted_trade_timestamp"], unique=False)
    op.create_index("ix_positions_user_symbol", "positions", ["user_id", "asset_symbol"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_positions_user_symbol", table_name="positions")
    op.drop_index("ix_positions_user_last_accounted_trade_timestamp", table_name="positions")
    op.drop_index(op.f("ix_positions_user_id"), table_name="positions")
    op.drop_index(op.f("ix_positions_last_accounted_trade_timestamp"), table_name="positions")
    op.drop_index(op.f("ix_positions_asset_symbol"), table_name="positions")
    op.drop_table("positions")
