from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_ledger, get_session
from app.schemas.trade import TradeIn, TradeOut
from app.services.ledger import LedgerService, TradeInput

router = APIRouter(prefix="/trades")


@router.post("", status_code=201, response_model=TradeOut)
def create_trade(
    payload: TradeIn,
    user_id: UUID = Depends(get_current_user_id),
    ledger: LedgerService = Depends(get_ledger),
    session: Session = Depends(get_session),
):
    trade = ledger.record(user_id=user_id, data=TradeInput(**payload.model_dump()))
    session.commit()
    return trade


@router.get("", response_model=list[TradeOut])
def list_trades(
    user_id: UUID = Depends(get_current_user_id),
    ledger: LedgerService = Depends(get_ledger),
):
    return ledger.list_trades(user_id=user_id)


@router.get("/{trade_id}", response_model=TradeOut)
def get_trade(
    trade_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    ledger: LedgerService = Depends(get_ledger),
):
    return ledger.get_trade(user_id=user_id, trade_id=trade_id)


@router.post("/{trade_id}/correct", status_code=201, response_model=TradeOut)
def correct_trade(
    trade_id: UUID,
    payload: TradeIn,
    user_id: UUID = Depends(get_current_user_id),
    ledger: LedgerService = Depends(get_ledger),
    session: Session = Depends(get_session),
):
    trade = ledger.correct(
        user_id=user_id, trade_id=trade_id, data=TradeInput(**payload.model_dump())
    )
    session.commit()
    return trade


@router.post("/{trade_id}/void", status_code=201, response_model=TradeOut)
def void_trade(
    trade_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    ledger: LedgerService = Depends(get_ledger),
    session: Session = Depends(get_session),
):
    trade = ledger.void(user_id=user_id, trade_id=trade_id)
    session.commit()
    return trade
