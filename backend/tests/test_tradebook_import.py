"""Tradebook import service (Feature 002c): dedupe, quarantine, oversell, batch lifecycle, isolation, atomicity.

All data is synthetic and built in the tests. SQLite cannot prove PostgreSQL lock semantics: the lock tests here only
check that a refused lock is handled; the real NOWAIT behavior is covered by the live-PostgreSQL tests.
"""
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from app.domain.enums import AssetType, Exchange, MarketSession, TradeSide, TradeSource, TradeStatus
from app.models.import_batch import ImportBatch
from app.models.trade import Trade
from app.repositories.import_batch_repository import ImportBatchRepository
from app.repositories.trade_repository import TradeRepository
from app.services.errors import InvalidImportFileError, LedgerBusyError
from app.services.ledger import CorrectionInput, LedgerService
from app.services.tradebook_import import ImportResult, TradebookImportService
from tests.conftest import T0, USER_A, USER_B, make_batch, trade_fields

ALPHA = "ZZ0ALPHA0001"
BETA = "ZZ0BETACO001"
HEADER = "symbol,isin,trade_date,exchange,segment,series,trade_type,auction,quantity,price,trade_id,order_id,order_execution_time"
FIXTURE = Path(__file__).parent / "fixtures" / "tradebook_synthetic.csv"


def r(tid, side="buy", qty="10", price="100", isin=ALPHA, symbol="ALPHACO", exchange="NSE", ts="2020-03-02T09:30:00", order_id=None):
    """One CSV data row. `ts` is the IST execution time; the trade date is derived from it."""
    series = "EQ" if exchange == "NSE" else "A"
    order_id = order_id if order_id is not None else f"9{int(tid):015d}"
    return f"{symbol},{isin},{ts[:10]},{exchange},EQ,{series},{side},false,{qty},{price},{tid},{order_id},{ts}"


def csv_bytes(*rows):
    return ("\n".join([HEADER, *rows]) + "\n").encode()


@pytest.fixture
def importer(session, clock, id_factory):
    return TradebookImportService.for_session(session, clock=clock, id_factory=id_factory)


def run(importer, *rows, user=USER_A, name="synthetic.csv") -> ImportResult:
    return importer.import_tradebook(user_id=user, file_name=name, content=csv_bytes(*rows))


def trades(session, user=USER_A):
    return list(session.scalars(select(Trade).where(Trade.user_id == user)))


def batches(session, user=USER_A):
    return list(session.scalars(select(ImportBatch).where(ImportBatch.user_id == user)))


def manual(session, **overrides):
    """A manual ledger row (optionally with an ISIN) that the import must take into account."""
    return TradeRepository(session).add(user_id=overrides.pop("user_id", USER_A), id=uuid4(), **trade_fields(**overrides))


def codes(result):
    return [(x.line, x.code) for x in result.rejected]


# ---- basic import ----------------------------------------------------------------------------------------------

def test_valid_rows_import_with_the_documented_trade_fields(importer, session):
    result = run(importer, r(1, qty="10.5", price="100.25", order_id="777"), r(2, side="sell", qty="4", ts="2020-03-03T10:00:00"))
    assert (result.total_rows, result.imported, result.duplicates, result.rejected_total) == (2, 2, 0, 0)
    assert result.rejected == () and result.quarantined_isins == () and result.fees_taxes_provided is False
    first, second = sorted(trades(session), key=lambda t: t.broker_trade_id)
    batch = batches(session)[0]
    assert first.import_batch_id == batch.id == result.import_batch_id
    assert (first.source, first.status, first.broker, first.currency.value) == (TradeSource.IMPORT, TradeStatus.EXECUTED, "ZERODHA", "INR")
    assert (first.isin, first.symbol, first.exchange, first.side) == (ALPHA, "ALPHACO", Exchange.NSE, TradeSide.BUY)
    assert (first.quantity, first.price_per_unit, first.order_id) == (D("10.5"), D("100.25"), "777")
    assert first.trade_timestamp == datetime(2020, 3, 2, 4, 0, tzinfo=timezone.utc)  # 09:30 IST
    assert (first.brokerage_fee, first.taxes, first.charges_provided) == (D(0), D(0), False)
    assert (first.name, first.asset_type, first.market_session) == (None, None, None)
    assert first.supersedes_trade_id is None and first.user_id == USER_A
    assert second.side is TradeSide.SELL


