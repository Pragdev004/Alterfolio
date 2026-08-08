"""create_user_decisions_table

Revision ID: d4a7c1e9b2f3
Revises: c2f6a8d1e4b9
Create Date: 2026-08-08 00:00:03.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4a7c1e9b2f3"
down_revision: Union[str, Sequence[str], None] = "c2f6a8d1e4b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "user_decisions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("recommendation_id", sa.UUID(), nullable=False),
        sa.Column("trade_id", sa.UUID(), nullable=True),
        sa.Column(
            "decision_type",
            sa.Enum("ACCEPTED", "IGNORED", "MODIFIED", name="user_decision_type"),
            nullable=False,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("modified_allocation", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["recommendation_id"], ["recommendations.id"]),
        sa.ForeignKeyConstraint(["trade_id"], ["trades.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "recommendation_id", name="uq_user_decisions_user_recommendation"),
    )

    op.create_index(op.f("ix_user_decisions_user_id"), "user_decisions", ["user_id"], unique=False)
    op.create_index(op.f("ix_user_decisions_recommendation_id"), "user_decisions", ["recommendation_id"], unique=False)
    op.create_index(op.f("ix_user_decisions_trade_id"), "user_decisions", ["trade_id"], unique=False)
    op.create_index("ix_user_decisions_user_decided_at", "user_decisions", ["user_id", "decided_at"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_user_decisions_user_decided_at", table_name="user_decisions")
    op.drop_index(op.f("ix_user_decisions_trade_id"), table_name="user_decisions")
    op.drop_index(op.f("ix_user_decisions_recommendation_id"), table_name="user_decisions")
    op.drop_index(op.f("ix_user_decisions_user_id"), table_name="user_decisions")
    op.drop_table("user_decisions")
