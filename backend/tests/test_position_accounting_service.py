from decimal import Decimal

import pytest

from app.models.enums import TransactionType
from app.services.position_accounting_service import (
    OversellError,
    PositionAccountingService,
)


def test_single_buy() -> None:
    result = PositionAccountingService.apply_trade(
        current_quantity=Decimal("0"),
        current_cost_basis=Decimal("0"),
        transaction_type=TransactionType.BUY,
        quantity=Decimal("10"),
        price_per_unit=Decimal("100"),
    )

    assert result.remaining_quantity == Decimal("10")
    assert result.remaining_cost_basis == Decimal("1000")
    assert result.average_cost == Decimal("100")
    assert result.realized_pl == Decimal("0")
    assert result.cost_basis_relieved == Decimal("0")


def test_multiple_buys_weighted_average_cost() -> None:
    first_buy = PositionAccountingService.apply_trade(
        current_quantity=Decimal("0"),
        current_cost_basis=Decimal("0"),
        transaction_type=TransactionType.BUY,
        quantity=Decimal("10"),
        price_per_unit=Decimal("100"),
    )

    second_buy = PositionAccountingService.apply_trade(
        current_quantity=first_buy.remaining_quantity,
        current_cost_basis=first_buy.remaining_cost_basis,
        transaction_type=TransactionType.BUY,
        quantity=Decimal("5"),
        price_per_unit=Decimal("160"),
    )

    assert second_buy.remaining_quantity == Decimal("15")
    assert second_buy.remaining_cost_basis == Decimal("1800")
    assert second_buy.average_cost == Decimal("120")
    assert second_buy.realized_pl == Decimal("0")
    assert second_buy.cost_basis_relieved == Decimal("0")


def test_partial_sell_relives_weighted_cost_basis_and_realizes_pl() -> None:
    position = PositionAccountingService.apply_trade(
        current_quantity=Decimal("0"),
        current_cost_basis=Decimal("0"),
        transaction_type=TransactionType.BUY,
        quantity=Decimal("10"),
        price_per_unit=Decimal("100"),
    )
    position = PositionAccountingService.apply_trade(
        current_quantity=position.remaining_quantity,
        current_cost_basis=position.remaining_cost_basis,
        transaction_type=TransactionType.BUY,
        quantity=Decimal("5"),
        price_per_unit=Decimal("160"),
    )

    sell = PositionAccountingService.apply_trade(
        current_quantity=position.remaining_quantity,
        current_cost_basis=position.remaining_cost_basis,
        transaction_type=TransactionType.SELL,
        quantity=Decimal("3"),
        price_per_unit=Decimal("150"),
    )

    assert sell.cost_basis_relieved == Decimal("360")
    assert sell.realized_pl == Decimal("90")
    assert sell.remaining_quantity == Decimal("12")
    assert sell.remaining_cost_basis == Decimal("1440")
    assert sell.average_cost == Decimal("120")


def test_multiple_sells() -> None:
    position = PositionAccountingService.apply_trade(
        current_quantity=Decimal("0"),
        current_cost_basis=Decimal("0"),
        transaction_type=TransactionType.BUY,
        quantity=Decimal("10"),
        price_per_unit=Decimal("100"),
    )
    position = PositionAccountingService.apply_trade(
        current_quantity=position.remaining_quantity,
        current_cost_basis=position.remaining_cost_basis,
        transaction_type=TransactionType.BUY,
        quantity=Decimal("10"),
        price_per_unit=Decimal("200"),
    )

    first_sell = PositionAccountingService.apply_trade(
        current_quantity=position.remaining_quantity,
        current_cost_basis=position.remaining_cost_basis,
        transaction_type=TransactionType.SELL,
        quantity=Decimal("4"),
        price_per_unit=Decimal("180"),
    )

    second_sell = PositionAccountingService.apply_trade(
        current_quantity=first_sell.remaining_quantity,
        current_cost_basis=first_sell.remaining_cost_basis,
        transaction_type=TransactionType.SELL,
        quantity=Decimal("6"),
        price_per_unit=Decimal("130"),
    )

    assert first_sell.cost_basis_relieved == Decimal("600")
    assert first_sell.realized_pl == Decimal("120")
    assert first_sell.remaining_quantity == Decimal("16")
    assert first_sell.remaining_cost_basis == Decimal("2400")
    assert first_sell.average_cost == Decimal("150")

    assert second_sell.cost_basis_relieved == Decimal("900")
    assert second_sell.realized_pl == Decimal("-120")
    assert second_sell.remaining_quantity == Decimal("10")
    assert second_sell.remaining_cost_basis == Decimal("1500")
    assert second_sell.average_cost == Decimal("150")


def test_full_liquidation_resets_remaining_position() -> None:
    buy = PositionAccountingService.apply_trade(
        current_quantity=Decimal("0"),
        current_cost_basis=Decimal("0"),
        transaction_type=TransactionType.BUY,
        quantity=Decimal("4"),
        price_per_unit=Decimal("25.5"),
    )

    sell = PositionAccountingService.apply_trade(
        current_quantity=buy.remaining_quantity,
        current_cost_basis=buy.remaining_cost_basis,
        transaction_type=TransactionType.SELL,
        quantity=Decimal("4"),
        price_per_unit=Decimal("30"),
    )

    assert sell.cost_basis_relieved == Decimal("102")
    assert sell.realized_pl == Decimal("18")
    assert sell.remaining_quantity == Decimal("0")
    assert sell.remaining_cost_basis == Decimal("0")
    assert sell.average_cost == Decimal("0")


def test_oversell_rejection() -> None:
    with pytest.raises(OversellError):
        PositionAccountingService.apply_trade(
            current_quantity=Decimal("2"),
            current_cost_basis=Decimal("50"),
            transaction_type=TransactionType.SELL,
            quantity=Decimal("3"),
            price_per_unit=Decimal("30"),
        )


def test_decimal_precision_preserved() -> None:
    first_buy = PositionAccountingService.apply_trade(
        current_quantity=Decimal("0"),
        current_cost_basis=Decimal("0"),
        transaction_type=TransactionType.BUY,
        quantity=Decimal("0.1"),
        price_per_unit=Decimal("100.10"),
    )

    second_buy = PositionAccountingService.apply_trade(
        current_quantity=first_buy.remaining_quantity,
        current_cost_basis=first_buy.remaining_cost_basis,
        transaction_type=TransactionType.BUY,
        quantity=Decimal("0.2"),
        price_per_unit=Decimal("100.20"),
    )

    sell = PositionAccountingService.apply_trade(
        current_quantity=second_buy.remaining_quantity,
        current_cost_basis=second_buy.remaining_cost_basis,
        transaction_type=TransactionType.SELL,
        quantity=Decimal("0.1"),
        price_per_unit=Decimal("100.30"),
    )

    expected_avg = Decimal("30.05") / Decimal("0.3")
    expected_relieved = expected_avg * Decimal("0.1")
    expected_realized = Decimal("10.03") - expected_relieved

    assert second_buy.remaining_quantity == Decimal("0.3")
    assert second_buy.remaining_cost_basis == Decimal("30.05")
    assert second_buy.average_cost == expected_avg

    assert sell.remaining_quantity == Decimal("0.2")
    assert sell.cost_basis_relieved == expected_relieved
    assert sell.realized_pl == expected_realized