def test_the_batch_records_the_upload(importer, session):
    content = csv_bytes(r(1), r(3))
    result = importer.import_tradebook(user_id=USER_A, file_name="my file.csv", content=content)
    (batch,) = batches(session)
    assert (batch.file_name, batch.user_id) == ("my file.csv", USER_A)
    assert len(batch.file_sha256) == 64 and batch.file_sha256 == result.file_sha256
    assert (batch.total_rows, batch.imported, batch.duplicates, batch.rejected_total) == (2, 2, 0, 0)
    assert batch.created_at.tzinfo is not None


def test_the_synthetic_fixture_imports_six_rows_and_rejects_the_bad_side(importer, session):
    result = importer.import_tradebook(user_id=USER_A, file_name="tradebook_synthetic.csv", content=FIXTURE.read_bytes())
    assert (result.total_rows, result.imported, result.duplicates, result.rejected_total) == (7, 6, 0, 1)
    assert codes(result) == [(8, "invalid_side")]
    assert len(trades(session)) == 6
    # the same ISIN on NSE and BSE with the same trade_id is two trades
    assert {(t.exchange, t.broker_trade_id) for t in trades(session)} >= {(Exchange.NSE, "900001"), (Exchange.BSE, "900001")}


# ---- file-level failures ---------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "content",
    [b"", b"\xff\xfe\x00bad", HEADER.encode() + b"\n", b"symbol,isin\nA,B\n", csv_bytes(r(1)).replace(b",NSE,", b",NSE,extra,")],
    ids=["empty", "not-utf8", "header-only", "wrong-header", "cell-count"],
)
def test_file_level_failures_create_no_batch_and_no_trades(importer, session, content):
    with pytest.raises(InvalidImportFileError):
        importer.import_tradebook(user_id=USER_A, file_name="x.csv", content=content)
    assert batches(session) == [] and trades(session) == []


def test_a_file_over_the_row_cap_is_a_file_level_failure(importer, session):
    rows = [r(i) for i in range(1, 5002)]
    with pytest.raises(InvalidImportFileError):
        run(importer, *rows)
    assert batches(session) == [] and trades(session) == []


# ---- dedupe ----------------------------------------------------------------------------------------------------

def test_reimport_is_all_duplicates_but_still_creates_a_batch(importer, session):
    rows = (r(1), r(2, ts="2020-03-02T09:31:00"))
    run(importer, *rows)
    again = run(importer, *rows)
    assert (again.total_rows, again.imported, again.duplicates, again.rejected_total) == (2, 0, 2, 0)
    assert len(trades(session)) == 2 and len(batches(session)) == 2
    assert {b.imported for b in batches(session)} == {0, 2}


def test_the_same_trade_id_on_nse_and_bse_is_two_trades(importer, session):
    result = run(importer, r(1), r(1, exchange="BSE", ts="2020-03-02T09:31:00"))
    assert (result.imported, result.duplicates) == (2, 0)
    assert len(trades(session)) == 2


def test_a_key_match_with_different_content_is_a_conflicting_duplicate(importer, session):
    run(importer, r(1, price="100"))
    changed = run(importer, r(1, price="101"))
    assert (changed.imported, changed.duplicates, changed.rejected_total) == (0, 0, 1)
    assert codes(changed) == [(2, "conflicting_duplicate")]
    assert "price" in changed.rejected[0].message
    (trade,) = trades(session)
    assert trade.price_per_unit == D("100")  # the original is never overwritten


def test_quantity_and_price_compare_as_numbers_not_text(importer):
    run(importer, r(1, qty="10", price="100"))
    again = run(importer, r(1, qty="10.000000", price="100.0"))
    assert (again.duplicates, again.rejected_total) == (1, 0)


