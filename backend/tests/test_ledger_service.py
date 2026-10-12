import re
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
from app.services.ledger import CorrectionInput, LedgerService, TradeInput
from tests.conftest import T0, USER_A, USER_B, make_batch, trade_fields


def isin_of(symbol):
    """A synthetic 12-character ISIN per symbol, so different symbols are different holdings."""
    return ("ZZ0" + re.sub("[^A-Z0-9]", "", symbol.upper()) + "0" * 12)[:12]


def ti(**kw):
    base = dict(
        symbol="RELIANCE", name="Reliance Industries", asset_type=AssetType.STOCK,
        exchange=Exchange.NSE, side=TradeSide.BUY, quantity=D("10"),
        price_per_unit=D("100"), trade_timestamp=T0, market_session=MarketSession.REGULAR,
    )
    base.update(kw)
    base.setdefault("isin", isin_of(base["symbol"]))
    return TradeInput(**base)


def ci(**kw):
    """A correction body that keeps the known descriptive fields of a manual trade."""
    base = dict(
        symbol="RELIANCE", name="Reliance Industries", asset_type=AssetType.STOCK,
        exchange=Exchange.NSE, side=TradeSide.BUY, quantity=D("10"),
        price_per_unit=D("100"), trade_timestamp=T0, market_session=MarketSession.REGULAR,
    )
    base.update(kw)
    base.setdefault("isin", isin_of(base["symbol"]))
    return CorrectionInput(**base)


def legacy(session, user=USER_A, **kw):
    """A pre-Feature-002 row: manual, NULL ISIN. The service can no longer create these, so tests write them directly."""
    return TradeRepository(session).add(user_id=user, id=uuid4(), **trade_fields(isin=None, **kw))


@pytest.fixture
def svc(session, clock, id_factory):
    return LedgerService(TradeRepository(session), clock=clock, id_factory=id_factory)


def hold(svc, user=USER_A, **kw):
    """Holdings indexed by each of their listings, so a single-listing holding is found by (symbol, exchange)."""
    return {(i.symbol, i.exchange): h for h in svc.holdings(user_id=user, **kw) for i in h.listings}


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
    fixed = svc.correct(user_id=USER_A, trade_id=original.id, data=ci(quantity=D("8"), price_per_unit=D("101")))
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
    svc.correct(user_id=USER_A, trade_id=original.id, data=ci(symbol="TCS", exchange=Exchange.BSE))
    assert list(hold(svc)) == [("TCS", Exchange.BSE)]


def test_correct_chain_requires_the_latest_row(svc):
    first = svc.record(user_id=USER_A, data=ti())
    second = svc.correct(user_id=USER_A, trade_id=first.id, data=ci(quantity=D("9")))
    with pytest.raises(AlreadySupersededError):
        svc.correct(user_id=USER_A, trade_id=first.id, data=ci(quantity=D("7")))
    third = svc.correct(user_id=USER_A, trade_id=second.id, data=ci(quantity=D("7")))
    assert third.supersedes_trade_id == second.id
    assert hold(svc)[("RELIANCE", Exchange.NSE)].quantity == D(7)


def test_correct_unknown_or_foreign_trade_is_not_found(svc):
    a = svc.record(user_id=USER_A, data=ti())
    with pytest.raises(TradeNotFoundError):
        svc.correct(user_id=USER_B, trade_id=a.id, data=ci())
    with pytest.raises(TradeNotFoundError):
        svc.correct(user_id=USER_A, trade_id=uuid4(), data=ci())
    assert len(svc.list_trades(user_id=USER_B)) == 0


def test_correction_that_causes_a_later_oversell_is_rejected(svc):
    buy = svc.record(user_id=USER_A, data=ti(trade_timestamp=at(0)))
    svc.record(user_id=USER_A, data=ti(side=TradeSide.SELL, trade_timestamp=at(1)))
    with pytest.raises(OversellError):
        svc.correct(user_id=USER_A, trade_id=buy.id, data=ci(quantity=D("5"), trade_timestamp=at(0)))
    assert len(svc.list_trades(user_id=USER_A)) == 2
    assert svc.holdings(user_id=USER_A) == []


