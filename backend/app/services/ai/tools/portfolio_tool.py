from app.schemas.portfolio import PortfolioSummary
from app.services.portfolio_service import PortfolioService


class PortfolioTool:
    """
    AI tool for retrieving portfolio information.
    """

    def __init__(
        self,
        portfolio_service: PortfolioService,
    ) -> None:
        self._portfolio_service = portfolio_service

    def get_portfolio_summary(self) -> PortfolioSummary:
        """
        Returns the user's portfolio summary.
        """
        return self._portfolio_service.get_summary()