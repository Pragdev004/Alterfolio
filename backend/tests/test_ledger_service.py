from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from uuid import uuid4

import pytest

from app.domain.enums import (
    AssetType, Exchange, MarketSession, TradeSide, TradeSource, TradeStatus,
)
from app.repositories.trade_repository import TradeRepository
from app.services.errors import (
    AlreadySupersededError, InvalidTradeError, OversellError, TradeNotFoundError,
)
from app.services.ledger import LedgerService, TradeInput
from tests.conftest import T0, USER_A, USER_B, trade_fields


def ti(**kw):
    base = dict(
        symbol="RELIANCE", name="Reliance Industries", asset_type=AssetType.STOCK,
        exchange=Exchange.NSE, side=TradeSide.BUY, quantity=D("10"),
        price_per_unit=D("100"), trade_timestamp=T0, market_session=MarketSession.REGULAR,
    )
    base.update(kw)
    return TradeInput(**base)


@pytest.fixture
def svc(session, clock, id_factory):
    return LedgerService(TradeRepository(session), clock=clock, id_factory=id_factory)


def hold(svc, user=USER_A, **kw):
    return {(h.instrument.symbol, h.instrument.exchange): h for h in svc.holdings(user_id=user, **kw)}


def at(hours):
    return T0 + timedelta(hours=hours)


# ---- record -------------------------------------------------------------

def test_record_sets_server_fields(svc, clock):
    t = svc.record(user_id=USER_A, data=ti())
    assert t.user_id == USER_A
    assert t.source is TradeSource.MANUAL
    assert t.status is TradeStatus.EXECUTED
    assert t.supersedes_trade_id is None
    assert t.currency.value == "INR"
    assert t.brokerage_fee == D(0) and t.taxes == D(0)
    assert t.recorded_at == T0 + timedelta(days=1)  # first clock tick


def test_list_and_get_are_user_scoped(svc):
    a = svc.record(user_id=USER_A, data=ti())
    svc.record(user_id=USER_B, data=ti())
    assert [t.id for t in svc.list_trades(user_id=USER_A)] == [a.id]
    assert svc.get_trade(user_id=USER_A, trade_id=a.id).id == a.id
    with pytest.raises(TradeNotFoundError):
        svc.get_trade(user_id=USER_B, trade_id=a.id)
    with pytest.raises(TradeNotFoundError):
        svc.get_trade(user_id=USER_A, trade_id=uuid4())


@pytest.mark.parametrize(
    "bad",
    [
        {"quantity": D("0")}, {"quantity": D("-1")}, {"price_per_unit": D("0")},
        {"brokerage_fee": D("-1")}, {"taxes": D("-0.5")},
        {"quantity": D("1.1234567")}, {"price_per_unit": D("0.0000001")},
        {"quantity": D("NaN")}, {"price_per_unit": D("Infinity")},
        {"quantity": D("123456789012345")},
        {"trade_timestamp": datetime(2026, 1, 1, 10, 0)},
        {"symbol": ""}, {"symbol": "  "}, {"name": ""},
        {"quantity": 5}, {"price_per_unit": 1.5}, {"side": "BUY"},
    ],
)
def test_invalid_input_is_rejected_without_repair(bad):
    with pytest.raises(InvalidTradeError):
        ti(**bad)


def test_offset_timestamps_are_normalised_to_utc():
    ist = timezone(timedelta(hours=5, minutes=30))
    data = ti(trade_timestamp=datetime(2026, 1, 1, 15, 30, tzinfo=ist))
    assert data.trade_timestamp == T0 and data.trade_timestamp.utcoffset() == timedelta(0)


def test_symbol_is_kept_verbatim():
    assert ti(symbol="m&m").symbol == "m&m"


# ---- oversell -------------------------------------------------------------

def test_sell_without_holdings_is_rejected_and_writes_nothing(svc):
    with pytest.raises(OversellError):
        svc.record(user_id=USER_A, data=ti(side=TradeSide.SELL))
    assert svc.list_trades(user_id=USER_A) == []