def test_an_existing_null_isin_does_not_create_a_conflict(importer, session):
    batch = make_batch(session)
    TradeRepository(session).add(
        user_id=USER_A, id=uuid4(), **trade_fields(
            symbol="ALPHACO", broker="ZERODHA", broker_trade_id="1", source=TradeSource.IMPORT, import_batch_id=batch.id,
            trade_timestamp=datetime(2020, 3, 2, 4, 0, tzinfo=timezone.utc), quantity=D("10"), price_per_unit=D("100"),
            order_id=None, isin=None,
        )
    )
    again = run(importer, r(1))
    assert (again.duplicates, again.rejected_total, again.imported) == (1, 0, 0)


def test_a_corrected_or_voided_original_stays_the_dedupe_target(importer, session, clock, id_factory):
    run(importer, r(1), r(2, ts="2020-03-02T09:31:00"))
    ledger = LedgerService.for_session(session, clock=clock, id_factory=id_factory)
    first, second = sorted(trades(session), key=lambda t: t.broker_trade_id)
    ledger.void(user_id=USER_A, trade_id=first.id)
    ledger.correct(
        user_id=USER_A, trade_id=second.id,
        data=CorrectionInput(
            symbol="ALPHACO", isin=ALPHA, name="Alpha", asset_type=AssetType.STOCK, exchange=Exchange.NSE,
            side=TradeSide.BUY, quantity=D("10"), price_per_unit=D("100"), trade_timestamp=second.trade_timestamp,
            market_session=MarketSession.REGULAR, brokerage_fee=D("0"), taxes=D("0"),
        ),
    )
    session.commit()
    again = run(importer, r(1), r(2, ts="2020-03-02T09:31:00"))
    assert (again.imported, again.duplicates, again.rejected_total) == (0, 2, 0)


def test_a_repeated_key_in_one_file(importer, session):
    result = run(importer, r(1), r(1), r(1, price="999"), r(2, ts="2020-03-02T09:31:00"))
    assert (result.total_rows, result.imported, result.duplicates, result.rejected_total) == (4, 2, 1, 1)
    assert codes(result) == [(4, "conflicting_duplicate")]
    assert len(trades(session)) == 2


def test_a_repeat_of_a_row_that_was_itself_rejected_is_not_evaluated_again(importer, session):
    result = run(importer, r(1, side="sell", qty="5"), r(1, side="sell", qty="5"))
    assert (result.imported, result.duplicates, result.rejected_total) == (0, 1, 1)
    assert codes(result) == [(2, "oversell")]


def test_a_lost_unique_index_race_is_reclassified_not_assumed(importer, session, monkeypatch):
    run(importer, r(1, price="100"))
    real = TradeRepository.original_by_key
    seen = []

    def blind_first_time(self, **kw):  # pass 1 misses the row another writer inserted meanwhile
        key = (kw["exchange"], kw["broker_trade_id"])
        if key not in seen:
            seen.append(key)
            return None
        return real(self, **kw)

    monkeypatch.setattr(TradeRepository, "original_by_key", blind_first_time)
    same = run(importer, r(1, price="100"))
    assert (same.imported, same.duplicates, same.rejected_total) == (0, 1, 0)
    seen.clear()
    different = run(importer, r(1, price="105"))
    assert (different.imported, different.duplicates, different.rejected_total) == (0, 0, 1)
    assert codes(different) == [(2, "conflicting_duplicate")]
    assert len(trades(session)) == 1


# ---- oversell and quarantine -----------------------------------------------------------------------------------

def test_a_sell_within_the_held_quantity_imports(importer, session):
    result = run(importer, r(1, qty="10"), r(2, side="sell", qty="10", ts="2020-03-03T10:00:00"))
    assert (result.imported, result.rejected_total) == (2, 0)


def test_an_oversell_is_rejected_and_leaves_no_record(importer, session):
    result = run(importer, r(1, qty="10"), r(2, side="sell", qty="11", ts="2020-03-03T10:00:00"))
    assert (result.imported, result.duplicates, result.rejected_total) == (1, 0, 1)
    assert codes(result) == [(3, "oversell")]
    assert result.quarantined_isins == (ALPHA,)
    assert [t.broker_trade_id for t in trades(session)] == ["1"]


