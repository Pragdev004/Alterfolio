from uuid import UUID

from app.models.trade import Trade
from app.repositories.trade_repository import TradeRepository
from app.schemas.trade import TradeCreate


class TradeService:
    def __init__(self, repository: TradeRepository):
        self.repository = repository

    def create_trade(self, trade: TradeCreate) -> Trade:
        """
        Create a new trade.

        Business rules will be added here later.
        """
        return self.repository.create(trade)

    def get_trade(self, trade_id: UUID) -> Trade | None:
        """
        Fetch a trade by ID.
        """
        return self.repository.get_by_id(trade_id)

    def list_trades(self) -> list[Trade]:
        """
        Return all trades.
        """
        return self.repository.list_all()