def test_moving_a_buy_to_another_instrument_checks_the_old_instrument(svc):
    buy = svc.record(user_id=USER_A, data=ti(trade_timestamp=at(0)))
    svc.record(user_id=USER_A, data=ti(side=TradeSide.SELL, trade_timestamp=at(1)))
    with pytest.raises(OversellError):
        svc.correct(user_id=USER_A, trade_id=buy.id, data=ci(symbol="TCS", trade_timestamp=at(0)))


def test_correcting_an_imported_row_yields_a_manual_row(svc, session):
    batch = make_batch(session)
    imported = TradeRepository(session).add(
        user_id=USER_A, id=uuid4(),
        **trade_fields(
            source=TradeSource.IMPORT, broker="zerodha", broker_trade_id="T1", import_batch_id=batch.id,
            charges_provided=False,
        ),
    )
    fixed = svc.correct(user_id=USER_A, trade_id=imported.id, data=ci(quantity=D("4"), brokerage_fee=D("0"), taxes=D("0")))
    assert imported.source is TradeSource.IMPORT and fixed.source is TradeSource.MANUAL
    assert fixed.import_batch_id is None  # a correction of an imported row is MANUAL and carries no batch


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
    svc.correct(user_id=USER_A, trade_id=void.id, data=ci())
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
    svc.correct(user_id=USER_A, trade_id=t.id, data=ci(brokerage_fee=D("20")))
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
        svc.correct(user_id=USER_A, trade_id=t.id, data=ci(quantity=BIG, price_per_unit=BIG))
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
    fixed = svc.correct(user_id=USER_A, trade_id=first.id, data=ci(broker="zerodha", broker_trade_id="T1", quantity=D("4")))
    assert fixed.broker_trade_id == "T1" and fixed.supersedes_trade_id == first.id


def test_the_database_constraint_is_the_race_safe_backstop(svc, monkeypatch):
    first = svc.record(user_id=USER_A, data=dup())
    real = TradeRepository.original_by_key
    calls = []

    def racing(self, **kw):  # first call (the pre-check) misses as if the other request had not committed yet
        calls.append(kw)
        return None if len(calls) == 1 else real(self, **kw)

    monkeypatch.setattr(TradeRepository, "original_by_key", racing)
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


# ---- per-user write lock (plan 002a OPEN-11) -------------------------------------------------------------------

def _recording_lock(monkeypatch):
    calls = []
    real = TradeRepository.lock_user_ledger

    def spy(self, **kw):
        calls.append(kw["user_id"])
        return real(self, **kw)

    monkeypatch.setattr(TradeRepository, "lock_user_ledger", spy)
    return calls


def test_record_correct_and_void_each_take_the_user_lock_first(svc, monkeypatch):
    calls = _recording_lock(monkeypatch)
    first = svc.record(user_id=USER_A, data=ti())
    second = svc.correct(user_id=USER_A, trade_id=first.id, data=ci(quantity=D("11")))
    svc.void(user_id=USER_A, trade_id=second.id)
    assert calls == [USER_A, USER_A, USER_A]


def test_reads_do_not_take_the_lock(svc, monkeypatch):
    calls = _recording_lock(monkeypatch)
    trade = svc.record(user_id=USER_A, data=ti())
    calls.clear()
    svc.list_trades(user_id=USER_A)
    svc.get_trade(user_id=USER_A, trade_id=trade.id)
    svc.holdings(user_id=USER_A)
    assert calls == []


def test_a_held_lock_refuses_every_write_with_ledger_busy_and_writes_nothing(svc, session, monkeypatch):
    from sqlalchemy.exc import OperationalError

    from app.services.errors import LedgerBusyError

    trade = svc.record(user_id=USER_A, data=ti())

    class Orig(Exception):
        sqlstate = "55P03"

    def refuse(self, **kw):
        raise OperationalError("SELECT ... FOR UPDATE NOWAIT", {}, Orig("lock not available"))

    monkeypatch.setattr(TradeRepository, "lock_user_ledger", refuse)
    with pytest.raises(LedgerBusyError):
        svc.record(user_id=USER_A, data=ti())
    with pytest.raises(LedgerBusyError):
        svc.correct(user_id=USER_A, trade_id=trade.id, data=ci())
    with pytest.raises(LedgerBusyError):
        svc.void(user_id=USER_A, trade_id=trade.id)
    assert [t.id for t in svc.list_trades(user_id=USER_A)] == [trade.id]


