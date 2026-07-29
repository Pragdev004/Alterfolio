from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum as SQLEnum,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import AssetType, Currency, Exchange


class Position(Base):
    __tablename__ = "positions"

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

    asset_symbol: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )

    exchange: Mapped[Exchange] = mapped_column(
        SQLEnum(Exchange, name="exchange"),
        nullable=False,
    )

    asset_type: Mapped[AssetType] = mapped_column(
        SQLEnum(AssetType, name="asset_type"),
        nullable=False,
    )

    currency: Mapped[Currency] = mapped_column(
        SQLEnum(Currency, name="currency"),
        nullable=False,
        default=Currency.INR,
    )

    remaining_quantity: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        server_default=text("0"),
    )

    remaining_cost_basis: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        server_default=text("0"),
    )

    average_cost: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        server_default=text("0"),
    )

    cumulative_realized_profit_loss: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        server_default=text("0"),
    )

    last_accounted_trade_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

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
        UniqueConstraint(
            "user_id",
            "asset_symbol",
            "exchange",
            "asset_type",
            "currency",
            name="uq_positions_user_instrument",
        ),
        CheckConstraint(
            "remaining_quantity >= 0",
            name="ck_positions_remaining_quantity_non_negative",
        ),
        CheckConstraint(
            "remaining_cost_basis >= 0",
            name="ck_positions_remaining_cost_basis_non_negative",
        ),
        CheckConstraint(
            "average_cost >= 0",
            name="ck_positions_average_cost_non_negative",
        ),
        Index("ix_positions_user_symbol", "user_id", "asset_symbol"),
        Index(
            "ix_positions_user_last_accounted_trade_timestamp",
            "user_id",
            "last_accounted_trade_timestamp",
        ),
    )
