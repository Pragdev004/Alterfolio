from uuid import UUID

from pydantic import BaseModel, model_validator


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

    @model_validator(mode="after")
    def _counts_add_up(self) -> "ImportResultOut":
        if self.imported + self.duplicates + self.rejected_total != self.total_rows:
            raise ValueError("imported + duplicates + rejected_total must equal total_rows")
        return self
