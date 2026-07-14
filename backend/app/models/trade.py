from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    Enum as SQLEnum,
    Index,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import (
    AssetType,
    Currency,
    Exchange,
    InvestmentHorizon,
    MarketSession,
    TradeSource,
    TradeStatus,
    TransactionType,
)


class Trade(Base):
    __tablename__ = "trades"

    # ==========================
    # Identity
    # ==========================

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    # ==========================
    # Asset Information
    # ==========================

    asset_symbol: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )

    asset_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    asset_type: Mapped[AssetType] = mapped_column(
        SQLEnum(AssetType, name="asset_type"),
        nullable=False,
    )

    exchange: Mapped[Exchange] = mapped_column(
        SQLEnum(Exchange, name="exchange"),
        nullable=False,
    )

    currency: Mapped[Currency] = mapped_column(
        SQLEnum(Currency, name="currency"),
        nullable=False,
        default=Currency.INR,
    )

    # ==========================
    # Trade Information
    # ==========================

    transaction_type: Mapped[TransactionType] = mapped_column(
        SQLEnum(TransactionType, name="transaction_type"),
        nullable=False,
    )

    quantity: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )

    price_per_unit: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )

    trade_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    # ==========================
    # Financial Information
    # ==========================

    brokerage_fee: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        server_default=text("0"),
    )

    taxes: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        server_default=text("0"),
    )

    # ==========================
    # Execution Information
    # ==========================

    broker: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )

    order_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    trade_source: Mapped[TradeSource] = mapped_column(
        SQLEnum(TradeSource, name="trade_source"),
        nullable=False,
        index=True,
    )

    market_session: Mapped[MarketSession] = mapped_column(
        SQLEnum(MarketSession, name="market_session"),
        nullable=False,
    )

    status: Mapped[TradeStatus] = mapped_column(
        SQLEnum(TradeStatus, name="trade_status"),
        nullable=False,
        default=TradeStatus.EXECUTED,
        index=True,
    )

    # ==========================
    # Investment Context
    # ==========================

    investment_horizon: Mapped[InvestmentHorizon | None] = mapped_column(
        SQLEnum(InvestmentHorizon, name="investment_horizon"),
        nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # ==========================
    # Metadata
    # ==========================

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index(
            "ix_trades_user_symbol",
            "user_id",
            "asset_symbol",
        ),
    )