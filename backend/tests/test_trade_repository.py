from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.enums import Exchange, TradeSide, TradeStatus
from app.models.trade import Trade
from app.repositories.trade_repository import TradeRepository
from tests.conftest import T0, USER_A, USER_B, trade_fields


@pytest.fixture
def repo(session):
    return TradeRepository(session)


def add(repo, user=USER_A, **kw):
    return repo.add(user_id=user, id=kw.pop("id", uuid4()), **trade_fields(**kw))


def test_decimal_fields_round_trip_exactly(repo, session):
    t = add(repo, quantity=D("12345678901234.123456"), price_per_unit=D("0.000001"),
            brokerage_fee=D("0.5"), taxes=D("1.250000"))
    session.commit()
    session.expire_all()
    got = repo.get(user_id=USER_A, trade_id=t.id)
    assert got.quantity == D("12345678901234.123456")
    assert got.price_per_unit == D("0.000001")
    assert isinstance(got.quantity, D)
    assert got.taxes == D("1.25")


def test_timestamps_are_returned_aware_utc(repo, session):
    ist = timezone(timedelta(hours=5, minutes=30))
    t = add(repo, trade_timestamp=datetime(2026, 3, 1, 15, 30, tzinfo=ist))
    session.commit()
    session.expire_all()
    got = repo.get(user_id=USER_A, trade_id=t.id)
    assert got.trade_timestamp == datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
    assert got.trade_timestamp.utcoffset() == timedelta(0)


def test_naive_timestamp_is_refused_by_the_column_type(repo, session):
    with pytest.raises(Exception):
        add(repo, trade_timestamp=datetime(2026, 3, 1, 10, 0))
        session.flush()


def test_get_and_list_are_scoped_to_the_user(repo, session):
    a = add(repo, USER_A)
    b = add(repo, USER_B)
    session.commit()
    assert repo.get(user_id=USER_A, trade_id=a.id).id == a.id
    assert repo.get(user_id=USER_A, trade_id=b.id) is None
    assert [t.id for t in repo.list_for_user(user_id=USER_A)] == [a.id]
    assert [t.id for t in repo.list_for_user(user_id=USER_B)] == [b.id]


def test_list_for_user_is_ordered_deterministically(repo, session):
    late = add(repo, trade_timestamp=T0 + timedelta(hours=2))
    early = add(repo, trade_timestamp=T0)
    session.commit()
    assert [t.id for t in repo.list_for_user(user_id=USER_A)] == [early.id, late.id]


def test_effective_set_excludes_superseded_and_non_executed(repo, session):
    original = add(repo)
    pending = add(repo, status=TradeStatus.PENDING)
    session.commit()
    corrected = add(repo, supersedes_trade_id=original.id)
    voided_target = add(repo)
    session.flush()
    void = add(repo, supersedes_trade_id=voided_target.id, status=TradeStatus.CANCELLED)
    session.commit()
    ids = {t.id for t in repo.list_effective(user_id=USER_A)}
    assert ids == {corrected.id}
    assert original.id not in ids and pending.id not in ids
    assert void.id not in ids and voided_target.id not in ids


def test_effective_set_follows_correction_chains(repo, session):
    first = add(repo)
    session.flush()
    second = add(repo, supersedes_trade_id=first.id)
    session.flush()
    third = add(repo, supersedes_trade_id=second.id)
    session.commit()
    assert [t.id for t in repo.list_effective(user_id=USER_A)] == [third.id]


def test_effective_set_filters_by_instrument_and_as_of_and_user(repo, session):
    from app.domain.instrument import Instrument

    nse = add(repo, trade_timestamp=T0)
    bse = add(repo, exchange=Exchange.BSE, trade_timestamp=T0 + timedelta(hours=1))
    add(repo, USER_B)
    session.commit()
    only_nse = repo.list_effective(user_id=USER_A, instruments=[Instrument("RELIANCE", Exchange.NSE)])
    assert [t.id for t in only_nse] == [nse.id]
    upto = repo.list_effective(user_id=USER_A, as_of=T0)
    assert [t.id for t in upto] == [nse.id]
    assert {t.id for t in repo.list_effective(user_id=USER_A)} == {nse.id, bse.id}


def test_superseder_of_is_scoped_and_finds_the_child(repo, session):
    original = add(repo)
    session.flush()
    child = add(repo, supersedes_trade_id=original.id)
    session.commit()
    assert repo.superseder_of(user_id=USER_A, trade_id=original.id).id == child.id
    assert repo.superseder_of(user_id=USER_A, trade_id=child.id) is None
    assert repo.superseder_of(user_id=USER_B, trade_id=original.id) is None