def test_sell_above_held_is_rejected(svc):
    svc.record(user_id=USER_A, data=ti(quantity=D("5")))
    with pytest.raises(OversellError):
        svc.record(user_id=USER_A, data=ti(side=TradeSide.SELL, quantity=D("6"), trade_timestamp=at(1)))
    assert len(svc.list_trades(user_id=USER_A)) == 1


def test_back_dated_sell_before_the_buy_is_rejected(svc):
    svc.record(user_id=USER_A, data=ti(trade_timestamp=at(2)))
    with pytest.raises(OversellError):
        svc.record(user_id=USER_A, data=ti(side=TradeSide.SELL, quantity=D("1"), trade_timestamp=at(0)))


def test_back_dated_sell_that_starves_a_later_sell_is_rejected(svc):
    svc.record(user_id=USER_A, data=ti(trade_timestamp=at(0)))
    svc.record(user_id=USER_A, data=ti(side=TradeSide.SELL, quantity=D("10"), trade_timestamp=at(2)))
    with pytest.raises(OversellError):
        svc.record(user_id=USER_A, data=ti(side=TradeSide.SELL, quantity=D("5"), trade_timestamp=at(1)))


def test_back_dated_buy_is_allowed(svc):
    svc.record(user_id=USER_A, data=ti(trade_timestamp=at(2)))
    svc.record(user_id=USER_A, data=ti(trade_timestamp=at(0)))
    assert hold(svc)[("RELIANCE", Exchange.NSE)].quantity == D(20)


def test_other_users_trades_never_cover_a_sell(svc):
    svc.record(user_id=USER_B, data=ti())
    with pytest.raises(OversellError):
        svc.record(user_id=USER_A, data=ti(side=TradeSide.SELL, quantity=D("1")))


# ---- correct --------------------------------------------------------------

def test_correct_adds_a_superseding_row_and_leaves_the_original_untouched(svc, session):
    original = svc.record(user_id=USER_A, data=ti())
    before = {c.name: getattr(original, c.name) for c in original.__table__.columns}
    fixed = svc.correct(user_id=USER_A, trade_id=original.id, data=ti(quantity=D("8"), price_per_unit=D("101")))
    assert fixed.id != original.id and fixed.supersedes_trade_id == original.id
    assert fixed.source is TradeSource.MANUAL and fixed.recorded_at > original.recorded_at
    session.expire_all()
    after = {c.name: getattr(original, c.name) for c in original.__table__.columns}
    assert after == before
    (h,) = svc.holdings(user_id=USER_A)
    assert (h.quantity, h.invested_amount) == (D(8), D(808))
    assert len(svc.list_trades(user_id=USER_A)) == 2


def test_correct_may_change_instrument_and_side(svc):
    original = svc.record(user_id=USER_A, data=ti())
    svc.correct(user_id=USER_A, trade_id=original.id, data=ti(symbol="TCS", exchange=Exchange.BSE))
    assert list(hold(svc)) == [("TCS", Exchange.BSE)]


def test_correct_chain_requires_the_latest_row(svc):
    first = svc.record(user_id=USER_A, data=ti())
    second = svc.correct(user_id=USER_A, trade_id=first.id, data=ti(quantity=D("9")))
    with pytest.raises(AlreadySupersededError):
        svc.correct(user_id=USER_A, trade_id=first.id, data=ti(quantity=D("7")))
    third = svc.correct(user_id=USER_A, trade_id=second.id, data=ti(quantity=D("7")))
    assert third.supersedes_trade_id == second.id
    assert hold(svc)[("RELIANCE", Exchange.NSE)].quantity == D(7)


def test_correct_unknown_or_foreign_trade_is_not_found(svc):
    a = svc.record(user_id=USER_A, data=ti())
    with pytest.raises(TradeNotFoundError):
        svc.correct(user_id=USER_B, trade_id=a.id, data=ti())
    with pytest.raises(TradeNotFoundError):
        svc.correct(user_id=USER_A, trade_id=uuid4(), data=ti())
    assert len(svc.list_trades(user_id=USER_B)) == 0


