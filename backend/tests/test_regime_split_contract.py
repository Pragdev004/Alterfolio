"""Feature 008 contract: pins the Feature 006/007 interfaces it consumes, and the one-to-one round trip -> trip mapping."""

import dataclasses
import inspect
from datetime import date
from decimal import Decimal as D

import pytest

from app.quant.bias_cost.analysis import analyze_biases
from app.quant.bias_cost.cost_basis import RoundTrip, fold_positions
from app.quant.bias_cost.types import LedgerTrade
from app.quant.bias_cost.validation import ValidatedBiasInputs, validate_inputs
from app.quant.luck_test.analysis import analyze_luck
from app.quant.luck_test.features import ListingBars, PreTradeView, volatility
from app.quant.luck_test.types import TripInput
from app.quant.regime_split.errors import RegimeInputError, UnavailableReason
from app.quant.regime_split.trips import map_round_trips
from luck_helpers import series as luck_series
from regime_helpers import BUY, OWN, SELL, bias_params, led, session


def _names(fn) -> list[str]:
    return list(inspect.signature(fn).parameters)


def _fields(cls) -> list[str]:
    return [f.name for f in dataclasses.fields(cls)]


def _round_trips(trades):
    inputs = validate_inputs(trades, {OWN: luck_series(OWN, 0)}, bias_params())
    return fold_positions(inputs).round_trips


def test_relied_upon_signatures():
    assert _names(validate_inputs) == ["trades", "series", "parameters", "corporate_action_listings"]
    assert _names(fold_positions) == ["inputs"]
    assert _names(analyze_biases) == ["trades", "series", "parameters", "corporate_action_listings"]
    assert _names(analyze_luck) == ["trips", "series", "universe", "nifty50", "corporate_action_listings", "parameters",
                                    "corporate_action_reviewed"]
    assert _names(volatility) == ["view", "lookback"]
    assert _names(ListingBars.close_on) == ["self", "d"]


def test_relied_upon_fields():
    assert _fields(RoundTrip) == ["instrument", "open_session", "close_session", "holding_sessions", "gross_pnl", "trades"]
    assert {"trade_id", "instrument", "isin", "side", "quantity", "price"} <= set(_fields(LedgerTrade))
    assert _fields(TripInput) == ["trip_id", "instrument", "isin", "open_session", "close_session", "cost_inr", "proceeds_inr"]
    assert _fields(ListingBars) == ["instrument", "offset", "fingerprint", "dates", "closes"]
    assert _fields(PreTradeView) == ["_closes", "count"]
    assert {"trades", "missing_series", "exclusions"} <= set(_fields(ValidatedBiasInputs))


def test_every_round_trip_maps_to_exactly_one_identified_trip():
    trades = [led("A1", BUY, 10, 100, 20), led("A2", SELL, 10, 110, 22), led("B1", BUY, 5, 50, 30), led("B2", BUY, 5, 52, 31),
              led("B3", SELL, 10, 60, 33)]
    mapped = map_round_trips(_round_trips(trades))
    assert [m.trip.trip_id for m in mapped] == ["A1", "B1"]
    first, second = mapped
    assert (first.trip.cost_inr, first.trip.proceeds_inr) == (D("1000"), D("1100"))
    assert (second.trip.cost_inr, second.trip.proceeds_inr) == (D("510"), D("600"))
    assert first.trip.open_session == session(20) and first.trip.close_session == session(22)
    assert second.trip.instrument == OWN and first.unavailable is None


def test_same_day_reentries_get_distinct_identities():
    trades = [led("A1", BUY, 10, 100, 20, hour=4), led("A2", SELL, 10, 105, 20, hour=5),
              led("A3", BUY, 4, 90, 20, hour=6), led("A4", SELL, 4, 95, 20, hour=7)]
    mapped = map_round_trips(_round_trips(trades))
    assert [m.trip.trip_id for m in mapped] == ["A1", "A3"]
    assert {(m.trip.open_session, m.trip.close_session) for m in mapped} == {(session(20), session(20))}
    assert len({m.trip.trip_id for m in mapped}) == 2


def test_membership_is_a_partition_of_the_trades_in_round_trips():
    trades = [led("A1", BUY, 10, 100, 20), led("A2", SELL, 6, 110, 21), led("A3", SELL, 4, 90, 22),
              led("C1", BUY, 3, 80, 25)]  # C1 stays open: it belongs to no round trip
    trips = _round_trips(trades)
    ids = [t.trade_id for rt in trips for t in rt.trades]
    assert ids == ["A1", "A2", "A3"] and len(set(ids)) == len(ids)
    assert trips[0].trades[0].side is BUY and trips[0].trades[-1].side is SELL


