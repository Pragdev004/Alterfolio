from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    event,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.column_types import ExactDecimal, UTCDateTime
from app.domain import limits
from app.domain.enums import (
    AssetType,
    Currency,
    Exchange,
    MarketSession,
    TradeSide,
    TradeSource,
    TradeStatus,
)
from app.models import import_batch  # noqa: F401  (registers import_batches, which trades references by foreign key)
from app.models.base import Base


def _enum(cls, name: str):
    return Enum(
        cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=16,
        values_callable=lambda e: [m.value for m in e],
    )


_DEDUPE_WHERE = text("broker_trade_id IS NOT NULL AND supersedes_trade_id IS NULL")


class Trade(Base):
    """Append-only ledger row. Corrections are new rows with supersedes_trade_id."""

    __tablename__ = "trades"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    symbol: Mapped[str] = mapped_column(String(limits.MAX_SYMBOL_LENGTH))
    name: Mapped[str | None] = mapped_column(String(limits.MAX_NAME_LENGTH))  # NULL = not provided (imports)
    asset_type: Mapped[AssetType | None] = mapped_column(_enum(AssetType, "asset_type"))
    exchange: Mapped[Exchange] = mapped_column(_enum(Exchange, "exchange"))
    currency: Mapped[Currency] = mapped_column(_enum(Currency, "currency"))
    side: Mapped[TradeSide] = mapped_column(_enum(TradeSide, "side"))
    quantity: Mapped[Decimal] = mapped_column(ExactDecimal)
    price_per_unit: Mapped[Decimal] = mapped_column(ExactDecimal)
    brokerage_fee: Mapped[Decimal] = mapped_column(ExactDecimal)
    taxes: Mapped[Decimal] = mapped_column(ExactDecimal)
    trade_timestamp: Mapped[datetime] = mapped_column(UTCDateTime)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime)
    broker: Mapped[str | None] = mapped_column(String(limits.MAX_BROKER_LENGTH))
    broker_trade_id: Mapped[str | None] = mapped_column(String(limits.MAX_BROKER_TRADE_ID_LENGTH))
    order_id: Mapped[str | None] = mapped_column(String(limits.MAX_ORDER_ID_LENGTH))
    supersedes_trade_id: Mapped[UUID | None] = mapped_column()
    source: Mapped[TradeSource] = mapped_column(_enum(TradeSource, "source"))
    market_session: Mapped[MarketSession | None] = mapped_column(_enum(MarketSession, "market_session"))
    status: Mapped[TradeStatus] = mapped_column(_enum(TradeStatus, "status"))
    notes: Mapped[str | None] = mapped_column(String(limits.MAX_NOTES_LENGTH))
    isin: Mapped[str | None] = mapped_column(String(limits.ISIN_LENGTH))  # NULL only on legacy rows
    # False on imported rows: the stored 0 fees/taxes are unknown, not zero. Manual rows and corrections store True.
    charges_provided: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    import_batch_id: Mapped[UUID | None] = mapped_column()  # set if and only if source = IMPORT

    __table_args__ = (
        UniqueConstraint("user_id", "id", name="uq_trades_user_id_id"),
        UniqueConstraint("supersedes_trade_id", name="uq_trades_supersedes_trade_id"),
        ForeignKeyConstraint(
            ["user_id", "supersedes_trade_id"],
            ["trades.user_id", "trades.id"],
            name="fk_trades_supersedes_same_user",
        ),
        CheckConstraint("CAST(quantity AS NUMERIC) > 0", name="quantity_positive"),
        CheckConstraint("CAST(price_per_unit AS NUMERIC) > 0", name="price_positive"),
        CheckConstraint("CAST(brokerage_fee AS NUMERIC) >= 0", name="fee_non_negative"),
        CheckConstraint("CAST(taxes AS NUMERIC) >= 0", name="taxes_non_negative"),
        ForeignKeyConstraint(
            ["user_id", "import_batch_id"],
            ["import_batches.user_id", "import_batches.id"],
            name="fk_trades_import_batch_same_user",
        ),
        CheckConstraint(f"isin IS NULL OR length(isin) = {limits.ISIN_LENGTH}", name="isin_length"),
        CheckConstraint("(source = 'IMPORT') = (import_batch_id IS NOT NULL)", name="import_source_has_batch"),
        Index(
            "uq_trades_dedupe",
            "user_id",
            "broker",
            "exchange",
            "broker_trade_id",
            unique=True,
            postgresql_where=_DEDUPE_WHERE,
            sqlite_where=_DEDUPE_WHERE,
        ),
        Index("ix_trades_user_timestamp", "user_id", "trade_timestamp"),
    )


@event.listens_for(Trade, "before_update")
def _refuse_update(mapper, connection, target):
    raise RuntimeError("trades are append-only: update refused")


@event.listens_for(Trade, "before_delete")
def _refuse_delete(mapper, connection, target):
    raise RuntimeError("trades are append-only: delete refused")
