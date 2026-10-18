from uuid import UUID

from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_user_id, get_import_service
from app.api.uploads import read_tradebook_upload
from app.schemas.imports import ImportBatchOut, ImportResultOut, ImportStatusOut, RejectedRowOut
from app.services.tradebook_import import TradebookImportService

router = APIRouter(prefix="/imports")


@router.post("/tradebook", status_code=201, response_model=ImportResultOut)
async def import_tradebook(
    request: Request,
    user_id: UUID = Depends(get_current_user_id),
    importer: TradebookImportService = Depends(get_import_service),
):
    """Transport only: stream the single `file` part (2 MiB cap enforced while reading), then hand it to the service.

    The service parses before it takes the user lock and owns the transaction. It is synchronous, so it runs in the
    thread pool rather than on the event loop. File-level failures are 422 `invalid_import_file`; a held lock is 409.
    """
    upload = await read_tradebook_upload(request)
    result = await run_in_threadpool(
        importer.import_tradebook, user_id=user_id, file_name=upload.file_name, content=upload.content
    )
    return ImportResultOut(
        import_batch_id=result.import_batch_id,
        file_name=result.file_name,
        file_sha256=result.file_sha256,
        total_rows=result.total_rows,
        imported=result.imported,
        duplicates=result.duplicates,
        rejected_total=result.rejected_total,
        rejected=[RejectedRowOut(row=r.line, code=r.code, message=r.message) for r in result.rejected],
        quarantined_isins=list(result.quarantined_isins),
        fees_taxes_provided=result.fees_taxes_provided,
        rejected_text=None if result.rejected_total <= len(result.rejected)
        else f"The first {len(result.rejected)} of {result.rejected_total} rejected rows",
    )


@router.get("/status", response_model=ImportStatusOut)
def import_status(
    user_id: UUID = Depends(get_current_user_id),
    importer: TradebookImportService = Depends(get_import_service),
):
    """Past uploads and the rejected-row warning shown on Holdings and Trips."""
    status = importer.status(user_id=user_id)
    n = status.rejected_rows_total
    return ImportStatusOut(
        batches=[
            ImportBatchOut(
                import_batch_id=b.batch.id, file_name=b.batch.file_name, created_at=b.batch.created_at,
                total_rows=b.batch.total_rows, imported=b.batch.imported, duplicates=b.batch.duplicates,
                rejected_total=b.batch.rejected_total, superseded=b.superseded,
            )
            for b in status.batches
        ],
        rejected_rows_total=n,
        warning=None if n == 0 else f"{n} {'row was' if n == 1 else 'rows were'} rejected at import; figures may be wrong",
    )