def test_correction_that_causes_a_later_oversell_is_rejected(svc):
    buy = svc.record(user_id=USER_A, data=ti(trade_timestamp=at(0)))
    svc.record(user_id=USER_A, data=ti(side=TradeSide.SELL, trade_timestamp=at(1)))
    with pytest.raises(OversellError):
        svc.correct(user_id=USER_A, trade_id=buy.id, data=ti(quantity=D("5"), trade_timestamp=at(0)))
    assert len(svc.list_trades(user_id=USER_A)) == 2
    assert svc.holdings(user_id=USER_A) == []


def test_moving_a_buy_to_another_instrument_checks_the_old_instrument(svc):
    buy = svc.record(user_id=USER_A, data=ti(trade_timestamp=at(0)))
    svc.record(user_id=USER_A, data=ti(side=TradeSide.SELL, trade_timestamp=at(1)))
    with pytest.raises(OversellError):
        svc.correct(user_id=USER_A, trade_id=buy.id, data=ti(symbol="TCS", trade_timestamp=at(0)))


def test_correcting_an_imported_row_yields_a_manual_row(svc, session):
    imported = TradeRepository(session).add(
        user_id=USER_A, id=uuid4(),
        **trade_fields(source=TradeSource.IMPORT, broker="zerodha", broker_trade_id="T1"),
    )
    fixed = svc.correct(user_id=USER_A, trade_id=imported.id, data=ti(quantity=D("4")))
    assert imported.source is TradeSource.IMPORT and fixed.source is TradeSource.MANUAL


# ---- void -----------------------------------------------------------------

def test_void_adds_a_cancelled_superseding_copy(svc):
    original = svc.record(user_id=USER_A, data=ti(brokerage_fee=D("1.5"), notes="hi"))
    void = svc.void(user_id=USER_A, trade_id=original.id)
    assert void.status is TradeStatus.CANCELLED and void.supersedes_trade_id == original.id
    assert (void.symbol, void.quantity, void.brokerage_fee, void.notes) == ("RELIANCE", D(10), D("1.5"), "hi")
    assert svc.holdings(user_id=USER_A) == []
    assert original.status is TradeStatus.EXECUTED


def test_void_twice_is_rejected(svc):
    original = svc.record(user_id=USER_A, data=ti())
    svc.void(user_id=USER_A, trade_id=original.id)
    with pytest.raises(AlreadySupersededError):
        svc.void(user_id=USER_A, trade_id=original.id)


def test_void_of_a_buy_that_later_sells_depend_on_is_rejected(svc):
    buy = svc.record(user_id=USER_A, data=ti(trade_timestamp=at(0)))
    svc.record(user_id=USER_A, data=ti(side=TradeSide.SELL, quantity=D("3"), trade_timestamp=at(1)))
    with pytest.raises(OversellError):
        svc.void(user_id=USER_A, trade_id=buy.id)
    assert len(svc.list_trades(user_id=USER_A)) == 2


def test_void_of_a_foreign_trade_is_not_found(svc):
    a = svc.record(user_id=USER_A, data=ti())
    with pytest.raises(TradeNotFoundError):
        svc.void(user_id=USER_B, trade_id=a.id)


def test_a_voided_trade_can_be_restored_by_correcting_the_void_row(svc):
    original = svc.record(user_id=USER_A, data=ti())
    void = svc.void(user_id=USER_A, trade_id=original.id)
    svc.correct(user_id=USER_A, trade_id=void.id, data=ti())
    assert hold(svc)[("RELIANCE", Exchange.NSE)].quantity == D(10)


# ---- holdings -------------------------------------------------------------

