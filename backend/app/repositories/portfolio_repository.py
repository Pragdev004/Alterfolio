from uuid import UUID

from sqlalchemy.orm import Session

from app.models.trade import Trade


class PortfolioRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_total_trades(self, user_id: UUID) -> int:
        return (
            self.db.query(Trade)
            .filter(Trade.user_id == user_id)
            .count()
        )