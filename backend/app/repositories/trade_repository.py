from uuid import UUID

from sqlalchemy.orm import Session

from app.models.trade import Trade
from app.schemas.trade import TradeCreate


class TradeRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, trade: TradeCreate, user_id: UUID) -> Trade:
        trade_data = trade.model_dump(exclude={"user_id"})
        db_trade = Trade(**trade_data, user_id=user_id)

        self.db.add(db_trade)
        self.db.commit()
        self.db.refresh(db_trade)

        return db_trade

    def get_by_id(self, trade_id: UUID, user_id: UUID) -> Trade | None:
        return (
            self.db.query(Trade)
            .filter(
                Trade.id == trade_id,
                Trade.user_id == user_id,
            )
            .first()
        )

    def list_all(self, user_id: UUID) -> list[Trade]:
        return (
            self.db.query(Trade)
            .filter(Trade.user_id == user_id)
            .order_by(Trade.trade_timestamp.desc())
            .all()
        )