def test_a_missing_user_row_is_a_setup_error(svc):
    with pytest.raises(RuntimeError, match="users row"):
        svc.record(user_id=uuid4(), data=ti())


def test_ledger_busy_has_a_stable_code():
    from app.services.errors import LedgerBusyError, LedgerError

    assert LedgerBusyError.code == "ledger_busy" and issubclass(LedgerBusyError, LedgerError)


# ---- ISIN on manual rows, corrections and voids (Feature 002) ----------------------------------------------------

ISIN = "ZZ0ALPHA0001"
OTHER_ISIN = "ZZ0BETACO001"


def imported_row(session, user=USER_A, **kw):
    """An imported ISIN row as the import service writes it (no name/type/session, charges unknown)."""
    batch = make_batch(session, user)
    fields = dict(
        symbol="RELIANCE", isin=ISIN, name=None, asset_type=None, market_session=None, source=TradeSource.IMPORT,
        broker="ZERODHA", broker_trade_id="T1", import_batch_id=batch.id, charges_provided=False,
    )
    fields.update(kw)
    return TradeRepository(session).add(user_id=user, id=uuid4(), **trade_fields(**fields))


def test_record_stores_a_valid_isin_and_affirms_charges(svc):
    t = svc.record(user_id=USER_A, data=ti(isin=ISIN))
    assert (t.isin, t.charges_provided, t.source, t.import_batch_id) == (ISIN, True, TradeSource.MANUAL, None)


def test_record_requires_an_isin(svc):
    with pytest.raises(InvalidTradeError, match="isin is required"):
        svc.record(user_id=USER_A, data=ti(isin=None))
    assert svc.list_trades(user_id=USER_A) == []


@pytest.mark.parametrize("bad", ["", "short", ISIN + "X", ISIN.lower(), "ZZ0ALPHA000É", "ZZ0ALPHA000 ", "١" * 12, 123456789012])
def test_a_malformed_isin_is_rejected_never_normalized(bad):
    with pytest.raises(InvalidTradeError, match="isin"):
        ti(isin=bad)


def test_correct_with_an_explicit_isin_uses_it(svc):
    original = svc.record(user_id=USER_A, data=ti(isin=ISIN))
    fixed = svc.correct(user_id=USER_A, trade_id=original.id, data=ci(isin=OTHER_ISIN))
    assert fixed.isin == OTHER_ISIN


def test_a_correction_always_carries_an_isin(svc):
    with pytest.raises(InvalidTradeError, match="isin is required"):
        ci(isin=None)


@pytest.mark.parametrize("bad", ["", "short", ISIN.lower(), ISIN + "X"])
def test_a_correction_validates_the_isin_format(bad):
    with pytest.raises(InvalidTradeError, match="isin"):
        ci(isin=bad)


def test_a_correction_can_move_a_legacy_row_onto_an_isin(svc, session):
    original = legacy(session)
    fixed = svc.correct(user_id=USER_A, trade_id=original.id, data=ci(isin=ISIN))
    assert fixed.isin == ISIN and fixed.charges_provided is True and original.isin is None


def test_correcting_an_imported_row_carries_the_isin_and_drops_the_batch(svc, session):
    imported = imported_row(session)
    fixed = svc.correct(user_id=USER_A, trade_id=imported.id, data=ci(isin=ISIN, name="Reliance", quantity=D("4"), brokerage_fee=D("0"), taxes=D("0")))
    assert (fixed.isin, fixed.source, fixed.import_batch_id, fixed.charges_provided) == (ISIN, TradeSource.MANUAL, None, True)
    assert imported.source is TradeSource.IMPORT and imported.import_batch_id is not None and imported.charges_provided is False