def test_holdings_are_point_in_time_and_user_scoped(svc):
    svc.record(user_id=USER_A, data=ti(trade_timestamp=at(0)))
    snapshot = hold(svc, as_of=at(0))[("RELIANCE", Exchange.NSE)]
    svc.record(user_id=USER_A, data=ti(trade_timestamp=at(5), price_per_unit=D("200")))
    svc.record(user_id=USER_B, data=ti(trade_timestamp=at(0), symbol="TCS"))
    assert hold(svc, as_of=at(0))[("RELIANCE", Exchange.NSE)] == snapshot
    assert hold(svc)[("RELIANCE", Exchange.NSE)].quantity == D(20)
    assert ("TCS", Exchange.NSE) not in hold(svc)
    assert svc.holdings(user_id=uuid4()) == []


def test_holdings_as_of_must_be_aware(svc):
    with pytest.raises(InvalidTradeError):
        svc.holdings(user_id=USER_A, as_of=datetime(2026, 1, 1))


# ---- fees and taxes flow into holdings ------------------------------------

def test_buy_fees_and_taxes_enter_the_holding_cost(svc):
    svc.record(user_id=USER_A, data=ti(brokerage_fee=D("10"), taxes=D("5")))
    (h,) = svc.holdings(user_id=USER_A)
    assert (h.invested_amount, h.average_buy_price) == (D("1015"), D("101.5"))


def test_sell_fees_do_not_change_the_remaining_average_via_the_service(svc):
    svc.record(user_id=USER_A, data=ti(brokerage_fee=D("10")))
    svc.record(
        user_id=USER_A,
        data=ti(side=TradeSide.SELL, quantity=D("4"), price_per_unit=D("150"),
                brokerage_fee=D("50"), taxes=D("20"), trade_timestamp=at(1)),
    )
    (h,) = svc.holdings(user_id=USER_A)
    assert (h.quantity, h.average_buy_price) == (D(6), D(101))


def test_a_correction_that_changes_fees_changes_the_cost(svc):
    t = svc.record(user_id=USER_A, data=ti(brokerage_fee=D("10")))
    svc.correct(user_id=USER_A, trade_id=t.id, data=ti(brokerage_fee=D("20")))
    (h,) = svc.holdings(user_id=USER_A)
    assert h.invested_amount == D(1020)


# ---- defect 4: bounded text fields are validated, never truncated or left to the database ----

from app.domain import limits  # noqa: E402

TEXT_LIMITS = {
    "symbol": limits.MAX_SYMBOL_LENGTH,
    "name": limits.MAX_NAME_LENGTH,
    "broker": limits.MAX_BROKER_LENGTH,
    "broker_trade_id": limits.MAX_BROKER_TRADE_ID_LENGTH,
    "order_id": limits.MAX_ORDER_ID_LENGTH,
    "notes": limits.MAX_NOTES_LENGTH,
}


def test_limits_match_the_documented_column_sizes():
    assert TEXT_LIMITS == {
        "symbol": 64, "name": 256, "broker": 64, "broker_trade_id": 128, "order_id": 128, "notes": 2000,
    }


@pytest.mark.parametrize("field,limit", sorted(TEXT_LIMITS.items()))
def test_text_at_the_limit_is_accepted_and_one_over_is_rejected(field, limit):
    assert getattr(ti(**{field: "x" * limit}), field) == "x" * limit
    with pytest.raises(InvalidTradeError, match=field):
        ti(**{field: "x" * (limit + 1)})


def test_oversized_text_is_rejected_not_truncated(svc):
    with pytest.raises(InvalidTradeError):
        svc.record(user_id=USER_A, data=ti(symbol="S" * 65))
    assert svc.list_trades(user_id=USER_A) == []


def test_limits_count_characters_not_bytes():
    assert ti(name="₹" * limits.MAX_NAME_LENGTH).name == "₹" * limits.MAX_NAME_LENGTH


def test_non_string_text_is_rejected():
    with pytest.raises(InvalidTradeError):
        ti(notes=5)
    with pytest.raises(InvalidTradeError):
        ti(broker=b"zerodha")