def test_isin_is_the_identity_so_an_nse_buy_covers_a_bse_sell(importer):
    result = run(importer, r(1, qty="10"), r(2, side="sell", qty="10", exchange="BSE", ts="2020-03-03T10:00:00"))
    assert (result.imported, result.rejected_total) == (2, 0)


def test_after_the_first_oversell_later_rows_of_that_isin_are_quarantined_but_other_isins_continue(importer, session):
    result = run(
        importer,
        r(1, qty="5", ts="2020-03-02T09:00:00"),
        r(2, side="sell", qty="50", ts="2020-03-02T10:00:00"),
        r(3, qty="100", ts="2020-03-02T11:00:00"),                         # BUY after the oversell
        r(4, side="sell", qty="1", ts="2020-03-02T12:00:00"),              # SELL after the oversell
        r(5, isin=BETA, symbol="BETACO", qty="5", ts="2020-03-02T11:30:00"),
    )
    assert (result.imported, result.rejected_total) == (2, 3)
    assert codes(result) == [(3, "oversell"), (4, "after_oversell"), (5, "after_oversell")]
    assert result.quarantined_isins == (ALPHA,)
    assert {t.broker_trade_id for t in trades(session)} == {"1", "5"}


def test_duplicates_are_classified_before_quarantine(importer, session):
    run(importer, r(1, qty="5", ts="2020-03-02T09:00:00"))
    result = run(
        importer,
        r(2, side="sell", qty="50", ts="2020-03-02T10:00:00"),   # oversell, quarantines the ISIN
        r(1, qty="5", ts="2020-03-02T09:00:00"),                  # identical to the ledger -> duplicate
        r(1, qty="6", ts="2020-03-02T09:00:00", exchange="NSE"),  # repeated key, differs -> conflicting_duplicate
        r(3, qty="1", ts="2020-03-02T11:00:00"),                  # genuinely new -> after_oversell
    )
    assert (result.imported, result.duplicates, result.rejected_total) == (0, 1, 3)
    assert codes(result) == [(2, "oversell"), (4, "conflicting_duplicate"), (5, "after_oversell")]


def test_a_conflict_with_the_ledger_after_an_oversell_stays_a_conflict(importer):
    run(importer, r(1, qty="5", ts="2020-03-02T09:00:00"))
    result = run(importer, r(2, side="sell", qty="50", ts="2020-03-02T10:00:00"), r(1, qty="7", ts="2020-03-02T09:00:00"))
    assert codes(result) == [(2, "oversell"), (3, "conflicting_duplicate")]


def test_a_sell_listed_before_its_earlier_buy_still_imports(importer):
    result = run(importer, r(2, side="sell", qty="10", ts="2020-03-03T10:00:00"), r(1, qty="10", ts="2020-03-02T10:00:00"))
    assert (result.imported, result.rejected_total) == (2, 0)


def test_at_equal_timestamps_a_buy_sorts_before_a_sell(importer):
    result = run(importer, r(2, side="sell", qty="10"), r(1, qty="10"))
    assert (result.imported, result.rejected_total) == (2, 0)


def test_trade_id_breaks_ties_between_equal_timestamp_sells(importer, session):
    result = run(importer, r(1, qty="10", ts="2020-03-02T09:00:00"), r(20, side="sell", qty="6"), r(9, side="sell", qty="6"))
    assert codes(result) == [(3, "oversell")]  # trade 20 (line 3) comes after trade 9 (line 4) in canonical order
    assert {t.broker_trade_id for t in trades(session)} == {"1", "9"}


def test_a_rejected_oversell_can_be_imported_after_the_missing_history_is_loaded(importer, session):
    sells = r(2, side="sell", qty="10", ts="2020-03-03T10:00:00")
    first = run(importer, sells)
    assert (first.imported, first.rejected_total) == (0, 1) and trades(session) == []
    run(importer, r(1, qty="10", ts="2020-03-02T10:00:00"))
    again = run(importer, sells)
    assert (again.imported, again.duplicates, again.rejected_total) == (1, 0, 0)