def test_a_trip_has_the_same_gross_value_alone_or_with_the_full_ledger():
    one = [led("A1", BUY, 10, 100, 20), led("A2", SELL, 4, 120, 21), led("A3", SELL, 6, 90, 22)]
    two = [led("B1", BUY, 7, 40, 30), led("B2", SELL, 7, 50, 33)]
    alone = _round_trips(two)[0]
    together = [rt for rt in _round_trips(one + two) if rt.trades[0].trade_id == "B1"][0]
    assert alone == together and alone.gross_pnl == D("70")
    second_alone = _round_trips(one)[0]
    assert second_alone == [rt for rt in _round_trips(one + two) if rt.trades[0].trade_id == "A1"][0]


def test_cost_and_proceeds_are_exact_decimals():
    trades = [led("A1", BUY, "3.333333", "12.345678", 20), led("A2", SELL, "3.333333", "13.000001", 21)]
    trip = map_round_trips(_round_trips(trades))[0].trip
    assert trip.cost_inr == D("3.333333") * D("12.345678")
    assert trip.proceeds_inr == D("3.333333") * D("13.000001")
    assert isinstance(trip.cost_inr, D)


ISIN_A, ISIN_B = "INE000000001", "INE000000002"


@pytest.mark.parametrize("isins,expected,excluded", [
    ((None, None), None, False), ((ISIN_A, ISIN_A), ISIN_A, False),
    ((ISIN_A, None), None, True), ((None, ISIN_A), None, True), ((ISIN_A, ISIN_B), None, True),
])
def test_isin_is_never_guessed(isins, expected, excluded):
    trades = [led("A1", BUY, 10, 100, 20, isin=isins[0]), led("A2", SELL, 10, 110, 21, isin=isins[1])]
    m = map_round_trips(_round_trips(trades))[0]
    assert m.trip.isin == expected
    assert (m.unavailable is not None) is excluded
    if excluded:
        assert m.unavailable.reason is UnavailableReason.AMBIGUOUS_ISIN


def _rt(trades, instrument=OWN) -> RoundTrip:
    return RoundTrip(instrument, session(20), session(22), 2, D(0), tuple(trades))


def test_broken_structures_raise():
    buy, sell = led("A1", BUY, 10, 100, 20), led("A2", SELL, 10, 110, 22)
    with pytest.raises(RegimeInputError):
        map_round_trips([_rt([sell, buy])])  # opens with a SELL
    with pytest.raises(RegimeInputError):
        map_round_trips([_rt([buy, led("A3", BUY, 1, 100, 21)])])  # ends with a BUY
    with pytest.raises(RegimeInputError):
        map_round_trips([_rt([])])
    with pytest.raises(RegimeInputError):
        map_round_trips([_rt([buy, led("A2", SELL, 9, 110, 22)])])  # sells less than bought
    other = led("A2", SELL, 10, 110, 22, instrument=type(OWN)("OTHERTEST", OWN.exchange))
    with pytest.raises(RegimeInputError):
        map_round_trips([_rt([buy, other])])  # two listings in one trip


def test_duplicate_identity_and_shared_trades_raise():
    buy, sell = led("A1", BUY, 10, 100, 20), led("A2", SELL, 10, 110, 22)
    with pytest.raises(RegimeInputError, match="duplicate trip identity"):
        map_round_trips([_rt([buy, sell]), _rt([buy, led("A9", SELL, 10, 1, 23)])])
    with pytest.raises(RegimeInputError, match="more than one round trip"):
        map_round_trips([_rt([buy, sell]), _rt([led("Z1", BUY, 10, 100, 24), sell])])


def test_a_trip_feature_007_rejects_is_an_input_error():
    tiny, price = D("0.0000000001"), D("0.0000000000001")  # each within the ledger limits, the product exponent is -23
    trades = [led("A1", BUY, tiny, price, 20), led("A2", SELL, tiny, price, 21)]
    with pytest.raises(RegimeInputError, match="not a valid Feature 007 trip"):
        map_round_trips(_round_trips(trades))


def test_empty_input_maps_to_nothing():
    assert map_round_trips([]) == ()
    assert date(2025, 10, 1) == session(0)
