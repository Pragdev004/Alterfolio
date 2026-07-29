from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.models.enums import TransactionType


@dataclass(frozen=True)
class PositionAccountingResult:
    remaining_quantity: Decimal
    remaining_cost_basis: Decimal
    average_cost: Decimal
    realized_pl: Decimal
    cost_basis_relieved: Decimal


class OversellError(ValueError):
    """Raised when a sell quantity exceeds the available position quantity."""


class PositionAccountingService:
    """Weighted-average position accounting engine."""

    @staticmethod
    def apply_trade(
        *,
        current_quantity: Decimal,
        current_cost_basis: Decimal,
        transaction_type: TransactionType,
        quantity: Decimal,
        price_per_unit: Decimal,
        brokerage_fee: Decimal = Decimal("0"),
        taxes: Decimal = Decimal("0"),
    ) -> PositionAccountingResult:
        current_quantity = PositionAccountingService._as_decimal(current_quantity)
        current_cost_basis = PositionAccountingService._as_decimal(current_cost_basis)
        quantity = PositionAccountingService._as_decimal(quantity)
        price_per_unit = PositionAccountingService._as_decimal(price_per_unit)
        brokerage_fee = PositionAccountingService._as_decimal(brokerage_fee)
        taxes = PositionAccountingService._as_decimal(taxes)

        PositionAccountingService._validate_inputs(
            current_quantity=current_quantity,
            current_cost_basis=current_cost_basis,
            quantity=quantity,
            price_per_unit=price_per_unit,
            brokerage_fee=brokerage_fee,
            taxes=taxes,
        )

        if transaction_type == TransactionType.BUY:
            return PositionAccountingService._apply_buy(
                current_quantity=current_quantity,
                current_cost_basis=current_cost_basis,
                quantity=quantity,
                price_per_unit=price_per_unit,
                brokerage_fee=brokerage_fee,
                taxes=taxes,
            )

        if transaction_type == TransactionType.SELL:
            return PositionAccountingService._apply_sell(
                current_quantity=current_quantity,
                current_cost_basis=current_cost_basis,
                quantity=quantity,
                price_per_unit=price_per_unit,
                brokerage_fee=brokerage_fee,
                taxes=taxes,
            )

        raise ValueError(f"Unsupported transaction type: {transaction_type}")

    @staticmethod
    def _apply_buy(
        *,
        current_quantity: Decimal,
        current_cost_basis: Decimal,
        quantity: Decimal,
        price_per_unit: Decimal,
        brokerage_fee: Decimal,
        taxes: Decimal,
    ) -> PositionAccountingResult:
        acquisition_cost = (quantity * price_per_unit) + brokerage_fee + taxes
        remaining_quantity = current_quantity + quantity
        remaining_cost_basis = current_cost_basis + acquisition_cost
        average_cost = remaining_cost_basis / remaining_quantity

        return PositionAccountingResult(
            remaining_quantity=remaining_quantity,
            remaining_cost_basis=remaining_cost_basis,
            average_cost=average_cost,
            realized_pl=Decimal("0"),
            cost_basis_relieved=Decimal("0"),
        )

    @staticmethod
    def _apply_sell(
        *,
        current_quantity: Decimal,
        current_cost_basis: Decimal,
        quantity: Decimal,
        price_per_unit: Decimal,
        brokerage_fee: Decimal,
        taxes: Decimal,
    ) -> PositionAccountingResult:
        if quantity > current_quantity:
            raise OversellError(
                f"Cannot sell {quantity} units with only {current_quantity} units available"
            )

        average_cost = current_cost_basis / current_quantity
        cost_basis_relieved = average_cost * quantity
        net_proceeds = (quantity * price_per_unit) - brokerage_fee - taxes
        realized_pl = net_proceeds - cost_basis_relieved

        remaining_quantity = current_quantity - quantity
        if remaining_quantity == Decimal("0"):
            remaining_cost_basis = Decimal("0")
            new_average_cost = Decimal("0")
        else:
            remaining_cost_basis = current_cost_basis - cost_basis_relieved
            new_average_cost = remaining_cost_basis / remaining_quantity

        return PositionAccountingResult(
            remaining_quantity=remaining_quantity,
            remaining_cost_basis=remaining_cost_basis,
            average_cost=new_average_cost,
            realized_pl=realized_pl,
            cost_basis_relieved=cost_basis_relieved,
        )

    @staticmethod
    def _validate_inputs(
        *,
        current_quantity: Decimal,
        current_cost_basis: Decimal,
        quantity: Decimal,
        price_per_unit: Decimal,
        brokerage_fee: Decimal,
        taxes: Decimal,
    ) -> None:
        if current_quantity < Decimal("0"):
            raise ValueError("current_quantity cannot be negative")
        if current_cost_basis < Decimal("0"):
            raise ValueError("current_cost_basis cannot be negative")
        if quantity <= Decimal("0"):
            raise ValueError("quantity must be greater than zero")
        if price_per_unit < Decimal("0"):
            raise ValueError("price_per_unit cannot be negative")
        if brokerage_fee < Decimal("0"):
            raise ValueError("brokerage_fee cannot be negative")
        if taxes < Decimal("0"):
            raise ValueError("taxes cannot be negative")

    @staticmethod
    def _as_decimal(value: Decimal) -> Decimal:
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))
