from uuid import UUID

from pydantic import BaseModel, model_validator

from app.schemas.display import DisplayKind, WithDisplay
from app.schemas.trade import WhenOut


class RejectedRowOut(BaseModel):
    """`row` is the 1-based physical line of the upload (the header is line 1)."""

    row: int
    code: str
    message: str


class ImportResultOut(BaseModel):
    import_batch_id: UUID
    file_name: str
    file_sha256: str
    total_rows: int
    imported: int
    duplicates: int
    rejected_total: int
    rejected: list[RejectedRowOut]  # the first 200 only; `rejected_total` is exact
    quarantined_isins: list[str]
    fees_taxes_provided: bool
    rejected_text: str | None = None  # "The first 200 of 350 rejected rows"; None when every rejected row is listed

    @model_validator(mode="after")
    def _counts_add_up(self) -> "ImportResultOut":
        if self.imported + self.duplicates + self.rejected_total != self.total_rows:
            raise ValueError("imported + duplicates + rejected_total must equal total_rows")
        return self


class ImportBatchOut(WithDisplay):
    import_batch_id: UUID
    file_name: str
    created_at: WhenOut
    total_rows: int
    imported: int
    duplicates: int
    rejected_total: int
    superseded: bool  # a newer upload of the same file exists


class ImportStatusOut(BaseModel):
    """What the ledger knows about past uploads. Rejected rows are not stored, only counted (the row list exists at upload time)."""

    batches: list[ImportBatchOut]
    rejected_rows_total: int
    warning: str | None  # "N rows were rejected at import; figures may be wrong", or None when nothing was rejected
