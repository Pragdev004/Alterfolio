"""Feature 013a: read-only analysis endpoints. The user always comes from the auth dependency; `as_of` defaults to the latest
sealed day and today or later is rejected (422 `as_of_not_sealed`). No AI is involved anywhere on this path."""

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api import analysis_presenter as present
from app.api.deps import get_analysis_reader, get_current_user_id
from app.services.analysis_read import AnalysisReadService
from app.services.errors import AnalysisTripNotFoundError

router = APIRouter(prefix="/api/analysis")


@router.get("/meta")
def meta(user_id: UUID = Depends(get_current_user_id), reader: AnalysisReadService = Depends(get_analysis_reader)):
    return present.meta(reader.meta(user_id))


@router.get("/trips")
def trips(as_of: date | None = None, user_id: UUID = Depends(get_current_user_id),
          reader: AnalysisReadService = Depends(get_analysis_reader)):
    day, defaulted = reader.resolve_as_of(as_of)
    return present.trips(reader.view(user_id, day), defaulted)


@router.get("/trips/{trip_id}")
def trip(trip_id: str, as_of: date | None = None, user_id: UUID = Depends(get_current_user_id),
         reader: AnalysisReadService = Depends(get_analysis_reader)):
    day, defaulted = reader.resolve_as_of(as_of)
    view = reader.view(user_id, day)
    found = next((t for t in view.trips if t.trip_id == trip_id), None)
    if found is None:
        raise AnalysisTripNotFoundError(trip_id)
    return present.trip_detail(view, found, defaulted)


@router.get("/regimes")
def regimes(as_of: date | None = None, user_id: UUID = Depends(get_current_user_id),
            reader: AnalysisReadService = Depends(get_analysis_reader)):
    day, defaulted = reader.resolve_as_of(as_of)
    return present.regimes(reader.view(user_id, day), defaulted)


@router.get("/biases")
def biases(as_of: date | None = None, user_id: UUID = Depends(get_current_user_id),
           reader: AnalysisReadService = Depends(get_analysis_reader)):
    day, defaulted = reader.resolve_as_of(as_of)
    return present.biases(reader.view(user_id, day), defaulted)
