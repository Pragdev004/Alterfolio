"""create_recommendations_table

Revision ID: a3d9f17c2b6e
Revises: 9c3f8e12b4a1
Create Date: 2026-08-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a3d9f17c2b6e"
down_revision: Union[str, Sequence[str], None] = "9c3f8e12b4a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "recommendations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "GENERATED",
                "DISPLAYED",
                "ACCEPTED",
                "IGNORED",
                "EXPIRED",
                "EXECUTED",
                "EVALUATED",
                "ARCHIVED",
                name="recommendation_status",
            ),
            nullable=False,
        ),
        sa.Column(
            "recommendation_type",
            sa.Enum(
                "BUY",
                "SELL",
                "HOLD",
                "REBALANCE",
                "REDUCE",
                "INCREASE",
                name="recommendation_type",
            ),
            nullable=False,
        ),
        sa.Column("asset_symbol", sa.String(length=32), nullable=False),
        sa.Column("suggested_allocation", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("expected_holding_period_days", sa.Integer(), nullable=False),
        sa.Column("confidence_score", sa.Numeric(precision=10, scale=8), nullable=False),
        sa.Column("risk_score", sa.Numeric(precision=10, scale=8), nullable=False),
        sa.Column("reasoning_text", sa.Text(), nullable=False),
        sa.Column("reasoning_json", sa.JSON(), nullable=False),
        sa.Column("market_snapshot", sa.JSON(), nullable=False),
        sa.Column("portfolio_snapshot_id", sa.UUID(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(op.f("ix_recommendations_user_id"), "recommendations", ["user_id"], unique=False)
    op.create_index("ix_recommendations_user_created_at", "recommendations", ["user_id", "created_at"], unique=False)
    op.create_index("ix_recommendations_user_asset_symbol", "recommendations", ["user_id", "asset_symbol"], unique=False)
    op.create_index("ix_recommendations_user_status", "recommendations", ["user_id", "status"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_recommendations_user_status", table_name="recommendations")
    op.drop_index("ix_recommendations_user_asset_symbol", table_name="recommendations")
    op.drop_index("ix_recommendations_user_created_at", table_name="recommendations")
    op.drop_index(op.f("ix_recommendations_user_id"), table_name="recommendations")
    op.drop_table("recommendations")
