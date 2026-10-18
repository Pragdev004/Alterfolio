from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.import_batch import ImportBatch


class ImportBatchRepository:
    """Every method is user-scoped. The counters are the only thing ever changed, and only by `update_counts`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(
        self, *, user_id: UUID, id: UUID, file_name: str, file_sha256: str, created_at: datetime,
        total_rows: int = 0, imported: int = 0, duplicates: int = 0, rejected_total: int = 0,
    ) -> ImportBatch:
        batch = ImportBatch(
            id=id, user_id=user_id, file_name=file_name, file_sha256=file_sha256, created_at=created_at,
            total_rows=total_rows, imported=imported, duplicates=duplicates, rejected_total=rejected_total,
        )
        self._session.add(batch)
        self._session.flush()
        return batch

    def get(self, *, user_id: UUID, batch_id: UUID) -> ImportBatch | None:
        return self._session.scalars(
            select(ImportBatch).where(ImportBatch.user_id == user_id, ImportBatch.id == batch_id)
        ).one_or_none()

    def update_counts(
        self, *, user_id: UUID, batch_id: UUID, total_rows: int, imported: int, duplicates: int, rejected_total: int
    ) -> ImportBatch:
        """Set the four counters of the user's own batch; another user's or an unknown batch raises LookupError."""
        batch = self.get(user_id=user_id, batch_id=batch_id)
        if batch is None:
            raise LookupError("import batch not found for this user")
        batch.total_rows = total_rows
        batch.imported = imported
        batch.duplicates = duplicates
        batch.rejected_total = rejected_total
        self._session.flush()
        return batch

    def list_for_user(self, *, user_id: UUID) -> list[ImportBatch]:
        """The user's batches, newest first."""
        return list(self._session.scalars(
            select(ImportBatch).where(ImportBatch.user_id == user_id).order_by(ImportBatch.created_at.desc(), ImportBatch.id)
        ))