def test_repository_has_no_mutating_methods():
    public = [n for n in dir(TradeRepository) if not n.startswith("_")]
    assert not [n for n in public if n.startswith(("update", "delete", "remove", "set"))]


def test_every_repository_method_requires_user_id():
    import inspect

    for name in ("add", "get", "list_for_user", "list_effective", "superseder_of"):
        sig = inspect.signature(getattr(TradeRepository, name))
        assert sig.parameters["user_id"].kind is inspect.Parameter.KEYWORD_ONLY, name


def test_orm_refuses_to_update_a_trade(repo, session):
    t = add(repo)
    session.commit()
    t.quantity = D("99")
    with pytest.raises(Exception, match="append-only"):
        session.flush()
    session.rollback()


def test_orm_refuses_to_delete_a_trade(repo, session):
    t = add(repo)
    session.commit()
    session.delete(t)
    with pytest.raises(Exception, match="append-only"):
        session.flush()
    session.rollback()


def test_cross_user_supersede_is_blocked_by_the_database(repo, session):
    a = add(repo, USER_A)
    session.commit()
    with pytest.raises(IntegrityError):
        add(repo, USER_B, supersedes_trade_id=a.id)
        session.flush()
    session.rollback()


def test_a_row_can_be_superseded_only_once(repo, session):
    original = add(repo)
    session.flush()
    add(repo, supersedes_trade_id=original.id)
    session.flush()
    with pytest.raises(IntegrityError):
        add(repo, supersedes_trade_id=original.id)
        session.flush()
    session.rollback()


def test_dedupe_index_applies_to_original_rows_only(repo, session):
    first = add(repo, broker="zerodha", broker_trade_id="T1")
    session.flush()
    add(repo, USER_B, broker="zerodha", broker_trade_id="T1")  # other user is fine
    add(repo, broker="zerodha", broker_trade_id=None)
    add(repo, broker="zerodha", broker_trade_id=None)  # null ids never collide
    add(repo, broker="zerodha", broker_trade_id="T1", supersedes_trade_id=first.id)  # correction
    session.flush()
    with pytest.raises(IntegrityError):
        add(repo, broker="zerodha", broker_trade_id="T1")
        session.flush()
    session.rollback()


@pytest.mark.parametrize(
    "bad",
    [
        {"quantity": D("0")},
        {"quantity": D("-1")},
        {"price_per_unit": D("0")},
        {"brokerage_fee": D("-0.01")},
        {"taxes": D("-1")},
    ],
)
def test_check_constraints_reject_out_of_range_values(repo, session, bad):
    with pytest.raises(IntegrityError):
        add(repo, **bad)
        session.flush()
    session.rollback()


def test_sell_side_round_trips(repo, session):
    t = add(repo, side=TradeSide.SELL)
    session.commit()
    session.expire_all()
    assert repo.get(user_id=USER_A, trade_id=t.id).side is TradeSide.SELL
    assert isinstance(t.id, UUID)


# ---- defect 2: duplicate lookup and a failed insert that leaves the session usable ----

def test_original_lookup_by_broker_trade_id_is_scoped_and_ignores_corrections(repo, session):
    first = add(repo, broker="zerodha", broker_trade_id="T1")
    session.flush()
    add(repo, broker="zerodha", broker_trade_id="T1", supersedes_trade_id=first.id)
    add(repo, USER_B, broker="zerodha", broker_trade_id="T2")
    session.commit()
    found = repo.original_by_broker_trade_id(user_id=USER_A, broker="zerodha", broker_trade_id="T1")
    assert found.id == first.id
    assert repo.original_by_broker_trade_id(user_id=USER_A, broker="zerodha", broker_trade_id="T2") is None
    assert repo.original_by_broker_trade_id(user_id=USER_B, broker="zerodha", broker_trade_id="T1") is None
    assert repo.original_by_broker_trade_id(user_id=USER_A, broker="other", broker_trade_id="T1") is None


def test_original_lookup_is_keyword_only_and_user_scoped():
    import inspect

    sig = inspect.signature(TradeRepository.original_by_broker_trade_id)
    assert sig.parameters["user_id"].kind is inspect.Parameter.KEYWORD_ONLY


def test_a_rejected_insert_rolls_back_only_itself(repo, session):
    kept = add(repo, broker="zerodha", broker_trade_id="T1")
    with pytest.raises(IntegrityError):
        add(repo, broker="zerodha", broker_trade_id="T1")
    later = add(repo, symbol="TCS")  # the session is still usable, and earlier pending work survives
    session.commit()
    assert {t.id for t in repo.list_for_user(user_id=USER_A)} == {kept.id, later.id}
