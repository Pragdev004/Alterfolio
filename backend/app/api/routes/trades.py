from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.repositories.trade_repository import TradeRepository
from app.schemas.trade import TradeCreate, TradeResponse
from app.services.trade_service import TradeService

router = APIRouter()


def get_trade_service(db: Session = Depends(get_db)) -> TradeService:
    repository = TradeRepository(db)
    return TradeService(repository)


@router.post("/", response_model=TradeResponse, status_code=201)
def create_trade(
    trade: TradeCreate,
    service: TradeService = Depends(get_trade_service),
):
    return service.create_trade(trade)


@router.get("/", response_model=list[TradeResponse])
def list_trades(
    service: TradeService = Depends(get_trade_service),
):
    return service.list_trades()


@router.get("/{trade_id}", response_model=TradeResponse)
def get_trade(
    trade_id: UUID,
    service: TradeService = Depends(get_trade_service),
):
    trade = service.get_trade(trade_id)

    if trade is None:
        raise HTTPException(
            status_code=404,
            detail="Trade not found",
        )

    return trade