def test_a_back_dated_sell_that_would_break_a_later_manual_sell_is_rejected(importer, session):
    manual(session, symbol="ALPHACO", isin=ALPHA, quantity=D("10"), trade_timestamp=datetime(2020, 3, 1, tzinfo=timezone.utc))
    manual(session, symbol="ALPHACO", isin=ALPHA, side=TradeSide.SELL, quantity=D("10"), trade_timestamp=datetime(2020, 3, 5, tzinfo=timezone.utc))
    result = run(importer, r(1, side="sell", qty="1", ts="2020-03-02T10:00:00"))
    assert codes(result) == [(2, "oversell")]
    assert len(trades(session)) == 2


def test_legacy_null_isin_rows_never_cover_an_isin_sell(importer, session):
    manual(session, symbol="ALPHACO", isin=None, quantity=D("100"), trade_timestamp=datetime(2020, 3, 1, tzinfo=timezone.utc))
    result = run(importer, r(1, side="sell", qty="1", ts="2020-03-02T10:00:00"))
    assert codes(result) == [(2, "oversell")]


def test_a_manual_buy_with_the_isin_covers_an_imported_sell(importer, session):
    manual(session, symbol="ALPHACO", isin=ALPHA, quantity=D("10"), trade_timestamp=datetime(2020, 3, 1, tzinfo=timezone.utc))
    result = run(importer, r(1, side="sell", qty="10", ts="2020-03-02T10:00:00"))
    assert (result.imported, result.rejected_total) == (1, 0)


def test_a_running_total_over_the_calculation_limit_is_rejected_without_quarantine(importer, session):
    big = "99999999999999"
    result = run(
        importer,
        r(1, qty=big, price="9", ts="2020-03-02T09:00:00"),
        r(2, qty=big, price="9", ts="2020-03-02T10:00:00"),
        r(3, qty="1", price="1", ts="2020-03-02T11:00:00"),
    )
    assert codes(result) == [(3, "numeric_limit_exceeded")]
    assert result.quarantined_isins == () and result.imported == 2


# ---- batch lifecycle and result --------------------------------------------------------------------------------

def test_an_all_rejected_upload_still_creates_a_batch(importer, session):
    result = run(importer, r(1, side="hold"), r(2, side="hold"))
    assert (result.total_rows, result.imported, result.duplicates, result.rejected_total) == (2, 0, 0, 2)
    (batch,) = batches(session)
    assert (batch.imported, batch.duplicates, batch.rejected_total) == (0, 0, 2) and trades(session) == []


def test_every_row_has_exactly_one_outcome(importer, session):
    run(importer, r(1, ts="2020-03-02T09:00:00"))
    result = run(
        importer,
        r(1, ts="2020-03-02T09:00:00"),                    # duplicate
        r(1, price="5", ts="2020-03-02T09:00:00"),         # conflicting duplicate
        r(2, side="hold"),                                 # parser rejection
        r(3, side="sell", qty="500", ts="2020-03-02T10:00:00"),   # oversell
        r(4, qty="1", ts="2020-03-02T11:00:00"),           # after_oversell
        r(5, isin=BETA, symbol="BETACO", qty="1"),         # imported
    )
    assert result.total_rows == 6
    assert (result.imported, result.duplicates, result.rejected_total) == (1, 1, 4)
    assert result.imported + result.duplicates + result.rejected_total == result.total_rows
    (_, latest) = sorted(batches(session), key=lambda b: b.created_at)
    assert (latest.total_rows, latest.imported, latest.duplicates, latest.rejected_total) == (6, 1, 1, 4)
    assert [x.line for x in result.rejected] == sorted(x.line for x in result.rejected)


def test_only_the_first_200_rejections_are_listed_but_the_count_is_exact(importer, session):
    result = run(importer, *[r(i, side="hold") for i in range(1, 251)])
    assert result.rejected_total == 250 and len(result.rejected) == 200
    assert [x.line for x in result.rejected] == list(range(2, 202))
    assert batches(session)[0].rejected_total == 250


