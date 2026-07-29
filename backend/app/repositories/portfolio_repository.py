from decimal import Decimal
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.enums import TransactionType
from app.models.trade import Trade
from app.schemas.portfolio import HoldingSummary, PortfolioSummary


class PortfolioRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_summary(self, user_id: UUID) -> PortfolioSummary:
        total_trades = (
            self.db.query(Trade)
            .filter(Trade.user_id == user_id)
            .count()
        )

        quantity_sum = func.sum(Trade.quantity)
        invested_sum = func.sum(Trade.quantity * Trade.price_per_unit)

        holdings_query = (
            self.db.query(
                Trade.asset_symbol.label("symbol"),
                quantity_sum.label("quantity"),
                (invested_sum / func.nullif(quantity_sum, 0)).label(
                    "average_buy_price"
                ),
                invested_sum.label("invested_amount"),
            )
            .filter(
                Trade.user_id == user_id,
                Trade.transaction_type == TransactionType.BUY,
            )
            .group_by(Trade.asset_symbol)
            .having(quantity_sum != 0)
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