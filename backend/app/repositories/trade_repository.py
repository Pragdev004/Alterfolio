from uuid import UUID

from sqlalchemy.orm import Session

from app.models.trade import Trade
from app.schemas.trade import TradeCreate


class TradeRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, trade: TradeCreate) -> Trade:
        db_trade = Trade(**trade.model_dump())

        self.db.add(db_trade)
        self.db.commit()
        self.db.refresh(db_trade)

        return db_trade

    def get_by_id(self, trade_id: UUID) -> Trade | None:
        return (
            self.db.query(Trade)
            .filter(Trade.id == trade_id)
            .first()
        )

    def list_all(self) -> list[Trade]:
        return (
            self.db.query(Trade)
            .order_by(Trade.trade_timestamp.desc())
            .all()
        )