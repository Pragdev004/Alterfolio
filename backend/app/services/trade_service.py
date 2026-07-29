from uuid import UUID

from app.models.trade import Trade
from app.repositories.trade_repository import TradeRepository
from app.schemas.trade import TradeCreate


class TradeService:
    def __init__(self, repository: TradeRepository):
        self.repository = repository

    def create_trade(self, trade: TradeCreate, user_id: UUID) -> Trade:
        """
        Create a new trade for the authenticated user.

        Business rules will be added here later.
        """
        return self.repository.create(trade, user_id)

    def get_trade(self, trade_id: UUID, user_id: UUID) -> Trade | None:
        """
        Fetch a trade by ID for the authenticated user.
        """
        return self.repository.get_by_id(trade_id, user_id)

    def list_trades(self, user_id: UUID) -> list[Trade]:
        """
        Return all trades for the authenticated user.
        """
        return self.repository.list_all(user_id)