def test_void_copies_isin_and_charges_provided_of_an_imported_row(svc, session):
    imported = imported_row(session)
    void = svc.void(user_id=USER_A, trade_id=imported.id)
    assert void.status is TradeStatus.CANCELLED and void.supersedes_trade_id == imported.id
    assert (void.isin, void.charges_provided) == (ISIN, False)
    assert (void.source, void.import_batch_id) == (TradeSource.MANUAL, None)
    assert (void.name, void.asset_type, void.market_session) == (None, None, None)  # NULLs are copied, never invented


def test_void_of_a_manual_isin_row_keeps_its_isin_and_charges(svc):
    original = svc.record(user_id=USER_A, data=ti(isin=ISIN))
    void = svc.void(user_id=USER_A, trade_id=original.id)
    assert (void.isin, void.charges_provided) == (ISIN, True)


def test_a_correction_never_breaks_the_source_batch_invariant(svc, session):
    imported = imported_row(session)
    svc.correct(user_id=USER_A, trade_id=imported.id, data=ci(brokerage_fee=D("0"), taxes=D("0")))
    session.flush()  # the CHECK (source = IMPORT) = (import_batch_id IS NOT NULL) accepts the new MANUAL row


# ---- oversell is checked per ISIN, not per listing --------------------------------------------------------------

def test_voiding_an_nse_buy_that_covers_a_bse_sell_of_the_same_isin_is_refused(svc, session):
    buy = imported_row(session, broker_trade_id="B1", side=TradeSide.BUY, quantity=D("10"), trade_timestamp=at(0))
    imported_row(session, broker_trade_id="S1", exchange=Exchange.BSE, side=TradeSide.SELL, quantity=D("10"), trade_timestamp=at(1))
    with pytest.raises(OversellError):
        svc.void(user_id=USER_A, trade_id=buy.id)
    assert TradeRepository(session).superseder_of(user_id=USER_A, trade_id=buy.id) is None


def test_shrinking_an_nse_buy_below_a_bse_sell_of_the_same_isin_is_refused(svc, session):
    buy = imported_row(session, broker_trade_id="B1", side=TradeSide.BUY, quantity=D("10"), trade_timestamp=at(0))
    imported_row(session, broker_trade_id="S1", exchange=Exchange.BSE, side=TradeSide.SELL, quantity=D("10"), trade_timestamp=at(1))
    with pytest.raises(OversellError):
        svc.correct(user_id=USER_A, trade_id=buy.id, data=ci(quantity=D("9"), trade_timestamp=at(0), brokerage_fee=D("0"), taxes=D("0")))


def test_a_cross_exchange_sell_of_the_same_isin_is_allowed_manually(svc, session):
    imported_row(session, broker_trade_id="B1", side=TradeSide.BUY, quantity=D("10"), trade_timestamp=at(0))
    sell = svc.record(user_id=USER_A, data=ti(isin=ISIN, exchange=Exchange.BSE, side=TradeSide.SELL, trade_timestamp=at(1)))
    assert sell.exchange is Exchange.BSE


def test_a_manual_sell_of_another_isin_is_not_covered(svc, session):
    imported_row(session, broker_trade_id="B1", side=TradeSide.BUY, quantity=D("10"), trade_timestamp=at(0))
    with pytest.raises(OversellError):
        svc.record(user_id=USER_A, data=ti(isin=OTHER_ISIN, side=TradeSide.SELL, trade_timestamp=at(1)))


def test_legacy_and_isin_rows_never_offset_each_other(svc, session):
    legacy(session, quantity=D("10"), trade_timestamp=at(0))  # legacy buy, NULL ISIN
    with pytest.raises(OversellError):
        svc.record(user_id=USER_A, data=ti(isin=ISIN, side=TradeSide.SELL, trade_timestamp=at(1)))


def test_moving_a_legacy_row_onto_an_isin_rechecks_both_keys(svc, session):
    buy = legacy(session, quantity=D("10"), trade_timestamp=at(0))
    legacy(session, side=TradeSide.SELL, quantity=D("10"), trade_timestamp=at(1))  # a legacy sell, covered by that buy
    with pytest.raises(OversellError):  # the legacy key would lose its buy
        svc.correct(user_id=USER_A, trade_id=buy.id, data=ci(isin=ISIN, quantity=D("10"), trade_timestamp=at(0)))


