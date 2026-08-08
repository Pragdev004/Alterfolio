"""add_market_snapshot_id_to_recommendations

Revision ID: c2f6a8d1e4b9
Revises: b8e1f4a2c9d0
Create Date: 2026-08-08 00:00:02.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c2f6a8d1e4b9"
down_revision: Union[str, Sequence[str], None] = "b8e1f4a2c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("recommendations", sa.Column("market_snapshot_id", sa.UUID(), nullable=True))
    op.create_index(
        op.f("ix_recommendations_market_snapshot_id"),
        "recommendations",
        ["market_snapshot_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_recommendations_market_snapshot_id",
        "recommendations",
        "market_snapshots",
        ["market_snapshot_id"],
        ["id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("fk_recommendations_market_snapshot_id", "recommendations", type_="foreignkey")
    op.drop_index(op.f("ix_recommendations_market_snapshot_id"), table_name="recommendations")
    op.drop_column("recommendations", "market_snapshot_id")
