"""users and trades

Revision ID: 0001
Revises:
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_DEDUPE_WHERE = sa.text("broker_trade_id IS NOT NULL AND supersedes_trade_id IS NULL")


def _in(column: str, values: list[str]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )
    op.create_table(
        "trades",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("asset_type", sa.String(16), nullable=False),
        sa.Column("exchange", sa.String(16), nullable=False),
        sa.Column("currency", sa.String(16), nullable=False),
        sa.Column("side", sa.String(16), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("price_per_unit", sa.Numeric(20, 6), nullable=False),
        sa.Column("brokerage_fee", sa.Numeric(20, 6), nullable=False),
        sa.Column("taxes", sa.Numeric(20, 6), nullable=False),
        sa.Column("trade_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("broker", sa.String(64), nullable=True),
        sa.Column("broker_trade_id", sa.String(128), nullable=True),
        sa.Column("order_id", sa.String(128), nullable=True),
        sa.Column("supersedes_trade_id", sa.Uuid(), nullable=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("market_session", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("notes", sa.String(2000), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_trades"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_trades_user_id_users"),
        sa.UniqueConstraint("user_id", "id", name="uq_trades_user_id_id"),
        sa.UniqueConstraint("supersedes_trade_id", name="uq_trades_supersedes_trade_id"),
        sa.ForeignKeyConstraint(
            ["user_id", "supersedes_trade_id"],
            ["trades.user_id", "trades.id"],
            name="fk_trades_supersedes_same_user",
        ),
        sa.CheckConstraint("CAST(quantity AS NUMERIC) > 0", name="quantity_positive"),
        sa.CheckConstraint("CAST(price_per_unit AS NUMERIC) > 0", name="price_positive"),
        sa.CheckConstraint("CAST(brokerage_fee AS NUMERIC) >= 0", name="fee_non_negative"),
        sa.CheckConstraint("CAST(taxes AS NUMERIC) >= 0", name="taxes_non_negative"),
        sa.CheckConstraint(_in("asset_type", ["STOCK", "ETF"]), name="asset_type"),
        sa.CheckConstraint(_in("exchange", ["NSE", "BSE"]), name="exchange"),
        sa.CheckConstraint(_in("currency", ["INR"]), name="currency"),
        sa.CheckConstraint(_in("side", ["BUY", "SELL"]), name="side"),
        sa.CheckConstraint(_in("source", ["MANUAL", "IMPORT"]), name="source"),
        sa.CheckConstraint(
            _in("market_session", ["PRE_MARKET", "REGULAR", "POST_MARKET"]),
            name="market_session",
        ),
        sa.CheckConstraint(
            _in("status", ["EXECUTED", "PENDING", "CANCELLED", "REJECTED"]), name="status"
        ),
    )
    op.create_index(
        "uq_trades_dedupe",
        "trades",
        ["user_id", "broker", "broker_trade_id"],
        unique=True,
        postgresql_where=_DEDUPE_WHERE,
        sqlite_where=_DEDUPE_WHERE,
    )
    op.create_index("ix_trades_user_timestamp", "trades", ["user_id", "trade_timestamp"])


def downgrade() -> None:
    op.drop_index("ix_trades_user_timestamp", table_name="trades")
    op.drop_index("uq_trades_dedupe", table_name="trades")
    op.drop_table("trades")
    op.drop_table("users")
