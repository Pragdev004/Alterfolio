from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Mapped, mapped_column

from app.db.column_types import UTCDateTime
from app.models.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=lambda: datetime.now(timezone.utc)
    )
