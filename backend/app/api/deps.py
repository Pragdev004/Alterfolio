from collections.abc import Iterator
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.services.ledger import LedgerService
from app.services.tradebook_import import TradebookImportService


def get_session(request: Request) -> Iterator[Session]:
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()  # rolls back anything a route did not commit


def get_current_user_id(request: Request) -> UUID:
    """Single local user (U7). Replace this one dependency when real auth arrives."""
    return request.app.state.settings.user_id


def get_ledger(request: Request, session: Session = Depends(get_session)) -> LedgerService:
    return LedgerService.for_session(
        session, clock=request.app.state.clock, id_factory=request.app.state.id_factory
    )


def get_import_service(request: Request, session: Session = Depends(get_session)) -> TradebookImportService:
    return TradebookImportService.for_session(
        session, clock=request.app.state.clock, id_factory=request.app.state.id_factory
    )
