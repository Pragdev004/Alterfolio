"""HoldingKey (plan 002a OPEN-1, 1b): ISIN identity, with legacy (symbol, exchange) keys kept apart."""
import dataclasses

import pytest

from app.domain.enums import Exchange
from app.domain.holding_key import HoldingKey

ISIN = "ZZ0ALPHA0001"


def test_an_isin_key_ignores_exchange_and_symbol():
    assert HoldingKey.of(ISIN, "ALPHACO", Exchange.NSE) == HoldingKey.of(ISIN, "OTHER", Exchange.BSE) == HoldingKey.for_isin(ISIN)
    assert hash(HoldingKey.of(ISIN, "ALPHACO", Exchange.NSE)) == hash(HoldingKey.of(ISIN, "ALPHACO", Exchange.BSE))


def test_different_isins_are_different_keys():
    assert HoldingKey.for_isin(ISIN) != HoldingKey.for_isin("ZZ0BETACO001")


def test_a_legacy_key_is_symbol_and_exchange():
    assert HoldingKey.of(None, "ALPHACO", Exchange.NSE) == HoldingKey.legacy("ALPHACO", Exchange.NSE)
    assert HoldingKey.legacy("ALPHACO", Exchange.NSE) != HoldingKey.legacy("ALPHACO", Exchange.BSE)
    assert HoldingKey.legacy("ALPHACO", Exchange.NSE) != HoldingKey.legacy("BETACO", Exchange.NSE)


def test_a_legacy_key_never_equals_an_isin_key():
    assert HoldingKey.legacy("ALPHACO", Exchange.NSE) != HoldingKey.for_isin(ISIN)
    assert HoldingKey.legacy(ISIN, Exchange.NSE) != HoldingKey.for_isin(ISIN)  # even a symbol that looks like the ISIN


def test_keys_are_hashable_and_usable_in_sets():
    keys = {HoldingKey.of(ISIN, "A", Exchange.NSE), HoldingKey.of(ISIN, "A", Exchange.BSE), HoldingKey.of(None, "A", Exchange.NSE)}
    assert len(keys) == 2


def test_sort_order_is_isin_ascending_then_legacy_by_symbol_and_exchange():
    keys = [
        HoldingKey.legacy("B", Exchange.NSE),
        HoldingKey.for_isin("ZZ0BETACO001"),
        HoldingKey.legacy("A", Exchange.NSE),
        HoldingKey.for_isin(ISIN),
        HoldingKey.legacy("A", Exchange.BSE),
    ]
    assert sorted(keys, key=lambda k: k.sort_key) == [
        HoldingKey.for_isin(ISIN),
        HoldingKey.for_isin("ZZ0BETACO001"),
        HoldingKey.legacy("A", Exchange.BSE),
        HoldingKey.legacy("A", Exchange.NSE),
        HoldingKey.legacy("B", Exchange.NSE),
    ]


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"isin": ""},
        {"isin": "  "},
        {"isin": ISIN, "symbol": "A"},
        {"isin": ISIN, "exchange": Exchange.NSE},
        {"symbol": "A"},
        {"exchange": Exchange.NSE},
        {"symbol": " ", "exchange": Exchange.NSE},
        {"symbol": "A", "exchange": "NSE"},
    ],
)
def test_malformed_keys_are_refused(kwargs):
    with pytest.raises(ValueError):
        HoldingKey(**kwargs)


def test_keys_are_immutable():
    with pytest.raises(dataclasses.FrozenInstanceError):
        HoldingKey.for_isin(ISIN).isin = "X"
