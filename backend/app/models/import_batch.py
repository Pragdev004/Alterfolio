from datetime import datetime
from uuid import UUID

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.column_types import UTCDateTime
from app.domain import limits
from app.models.base import Base


class ImportBatch(Base):
    """One accepted tradebook upload. Counts are written after the rows are processed (plan 002, OPEN-10).

    Rejected rows are not stored. `file_sha256` is deliberately not unique: the same file may be uploaded again.
    """

    __tablename__ = "import_batches"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    file_name: Mapped[str] = mapped_column(String(limits.MAX_IMPORT_FILE_NAME_LENGTH))
    file_sha256: Mapped[str] = mapped_column(String(limits.MAX_FILE_SHA256_LENGTH))
    total_rows: Mapped[int] = mapped_column()
    imported: Mapped[int] = mapped_column()
    duplicates: Mapped[int] = mapped_column()
    rejected_total: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)

    __table_args__ = (
        UniqueConstraint("user_id", "id", name="uq_import_batches_user_id_id"),
        Index("ix_import_batches_user_id", "user_id"),
    )