def test_service_rejections_merge_with_parser_rejections_in_line_order(importer):
    result = run(importer, r(1, side="sell", qty="5"), r(2, side="hold"), r(3, side="sell", qty="5", ts="2020-03-02T09:31:00"))
    assert codes(result) == [(2, "oversell"), (3, "invalid_side"), (4, "after_oversell")]


# ---- user isolation --------------------------------------------------------------------------------------------

def test_another_users_identical_file_is_independent(importer, session):
    rows = (r(1), r(2, side="sell", qty="4", ts="2020-03-03T10:00:00"))
    a = run(importer, *rows, user=USER_A)
    b = run(importer, *rows, user=USER_B)
    assert (a.imported, b.imported, b.duplicates) == (2, 2, 0)
    assert len(trades(session, USER_A)) == len(trades(session, USER_B)) == 2
    assert a.import_batch_id != b.import_batch_id
    repo = ImportBatchRepository(session)
    assert repo.get(user_id=USER_B, batch_id=a.import_batch_id) is None
    assert repo.get(user_id=USER_A, batch_id=b.import_batch_id) is None


def test_another_users_holdings_never_cover_a_sell(importer, session):
    run(importer, r(1, qty="10"), user=USER_A)
    result = run(importer, r(2, side="sell", qty="1", ts="2020-03-03T10:00:00"), user=USER_B)
    assert codes(result) == [(2, "oversell")]
    assert [t.broker_trade_id for t in trades(session, USER_A)] == ["1"] and trades(session, USER_B) == []


def test_importing_for_one_user_never_writes_rows_for_another(importer, session):
    run(importer, r(1), r(2, ts="2020-03-02T09:31:00"), user=USER_B)
    assert trades(session, USER_A) == [] and batches(session, USER_A) == []
    assert all(t.import_batch_id == batches(session, USER_B)[0].id for t in trades(session, USER_B))


# ---- atomicity and the lock ------------------------------------------------------------------------------------

def test_an_unexpected_failure_mid_file_rolls_back_the_rows_and_the_batch(importer, session, monkeypatch):
    real = TradeRepository.add
    calls = []

    def fail_on_third(self, **kw):
        calls.append(1)
        if len(calls) == 3:
            raise RuntimeError("boom")
        return real(self, **kw)

    monkeypatch.setattr(TradeRepository, "add", fail_on_third)
    with pytest.raises(RuntimeError, match="boom"):
        run(importer, r(1), r(2, ts="2020-03-02T09:31:00"), r(3, ts="2020-03-02T09:32:00"))
    assert batches(session) == [] and trades(session) == []


def _busy():
    class Orig(Exception):
        sqlstate = "55P03"

    return OperationalError("SELECT ... FOR UPDATE NOWAIT", {}, Orig("could not obtain lock"))


def test_a_held_lock_returns_ledger_busy_and_creates_no_batch(importer, session, monkeypatch):
    def refuse(self, **kw):
        raise _busy()

    monkeypatch.setattr(TradeRepository, "lock_user_ledger", refuse)
    with pytest.raises(LedgerBusyError):
        run(importer, r(1))
    assert batches(session) == [] and trades(session) == []


def test_other_database_errors_from_the_lock_are_not_called_busy(importer, session, monkeypatch):
    class Orig(Exception):
        sqlstate = "08006"

    def fail(self, **kw):
        raise OperationalError("SELECT", {}, Orig("connection lost"))

    monkeypatch.setattr(TradeRepository, "lock_user_ledger", fail)
    with pytest.raises(OperationalError):
        run(importer, r(1))
    assert batches(session) == []


def test_a_user_without_a_users_row_is_a_setup_error_not_a_business_error(importer, session):
    with pytest.raises(RuntimeError, match="users row"):
        run(importer, r(1), user=uuid4())
    assert session.scalar(select(func.count()).select_from(ImportBatch)) == 0