# ---- defect 3: accepted values cannot overflow the exact Decimal / database / holdings range ----

from app.domain.numeric import MAX_AMOUNT  # noqa: E402,F811
from app.services.errors import NumericLimitError  # noqa: E402

BIG = D("99999999999999")  # largest value one NUMERIC(20,6) field accepts


def test_the_probe_that_poisoned_holdings_is_now_rejected(svc):
    with pytest.raises(NumericLimitError):
        svc.record(user_id=USER_A, data=ti(quantity=BIG, price_per_unit=BIG))
    assert svc.list_trades(user_id=USER_A) == [] and svc.holdings(user_id=USER_A) == []


def test_trade_notional_is_bounded_including_fees_and_taxes():
    ti(quantity=D("10"), price_per_unit=D("90000000000000"))  # 9e14 on its own is fine
    with pytest.raises(NumericLimitError):
        ti(quantity=D("10"), price_per_unit=D("90000000000000"), brokerage_fee=BIG, taxes=BIG)  # 1.09e15


def test_notional_just_under_the_ceiling_is_accepted_unchanged():
    data = ti(quantity=D("1"), price_per_unit=BIG, brokerage_fee=D("0.000001"))
    assert data.quantity == D(1) and data.price_per_unit == BIG
    assert ti(quantity=D("99999999999999"), price_per_unit=D("0.000001")).price_per_unit == D("0.000001")


def test_notional_is_checked_exactly_not_in_the_rounding_context():
    # 14+6 digit quantity x 14+6 digit price needs 40 digits; the check must not overflow or round.
    with pytest.raises(NumericLimitError):
        ti(quantity=D("99999999999999.999999"), price_per_unit=D("99999999999999.999999"))


def test_cumulative_cost_cannot_reach_the_ceiling(svc):
    svc.record(user_id=USER_A, data=ti(quantity=D("6"), price_per_unit=BIG, trade_timestamp=at(0)))
    with pytest.raises(NumericLimitError):
        svc.record(user_id=USER_A, data=ti(quantity=D("6"), price_per_unit=BIG, trade_timestamp=at(1)))
    assert len(svc.list_trades(user_id=USER_A)) == 1
    (h,) = svc.holdings(user_id=USER_A)
    assert h.invested_amount == D(6) * BIG


def test_cumulative_sale_proceeds_cannot_reach_the_ceiling(svc):
    svc.record(user_id=USER_A, data=ti(quantity=D("12"), price_per_unit=D("1"), trade_timestamp=at(0)))
    svc.record(user_id=USER_A, data=ti(side=TradeSide.SELL, quantity=D("6"), price_per_unit=BIG, trade_timestamp=at(1)))
    with pytest.raises(NumericLimitError):
        svc.record(user_id=USER_A, data=ti(side=TradeSide.SELL, quantity=D("6"), price_per_unit=BIG, trade_timestamp=at(2)))
    assert len(svc.list_trades(user_id=USER_A)) == 2


def test_a_correction_cannot_breach_the_ceiling_either(svc):
    t = svc.record(user_id=USER_A, data=ti())
    with pytest.raises(NumericLimitError):
        svc.correct(user_id=USER_A, trade_id=t.id, data=ti(quantity=BIG, price_per_unit=BIG))
    assert len(svc.list_trades(user_id=USER_A)) == 1


# ---- defect 2: duplicate broker trade ids on manual creation ----

from sqlalchemy.exc import IntegrityError  # noqa: E402

from app.services.errors import DuplicateTradeError  # noqa: E402


def dup(**kw):
    return ti(broker="zerodha", broker_trade_id="T1", **kw)


def test_a_duplicate_broker_trade_id_is_refused_cleanly_and_writes_nothing(svc):
    first = svc.record(user_id=USER_A, data=dup())
    with pytest.raises(DuplicateTradeError) as err:
        svc.record(user_id=USER_A, data=dup(trade_timestamp=at(1)))
    assert err.value.code == "duplicate_trade" and err.value.existing_trade_id == first.id
    assert [t.id for t in svc.list_trades(user_id=USER_A)] == [first.id]


