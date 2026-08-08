from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_authenticated_user_id
from app.db.database import get_db
from app.repositories.position_repository import PositionRepository
from app.repositories.trade_repository import TradeRepository

from app.schemas.trade import TradeCreate, TradeResponse
from app.services.trade_service import TradeService


router = APIRouter()


def get_trade_service(db: Session = Depends(get_db)) -> TradeService:
    trade_repository = TradeRepository(db)
    position_repository = PositionRepository(db)
    return TradeService(
        db=db,
        trade_repository=trade_repository,
        position_repository=position_repository,
    )



@router.post("/", response_model=TradeResponse, status_code=201)
def create_trade(
    trade: TradeCreate,
    service: TradeService = Depends(get_trade_service),
    user_id: UUID = Depends(get_authenticated_user_id),
):
    return service.create_trade(trade, user_id)



@router.get("/", response_model=list[TradeResponse])
def list_trades(
    service: TradeService = Depends(get_trade_service),
    user_id: UUID = Depends(get_authenticated_user_id),
):
    return service.list_trades(user_id)



@router.get("/{trade_id}", response_model=TradeResponse)
def get_trade(
    trade_id: UUID,
    service: TradeService = Depends(get_trade_service),
    user_id: UUID = Depends(get_authenticated_user_id),
):
    trade = service.get_trade(trade_id, user_id)


    if trade is None:
        raise HTTPException(
            status_code=404,
            detail="Trade not found",
        )

    return trade