def test_parsing_happens_before_the_lock(importer, monkeypatch):
    def must_not_run(self, **kw):
        raise AssertionError("lock taken before the file was parsed")

    monkeypatch.setattr(TradeRepository, "lock_user_ledger", must_not_run)
    with pytest.raises(InvalidImportFileError):
        importer.import_tradebook(user_id=USER_A, file_name="x.csv", content=b"")


# ---- calculation limit is separate from oversell quarantine ---------------------------------------------------

BIG = "99999999999999"  # 14 integer digits at price 9: each buy is under 10^15 but two of them are not


def test_a_limit_rejection_does_not_quarantine_and_a_later_new_row_of_the_same_isin_imports(importer, session):
    result = run(
        importer,
        r(1, qty=BIG, price="9", ts="2020-03-02T09:00:00"),
        r(2, qty=BIG, price="9", ts="2020-03-02T10:00:00"),   # running cost reaches the limit -> rejected
        r(3, qty="1", price="1", ts="2020-03-02T11:00:00"),   # genuinely new, same ISIN
        r(4, side="sell", qty="1", ts="2020-03-02T12:00:00"),  # a valid sell of the same ISIN
    )
    assert codes(result) == [(3, "numeric_limit_exceeded")]
    assert result.quarantined_isins == ()
    assert (result.imported, result.duplicates, result.rejected_total) == (3, 0, 1)
    assert "after_oversell" not in {x.code for x in result.rejected}
    assert {t.broker_trade_id for t in trades(session)} == {"1", "3", "4"}


def test_other_isins_continue_after_a_limit_rejection(importer):
    result = run(
        importer,
        r(1, qty=BIG, price="9", ts="2020-03-02T09:00:00"),
        r(2, qty=BIG, price="9", ts="2020-03-02T10:00:00"),
        r(3, isin=BETA, symbol="BETACO", qty="5", ts="2020-03-02T11:00:00"),
    )
    assert codes(result) == [(3, "numeric_limit_exceeded")] and result.imported == 2


def test_a_real_oversell_after_a_limit_rejection_still_quarantines(importer, session):
    result = run(
        importer,
        r(1, qty=BIG, price="9", ts="2020-03-02T09:00:00"),
        r(2, qty=BIG, price="9", ts="2020-03-02T10:00:00"),                   # limit rejection, no quarantine
        r(3, side="sell", qty=BIG, price="1", ts="2020-03-02T11:00:00"),                 # sells everything held: fine
        r(4, side="sell", qty="1", ts="2020-03-02T12:00:00"),                 # nothing left: oversell, quarantines
        r(5, qty="1", price="1", ts="2020-03-02T13:00:00"),                   # now after_oversell
        r(6, isin=BETA, symbol="BETACO", qty="1", ts="2020-03-02T13:30:00"),  # other ISIN unaffected
    )
    assert codes(result) == [(3, "numeric_limit_exceeded"), (5, "oversell"), (6, "after_oversell")]
    assert result.quarantined_isins == (ALPHA,)
    assert {t.broker_trade_id for t in trades(session)} == {"1", "3", "6"}


def test_history_already_at_the_limit_gives_numeric_limit_for_every_new_row_never_after_oversell(importer, session):
    for n in (0, 1):
        manual(
            session, symbol="ALPHACO", isin=ALPHA, quantity=D(BIG), price_per_unit=D("9"),
            trade_timestamp=datetime(2020, 3, 1, 9 + n, tzinfo=timezone.utc),
        )
    result = run(importer, r(1, qty="1", ts="2020-03-02T09:00:00"), r(2, qty="1", ts="2020-03-02T10:00:00"))
    assert codes(result) == [(2, "numeric_limit_exceeded"), (3, "numeric_limit_exceeded")]
    assert result.quarantined_isins == () and result.imported == 0


def test_the_ordinary_oversell_quarantine_is_unchanged(importer):
    result = run(
        importer,
        r(1, qty="5", ts="2020-03-02T09:00:00"),
        r(2, side="sell", qty="6", ts="2020-03-02T10:00:00"),
        r(3, qty="1", ts="2020-03-02T11:00:00"),
    )
    assert codes(result) == [(3, "oversell"), (4, "after_oversell")]
    assert result.quarantined_isins == (ALPHA,)
