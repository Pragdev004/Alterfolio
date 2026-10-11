from decimal import ROUND_HALF_EVEN

import pytest

from app.domain.enums import (
    AssetType,
    Currency,
    Exchange,
    MarketSession,
    TradeSide,
    TradeSource,
    TradeStatus,
)
from app.domain.instrument import Instrument
from app.domain.numeric import MONEY_CONTEXT, SCALE


def test_enum_members_match_the_spec():
    assert {m.value for m in AssetType} == {"STOCK", "ETF"}
    assert {m.value for m in Exchange} == {"NSE", "BSE"}
    assert {m.value for m in TradeSide} == {"BUY", "SELL"}
    assert {m.value for m in TradeSource} == {"MANUAL", "IMPORT"}
    assert {m.value for m in TradeStatus} == {"EXECUTED", "PENDING", "CANCELLED", "REJECTED"}
    assert {m.value for m in Currency} == {"INR"}
    assert {m.value for m in MarketSession} == {"PRE_MARKET", "REGULAR", "POST_MARKET"}


def test_instrument_identity_is_symbol_and_exchange():
    assert Instrument("RELIANCE", Exchange.NSE) == Instrument("RELIANCE", Exchange.NSE)
    assert Instrument("RELIANCE", Exchange.NSE) != Instrument("RELIANCE", Exchange.BSE)
    assert len({Instrument("X", Exchange.NSE), Instrument("X", Exchange.BSE)}) == 2


def test_instrument_is_frozen_and_rejects_empty_symbol():
    inst = Instrument("TCS", Exchange.NSE)
    with pytest.raises(AttributeError):
        inst.symbol = "INFY"  # type: ignore[misc]
    with pytest.raises(ValueError):
        Instrument("", Exchange.NSE)
    with pytest.raises(ValueError):
        Instrument("   ", Exchange.NSE)


def test_instrument_keeps_symbol_verbatim():
    assert Instrument("m&m", Exchange.NSE).symbol == "m&m"


def test_numeric_constants():
    assert SCALE == 6
    assert MONEY_CONTEXT.prec == 28
    assert MONEY_CONTEXT.rounding == ROUND_HALF_EVEN


def test_max_amount_is_the_documented_calculation_ceiling():
    from decimal import Decimal

    from app.domain.numeric import MAX_AMOUNT

    assert MAX_AMOUNT == Decimal(10) ** 15
