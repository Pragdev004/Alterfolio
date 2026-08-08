"""create_baseline_decisions_table

Revision ID: f1a2b3c4d5e6
Revises: d4a7c1e9b2f3
Create Date: 2026-08-08 00:00:04.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "d4a7c1e9b2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "baseline_decisions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("recommendation_id", sa.UUID(), nullable=False),
        sa.Column("strategy_key", sa.String(length=128), nullable=False),
        sa.Column("strategy_version", sa.String(length=32), nullable=False),
        sa.Column("baseline_action", sa.Enum("MAINTAIN", name="baseline_action_type"), nullable=False),
        sa.Column("baseline_allocation", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["recommendation_id"], ["recommendations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "recommendation_id", name="uq_baseline_decisions_user_recommendation"),
    )

    op.create_index(op.f("ix_baseline_decisions_user_id"), "baseline_decisions", ["user_id"], unique=False)
    op.create_index(op.f("ix_baseline_decisions_recommendation_id"), "baseline_decisions", ["recommendation_id"], unique=False)
    op.create_index("ix_baseline_decisions_user_created_at", "baseline_decisions", ["user_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_baseline_decisions_user_created_at", table_name="baseline_decisions")
    op.drop_index(op.f("ix_baseline_decisions_recommendation_id"), table_name="baseline_decisions")
    op.drop_index(op.f("ix_baseline_decisions_user_id"), table_name="baseline_decisions")
    op.drop_table("baseline_decisions")
    op.execute("DROP TYPE baseline_action_type")
