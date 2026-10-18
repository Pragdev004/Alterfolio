"""One ISIN traded on NSE and BSE is one holding (real-data bug): buy 10 NSE, buy 10 BSE, sell 20 BSE -> 0 held."""
from decimal import Decimal as D

import pytest

from app.services.holdings import fold_holdings
from app.services.ledger import LedgerService
from app.services.tradebook_import import TradebookImportService
from tests.conftest import USER_A
from tests.test_tradebook_import import csv_bytes, r

ROWS = (
    r(1, "buy", "10", "100", exchange="NSE", ts="2020-03-02T09:30:00"),
    r(2, "buy", "10", "101", exchange="BSE", ts="2020-03-03T09:30:00"),
    r(3, "sell", "20", "110", exchange="BSE", ts="2020-03-04T09:30:00"),
)


@pytest.fixture
def imported(session, clock, id_factory):
    importer = TradebookImportService.for_session(session, clock=clock, id_factory=id_factory)
    result = importer.import_tradebook(user_id=USER_A, file_name="x.csv", content=csv_bytes(*ROWS))
    return session, result


def test_import_accepts_the_cross_listing_sell(imported):
    _, result = imported
    assert (result.imported, result.rejected_total) == (3, 0)


def test_holdings_are_zero_after_the_cross_listing_sell(imported, clock):
    session, _ = imported
    held = LedgerService.for_session(session, clock=clock).holdings(user_id=USER_A)
    assert [h for h in held if h.quantity > D(0)] == []


def _held(session, clock):
    return [h for h in LedgerService.for_session(session, clock=clock).holdings(user_id=USER_A) if h.quantity > D(0)]


@pytest.mark.parametrize("split", [(1, 2), (2, 1), (0, 3)])
def test_separate_files_in_any_order_converge_to_zero(session, clock, id_factory, split):
    importer = TradebookImportService.for_session(session, clock=clock, id_factory=id_factory)
    files = [ROWS[: split[0]] or ROWS[:0], ROWS[split[0]:]]
    for f in files:
        if f:
            importer.import_tradebook(user_id=USER_A, file_name="x.csv", content=csv_bytes(*f))
    assert _held(session, clock) == []


def test_bse_symbol_differing_from_nse_symbol(session, clock, id_factory):
    importer = TradebookImportService.for_session(session, clock=clock, id_factory=id_factory)
    rows = (
        r(1, "buy", "10", "100", exchange="NSE", symbol="ALPHACO", ts="2020-03-02T09:30:00"),
        r(2, "buy", "10", "101", exchange="BSE", symbol="500001", ts="2020-03-03T09:30:00"),
        r(3, "sell", "20", "110", exchange="BSE", symbol="500001", ts="2020-03-04T09:30:00"),
    )
    result = importer.import_tradebook(user_id=USER_A, file_name="x.csv", content=csv_bytes(*rows))
    assert result.rejected_total == 0 and _held(session, clock) == []
