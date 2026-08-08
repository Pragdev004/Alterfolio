from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.enums import TradeStatus
from app.models.trade import Trade
from app.repositories.position_repository import PositionRepository
from app.repositories.trade_repository import TradeRepository
from app.schemas.trade import TradeCreate
from app.services.position_accounting_service import PositionAccountingService


class TradeService:
    def __init__(
        self,
        db: Session,
        trade_repository: TradeRepository,
        position_repository: PositionRepository,
    ):
        self.db = db
        self.trade_repository = trade_repository
        self.position_repository = position_repository

    def create_trade(self, trade: TradeCreate, user_id: UUID) -> Trade:
        """
        Create a new trade for the authenticated user.

        Trade persistence and position accounting are applied atomically.
        """
        try:
            created_trade = self.trade_repository.create(trade, user_id)

            if created_trade.status == TradeStatus.EXECUTED:
                self._apply_executed_trade_to_position(created_trade)

            self.db.commit()
            self.db.refresh(created_trade)
            return created_trade
        except Exception:
            self.db.rollback()
            raise

    def _apply_executed_trade_to_position(self, trade: Trade) -> None:
        existing_position = self.position_repository.lock_position(
            user_id=trade.user_id,
            asset_symbol=trade.asset_symbol,
            exchange=trade.exchange,
            asset_type=trade.asset_type,
            currency=trade.currency,
        )

        current_quantity = (
            existing_position.remaining_quantity
            if existing_position is not None
            else Decimal("0")
        )
        current_cost_basis = (
            existing_position.remaining_cost_basis
            if existing_position is not None
            else Decimal("0")
        )
        current_cumulative_realized_pl = (
            existing_position.cumulative_realized_profit_loss
            if existing_position is not None
            else Decimal("0")
        )

        accounting_result = PositionAccountingService.apply_trade(
            current_quantity=current_quantity,
            current_cost_basis=current_cost_basis,
            transaction_type=trade.transaction_type,
            quantity=trade.quantity,
            price_per_unit=trade.price_per_unit,
            brokerage_fee=trade.brokerage_fee,
            taxes=trade.taxes,
        )

        self.position_repository.upsert_position(
            user_id=trade.user_id,
            asset_symbol=trade.asset_symbol,
            exchange=trade.exchange,
            asset_type=trade.asset_type,
            currency=trade.currency,
            remaining_quantity=accounting_result.remaining_quantity,
            remaining_cost_basis=accounting_result.remaining_cost_basis,
            average_cost=accounting_result.average_cost,
            cumulative_realized_profit_loss=current_cumulative_realized_pl
            + accounting_result.realized_pl,
            last_accounted_trade_timestamp=trade.trade_timestamp,
        )

    def get_trade(self, trade_id: UUID, user_id: UUID) -> Trade | None:
        """
        Fetch a trade by ID for the authenticated user.
        """
        return self.trade_repository.get_by_id(trade_id, user_id)

    def list_trades(self, user_id: UUID) -> list[Trade]:
        """
        Return all trades for the authenticated user.
        """
        return self.trade_repository.list_all(user_id)