def test_duplicate_detection_mirrors_the_database_index(svc):
    svc.record(user_id=USER_A, data=dup())
    svc.record(user_id=USER_B, data=dup())                                    # other user
    svc.record(user_id=USER_A, data=ti(broker="other", broker_trade_id="T1")) # other broker
    svc.record(user_id=USER_A, data=ti(broker="zerodha", broker_trade_id="T2"))  # other id
    svc.record(user_id=USER_A, data=ti(broker="zerodha"))                     # no broker_trade_id
    svc.record(user_id=USER_A, data=ti(broker="zerodha"))
    svc.record(user_id=USER_A, data=ti(broker_trade_id="T1"))                 # no broker: NULLs never collide
    svc.record(user_id=USER_A, data=ti(broker_trade_id="T1"))
    assert len(svc.list_trades(user_id=USER_A)) == 7


def test_a_correction_may_keep_the_same_broker_trade_id(svc):
    first = svc.record(user_id=USER_A, data=dup())
    fixed = svc.correct(user_id=USER_A, trade_id=first.id, data=dup(quantity=D("4")))
    assert fixed.broker_trade_id == "T1" and fixed.supersedes_trade_id == first.id


def test_the_database_constraint_is_the_race_safe_backstop(svc, monkeypatch):
    first = svc.record(user_id=USER_A, data=dup())
    real = TradeRepository.original_by_broker_trade_id
    calls = []

    def racing(self, **kw):  # first call (the pre-check) misses as if the other request had not committed yet
        calls.append(kw)
        return None if len(calls) == 1 else real(self, **kw)

    monkeypatch.setattr(TradeRepository, "original_by_broker_trade_id", racing)
    with pytest.raises(DuplicateTradeError):
        svc.record(user_id=USER_A, data=dup(trade_timestamp=at(1)))
    assert len(calls) == 2  # pre-check missed, the unique index fired, the follow-up lookup found the winner
    monkeypatch.undo()
    svc.record(user_id=USER_A, data=ti(trade_timestamp=at(2)))  # session still healthy afterwards
    assert len(svc.list_trades(user_id=USER_A)) == 2 and first.id in {t.id for t in svc.list_trades(user_id=USER_A)}


def test_other_integrity_errors_are_not_disguised_as_duplicates(svc, monkeypatch):
    def boom(self, **kw):
        raise IntegrityError("stmt", {}, Exception("some other constraint"))

    monkeypatch.setattr(TradeRepository, "add", boom)
    with pytest.raises(IntegrityError):
        svc.record(user_id=USER_A, data=ti())


# ---- review round 3: empty-string broker, extreme Decimal exponents, NUL characters ----

def test_an_empty_string_broker_is_a_real_value_for_the_unique_index(svc):
    first = svc.record(user_id=USER_A, data=ti(broker="", broker_trade_id="T1"))
    with pytest.raises(DuplicateTradeError) as err:
        svc.record(user_id=USER_A, data=ti(broker="", broker_trade_id="T1", trade_timestamp=at(1)))
    assert err.value.existing_trade_id == first.id
    assert [t.id for t in svc.list_trades(user_id=USER_A)] == [first.id]


def test_empty_string_broker_is_distinct_from_no_broker_and_from_other_ids(svc):
    svc.record(user_id=USER_A, data=ti(broker="", broker_trade_id="T1"))
    svc.record(user_id=USER_A, data=ti(broker=None, broker_trade_id="T1"))   # NULL broker never collides
    svc.record(user_id=USER_A, data=ti(broker="", broker_trade_id="T2"))
    svc.record(user_id=USER_A, data=ti(broker="zerodha", broker_trade_id="T1"))
    assert len(svc.list_trades(user_id=USER_A)) == 4


