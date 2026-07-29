from uuid import UUID

from app.repositories.portfolio_repository import PortfolioRepository
from app.schemas.portfolio import PortfolioSummary


class PortfolioService:
    def __init__(self, repository: PortfolioRepository):
        self.repository = repository

    def get_summary(self, user_id: UUID) -> PortfolioSummary:
        """
        Returns a complete portfolio summary for the authenticated user.
        Future calculations like P&L, XIRR, CAGR,
        diversification and risk score will live here.
        """
        return self.repository.get_summary(user_id)