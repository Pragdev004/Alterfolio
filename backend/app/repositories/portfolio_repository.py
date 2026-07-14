from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.enums import TransactionType
from app.models.trade import Trade
from app.schemas.portfolio import HoldingSummary, PortfolioSummary


class PortfolioRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_summary(self) -> PortfolioSummary:
        total_trades = self.db.query(Trade).count()

        holdings_query = (
            self.db.query(
                Trade.asset_symbol.label("symbol"),
                func.sum(Trade.quantity).label("quantity"),
                (
                    func.sum(Trade.quantity * Trade.price_per_unit)
                    / func.sum(Trade.quantity)
                ).label("average_buy_price"),
                func.sum(
                    Trade.quantity * Trade.price_per_unit
                ).label("invested_amount"),
            )
            .filter(Trade.transaction_type == TransactionType.BUY)
            .group_by(Trade.asset_symbol)
            .all()
        )

        holdings = [
            HoldingSummary(
                symbol=row.symbol,
                quantity=row.quantity or Decimal("0"),
                average_buy_price=row.average_buy_price or Decimal("0"),
                invested_amount=row.invested_amount or Decimal("0"),
            )
            for row in holdings_query
        ]

        total_invested = sum(
            (holding.invested_amount for holding in holdings),
            Decimal("0"),
        )

        return PortfolioSummary(
            total_trades=total_trades,
            total_invested=total_invested,
            holdings=holdings,
        )