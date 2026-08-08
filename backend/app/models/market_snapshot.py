from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum as SQLEnum, Index, JSON, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import AssetType, Currency, Exchange


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"

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

    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    source: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    asset_symbol: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    exchange: Mapped[Exchange | None] = mapped_column(
        SQLEnum(Exchange, name="exchange"),
        nullable=True,
    )

    asset_type: Mapped[AssetType | None] = mapped_column(
        SQLEnum(AssetType, name="asset_type"),
        nullable=True,
    )

    currency: Mapped[Currency] = mapped_column(
        SQLEnum(Currency, name="currency"),
        nullable=False,
        default=Currency.INR,
    )

    asset_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )

    price_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    volume: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8),
        nullable=True,
    )

    market_cap: Mapped[Decimal | None] = mapped_column(
        Numeric(24, 8),
        nullable=True,
    )

    market_data: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
    )

    __table_args__ = (
        Index("ix_market_snapshots_user_captured_at", "user_id", "captured_at"),
        Index(
            "ix_market_snapshots_user_asset_symbol_captured_at",
            "user_id",
            "asset_symbol",
            "captured_at",
        ),
    )