def test_another_users_isin_rows_never_cover_a_sell(svc, session):
    imported_row(session, user=USER_B, broker_trade_id="B1", quantity=D("10"), trade_timestamp=at(0))
    with pytest.raises(OversellError):
        svc.record(user_id=USER_A, data=ti(isin=ISIN, side=TradeSide.SELL, trade_timestamp=at(1)))


# ---- correction rules against the target (plan 002a 3a) ----------------------------------------------------------

def test_a_correction_cannot_erase_a_known_descriptive_value(svc):
    original = svc.record(user_id=USER_A, data=ti())
    for field in ("name", "asset_type", "market_session"):
        with pytest.raises(InvalidTradeError, match=f"{field} cannot be erased"):
            svc.correct(user_id=USER_A, trade_id=original.id, data=ci(**{field: None}))
    assert len(svc.list_trades(user_id=USER_A)) == 1


def test_a_correction_may_leave_values_null_only_where_the_target_is_null(svc, session):
    imported = imported_row(session)  # name, asset_type, market_session are NULL
    fixed = svc.correct(
        user_id=USER_A, trade_id=imported.id,
        data=ci(name=None, asset_type=None, market_session=None, brokerage_fee=D("0"), taxes=D("0")),
    )
    assert (fixed.name, fixed.asset_type, fixed.market_session) == (None, None, None)


def test_a_correction_may_supply_a_value_where_the_target_has_none(svc, session):
    imported = imported_row(session)
    fixed = svc.correct(user_id=USER_A, trade_id=imported.id, data=ci(name="Reliance", brokerage_fee=D("1"), taxes=D("2")))
    assert fixed.name == "Reliance" and (fixed.brokerage_fee, fixed.taxes) == (D(1), D(2))


@pytest.mark.parametrize("given", [{}, {"brokerage_fee": D("0")}, {"taxes": D("0")}])
def test_correcting_unprovided_charges_needs_both_fees_stated(svc, session, given):
    imported = imported_row(session)
    with pytest.raises(InvalidTradeError, match="brokerage_fee and taxes must both be stated"):
        svc.correct(user_id=USER_A, trade_id=imported.id, data=ci(**given))
    assert [t.id for t in svc.list_trades(user_id=USER_A)] == [imported.id]


def test_an_explicit_zero_counts_as_stated_and_the_new_row_affirms_its_charges(svc, session):
    imported = imported_row(session)
    fixed = svc.correct(user_id=USER_A, trade_id=imported.id, data=ci(brokerage_fee=D("0"), taxes=D("0")))
    assert (fixed.brokerage_fee, fixed.taxes, fixed.charges_provided) == (D(0), D(0), True)


def test_omitted_fees_default_to_zero_when_the_target_charges_were_provided(svc):
    original = svc.record(user_id=USER_A, data=ti(brokerage_fee=D("3"), taxes=D("1")))
    fixed = svc.correct(user_id=USER_A, trade_id=original.id, data=ci())
    assert (fixed.brokerage_fee, fixed.taxes, fixed.charges_provided) == (D(0), D(0), True)


def test_a_correction_of_a_correction_stays_affirmed(svc, session):
    imported = imported_row(session)
    first = svc.correct(user_id=USER_A, trade_id=imported.id, data=ci(brokerage_fee=D("1"), taxes=D("1")))
    second = svc.correct(user_id=USER_A, trade_id=first.id, data=ci(quantity=D("3")))  # target charges are provided now
    assert second.charges_provided is True and second.brokerage_fee == D(0)


def test_correction_input_validates_like_a_new_trade():
    with pytest.raises(InvalidTradeError, match="quantity"):
        ci(quantity=D("0"))
    with pytest.raises(InvalidTradeError, match="fees and taxes must not be negative"):
        ci(brokerage_fee=D("-1"))
    with pytest.raises(InvalidTradeError, match="timezone-aware"):
        ci(trade_timestamp=datetime(2026, 1, 1))
    assert ci(trade_timestamp=datetime(2026, 1, 1, 5, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))).trade_timestamp == datetime(2026, 1, 1, tzinfo=timezone.utc)
