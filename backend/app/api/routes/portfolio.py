from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user_id, get_ledger
from app.schemas.trade import HoldingOut
from app.services.ledger import LedgerService

router = APIRouter(prefix="/portfolio")


@router.get("/holdings", response_model=list[HoldingOut])
def holdings(
    as_of: datetime | None = None,
    user_id: UUID = Depends(get_current_user_id),
    ledger: LedgerService = Depends(get_ledger),
):
    return [
        HoldingOut(
            symbol=h.instrument.symbol,
            exchange=h.instrument.exchange,
            quantity=h.quantity,
            average_buy_price=h.average_buy_price,
            invested_amount=h.invested_amount,
        )
        for h in ledger.holdings(user_id=user_id, as_of=as_of)
    ]
