"""import batches, ISIN, charges_provided, exchange in the dedupe key (Feature 002)

Revision ID: 0002
Revises: 0001

Nothing is backfilled: existing trades keep isin NULL, import_batch_id NULL and charges_provided true.
`batch_alter_table` is a plain ALTER on PostgreSQL and a table rebuild on SQLite (test-only).
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_DEDUPE_WHERE = sa.text("broker_trade_id IS NOT NULL AND supersedes_trade_id IS NULL")
_FK = "fk_trades_import_batch_same_user"


def upgrade() -> None:
    op.create_table(
        "import_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column("imported", sa.Integer(), nullable=False),
        sa.Column("duplicates", sa.Integer(), nullable=False),
        sa.Column("rejected_total", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_import_batches"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_import_batches_user_id_users"),
        sa.UniqueConstraint("user_id", "id", name="uq_import_batches_user_id_id"),
    )
    op.create_index("ix_import_batches_user_id", "import_batches", ["user_id"])

    op.drop_index("uq_trades_dedupe", table_name="trades")
    with op.batch_alter_table("trades") as batch:
        batch.alter_column("name", existing_type=sa.String(256), nullable=True)
        batch.alter_column("asset_type", existing_type=sa.String(16), nullable=True)
        batch.alter_column("market_session", existing_type=sa.String(16), nullable=True)
        batch.add_column(sa.Column("isin", sa.String(12), nullable=True))
        batch.add_column(sa.Column("charges_provided", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.add_column(sa.Column("import_batch_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(_FK, "import_batches", ["user_id", "import_batch_id"], ["user_id", "id"])
        batch.create_check_constraint("isin_length", "isin IS NULL OR length(isin) = 12")
        batch.create_check_constraint("import_source_has_batch", "(source = 'IMPORT') = (import_batch_id IS NOT NULL)")
    op.create_index(
        "uq_trades_dedupe",
        "trades",
        ["user_id", "broker", "exchange", "broker_trade_id"],
        unique=True,
        postgresql_where=_DEDUPE_WHERE,
        sqlite_where=_DEDUPE_WHERE,
    )


def downgrade() -> None:
    op.drop_index("uq_trades_dedupe", table_name="trades")
    with op.batch_alter_table("trades") as batch:
        batch.drop_constraint(op.f("ck_trades_import_source_has_batch"), type_="check")
        batch.drop_constraint(op.f("ck_trades_isin_length"), type_="check")
        batch.drop_constraint(_FK, type_="foreignkey")
        batch.drop_column("import_batch_id")
        batch.drop_column("charges_provided")
        batch.drop_column("isin")
        # these fail loudly if rows with NULLs exist; data is never rewritten
        batch.alter_column("market_session", existing_type=sa.String(16), nullable=False)
        batch.alter_column("asset_type", existing_type=sa.String(16), nullable=False)
        batch.alter_column("name", existing_type=sa.String(256), nullable=False)
    op.create_index(
        "uq_trades_dedupe",
        "trades",
        ["user_id", "broker", "broker_trade_id"],
        unique=True,
        postgresql_where=_DEDUPE_WHERE,
        sqlite_where=_DEDUPE_WHERE,
    )
    op.drop_index("ix_import_batches_user_id", table_name="import_batches")
    op.drop_table("import_batches")