@pytest.mark.parametrize("field", ["quantity", "price_per_unit", "brokerage_fee", "taxes"])
@pytest.mark.parametrize("bad", ["0E+1000000", "0E+14", "0E-21", "1.000000000000000000000", "5E+14", "5." + "0" * 20000])
def test_decimals_outside_the_supported_exponent_range_are_rejected_even_when_zero(field, bad):
    with pytest.raises(InvalidTradeError, match=field):
        ti(**{field: D(bad)})


@pytest.mark.parametrize("ok", ["0", "0E+13", "0E-20", "1.0000000", "0.000001", "99999999999999"])
def test_exponents_inside_the_range_keep_their_existing_semantics(ok):
    data = ti(quantity=D("1"), price_per_unit=D("1"), brokerage_fee=D(ok), taxes=D(ok))
    assert data.brokerage_fee == D(ok) and str(data.brokerage_fee) == str(D(ok))  # stored as given, not normalized


@pytest.mark.parametrize("field", sorted(TEXT_LIMITS))
def test_nul_characters_are_rejected_in_every_bounded_text_field(field):
    for bad in ("a\x00b", "\x00", "x" * 3 + "\x00"):
        with pytest.raises(InvalidTradeError, match=field):
            ti(**{field: bad})


def test_a_nul_character_writes_nothing(svc):
    with pytest.raises(InvalidTradeError):
        svc.record(user_id=USER_A, data=ti(notes="line\x00two"))
    assert svc.list_trades(user_id=USER_A) == []


# ---- final review M1: timestamps whose UTC instant is outside year 1..9999 are a client error, not an OverflowError ----

from datetime import datetime as _dt, timedelta as _td, timezone as _tz  # noqa: E402

_IST = _tz(_td(hours=5, minutes=30))
_EST = _tz(_td(hours=-5))


@pytest.mark.parametrize(
    "ts",
    [_dt(1, 1, 1, 0, 0, tzinfo=_IST), _dt(9999, 12, 31, 23, 59, 59, tzinfo=_EST)],
    ids=["utc-before-year-1", "utc-after-year-9999"],
)
def test_timestamps_that_overflow_utc_are_rejected_as_invalid_input(ts):
    with pytest.raises(InvalidTradeError, match="trade_timestamp"):
        ti(trade_timestamp=ts)


def test_the_supported_timestamp_window_keeps_a_day_of_margin_from_the_calendar_edges(svc):
    assert limits.MIN_TRADE_TIMESTAMP == _dt(1, 1, 2, tzinfo=_tz.utc)
    assert limits.MAX_TRADE_TIMESTAMP == _dt(9999, 12, 30, 23, 59, 59, 999999, tzinfo=_tz.utc)
    first, last = limits.MIN_TRADE_TIMESTAMP, limits.MAX_TRADE_TIMESTAMP
    assert ti(trade_timestamp=first).trade_timestamp == first
    assert ti(trade_timestamp=last).trade_timestamp == last
    svc.record(user_id=USER_A, data=ti(trade_timestamp=first))
    svc.record(user_id=USER_A, data=ti(trade_timestamp=last, symbol="TCS"))
    assert [t.trade_timestamp for t in svc.list_trades(user_id=USER_A)] == [first, last]


@pytest.mark.parametrize(
    "ts",
    [
        limits.MIN_TRADE_TIMESTAMP - _td(microseconds=1),
        limits.MAX_TRADE_TIMESTAMP + _td(microseconds=1),
        _dt(1, 1, 1, 0, 0, tzinfo=_tz.utc),
        _dt(9999, 12, 31, 23, 59, 59, tzinfo=_tz.utc),
        _dt(1, 1, 2, 5, 29, tzinfo=_IST),  # UTC instant 0001-01-01T23:59 is just outside the window
    ],
    ids=["just-below-min", "just-above-max", "calendar-first-instant", "calendar-last-second", "offset-into-margin"],
)
def test_timestamps_outside_the_supported_window_are_rejected(ts):
    with pytest.raises(InvalidTradeError, match="trade_timestamp"):
        ti(trade_timestamp=ts)
