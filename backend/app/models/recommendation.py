from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum as SQLEnum, ForeignKey, Index, Integer, JSON, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import RecommendationStatus, RecommendationType


class Recommendation(Base):
    __tablename__ = "recommendations"

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

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    status: Mapped[RecommendationStatus] = mapped_column(
        SQLEnum(RecommendationStatus, name="recommendation_status"),
        nullable=False,
        default=RecommendationStatus.GENERATED,
    )

    recommendation_type: Mapped[RecommendationType] = mapped_column(
        SQLEnum(RecommendationType, name="recommendation_type"),
        nullable=False,
    )

    asset_symbol: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    suggested_allocation: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )

    expected_holding_period_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    confidence_score: Mapped[Decimal] = mapped_column(
        Numeric(10, 8),
        nullable=False,
    )

    risk_score: Mapped[Decimal] = mapped_column(
        Numeric(10, 8),
        nullable=False,
    )

    reasoning_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    reasoning_json: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
    )

    market_snapshot: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
    )

    market_snapshot_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("market_snapshots.id"),
        nullable=True,
        index=True,
    )

    context_market_snapshot = relationship(
        "MarketSnapshot",
        foreign_keys=[market_snapshot_id],
        uselist=False,
    )

    baseline_decision = relationship(
        "BaselineDecision",
        uselist=False,
        back_populates="recommendation",
    )

    portfolio_snapshot_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=True,
    )

    __table_args__ = (
        Index("ix_recommendations_user_created_at", "user_id", "created_at"),
        Index("ix_recommendations_user_asset_symbol", "user_id", "asset_symbol"),
        Index("ix_recommendations_user_status", "user_id", "status"),
    )
