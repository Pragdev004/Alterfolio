from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum as SQLEnum, ForeignKey, Index, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import BaselineAction


class BaselineDecision(Base):
    __tablename__ = "baseline_decisions"

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

    recommendation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("recommendations.id"),
        nullable=False,
        index=True,
    )

    strategy_key: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    strategy_version: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    baseline_action: Mapped[BaselineAction] = mapped_column(
        SQLEnum(BaselineAction, name="baseline_action_type"),
        nullable=False,
    )

    baseline_allocation: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    recommendation = relationship(
        "Recommendation",
        foreign_keys=[recommendation_id],
        uselist=False,
        back_populates="baseline_decision",
    )

    __table_args__ = (
        UniqueConstraint("user_id", "recommendation_id", name="uq_baseline_decisions_user_recommendation"),
        Index("ix_baseline_decisions_user_created_at", "user_id", "created_at"),
    )
