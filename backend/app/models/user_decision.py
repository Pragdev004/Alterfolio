from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum as SQLEnum, ForeignKey, Index, Numeric, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import UserDecisionType


class UserDecision(Base):
    __tablename__ = "user_decisions"

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

    trade_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("trades.id"),
        nullable=True,
        index=True,
    )

    decision_type: Mapped[UserDecisionType] = mapped_column(
        SQLEnum(UserDecisionType, name="user_decision_type"),
        nullable=False,
    )

    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    modified_allocation: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8),
        nullable=True,
    )

    decision_note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    recommendation = relationship("Recommendation", foreign_keys=[recommendation_id], uselist=False)
    trade = relationship("Trade", foreign_keys=[trade_id], uselist=False)

    __table_args__ = (
        UniqueConstraint("user_id", "recommendation_id", name="uq_user_decisions_user_recommendation"),
        Index("ix_user_decisions_user_decided_at", "user_id", "decided_at"),
    )
