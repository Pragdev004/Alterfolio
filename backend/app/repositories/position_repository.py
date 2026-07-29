from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.enums import AssetType, Currency, Exchange
from app.models.position import Position


class PositionRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_position(
        self,
        *,
        user_id: UUID,
        asset_symbol: str,
        exchange: Exchange,
        asset_type: AssetType,
        currency: Currency,
    ) -> Position | None:
        return (
            self.db.query(Position)
            .filter(
                Position.user_id == user_id,
                Position.asset_symbol == asset_symbol,
                Position.exchange == exchange,
                Position.asset_type == asset_type,
                Position.currency == currency,
            )
            .first()
        )

    def upsert_position(
        self,
        *,
        user_id: UUID,
        asset_symbol: str,
        exchange: Exchange,
        asset_type: AssetType,
        currency: Currency,
        remaining_quantity: Decimal,
        remaining_cost_basis: Decimal,
        average_cost: Decimal,
        cumulative_realized_profit_loss: Decimal,
        last_accounted_trade_timestamp: datetime,
    ) -> Position:
        position = self.get_position(
            user_id=user_id,
            asset_symbol=asset_symbol,
            exchange=exchange,
            asset_type=asset_type,
            currency=currency,
        )

        if position is None:
            position = Position(
                user_id=user_id,
                asset_symbol=asset_symbol,
                exchange=exchange,
                asset_type=asset_type,
                currency=currency,
                remaining_quantity=remaining_quantity,
                remaining_cost_basis=remaining_cost_basis,
                average_cost=average_cost,
                cumulative_realized_profit_loss=cumulative_realized_profit_loss,
                last_accounted_trade_timestamp=last_accounted_trade_timestamp,
            )
            self.db.add(position)
        else:
            position.remaining_quantity = remaining_quantity
            position.remaining_cost_basis = remaining_cost_basis
            position.average_cost = average_cost
            position.cumulative_realized_profit_loss = cumulative_realized_profit_loss
            position.last_accounted_trade_timestamp = last_accounted_trade_timestamp

        self.db.commit()
        self.db.refresh(position)

        return position

    def list_active_positions(self, *, user_id: UUID) -> list[Position]:
        return (
            self.db.query(Position)
            .filter(
                Position.user_id == user_id,
                Position.remaining_quantity > 0,
            )
            .order_by(Position.asset_symbol.asc())
            .all()
        )

    def list_all_positions(self, *, user_id: UUID) -> list[Position]:
        return (
            self.db.query(Position)
            .filter(Position.user_id == user_id)
            .order_by(Position.last_accounted_trade_timestamp.desc())
            .all()
        )

    def lock_position(
        self,
        *,
        user_id: UUID,
        asset_symbol: str,
        exchange: Exchange,
        asset_type: AssetType,
        currency: Currency,
    ) -> Position | None:
        return (
            self.db.query(Position)
            .filter(
                Position.user_id == user_id,
                Position.asset_symbol == asset_symbol,
                Position.exchange == exchange,
                Position.asset_type == asset_type,
                Position.currency == currency,
            )
            .with_for_update()
            .first()
        )
