"""Import is order-independent: the whole ledger is replayed in trade-time order, not insertion order."""

from itertools import count
from uuid import UUID

from analysis_helpers import D_ASOF, NOW, TRADED_ISIN, FakeBars, config
from conftest import USER_A, make_engine
from sqlalchemy.orm import Session

from app.repositories.trade_repository import TradeRepository
from app.repositories.user_repository import UserRepository
from app.services.holdings import fold_ledger
from app.services.portfolio_analysis import PortfolioAnalysisService
from app.services.tradebook_import import TradebookImportService
from tests.test_tradebook_import import csv_bytes, r


def row(tid, side, qty, day):
    return r(tid, side=side, qty=qty, price="100", isin=TRADED_ISIN, symbol="TEST1", ts=f"2026-03-{day:02d}T09:30:00")


A = (row(1, "buy", "10", 2), row(2, "sell", "10", 10))
B = (row(3, "buy", "5", 4), row(4, "sell", "5", 6))
LATE_SELL = (row(5, "sell", "10", 10),)
EARLY_BUY = (row(6, "buy", "10", 2),)
IMPOSSIBLE = (row(7, "buy", "10", 2), row(8, "sell", "20", 10))


def replay(*uploads):
    """Fresh world; import the uploads in order; return (rejections per upload, ledger rows, holdings, analysis)."""
    ticks, ids = count(), count(1)
    with Session(make_engine()) as session:
        UserRepository(session).ensure(USER_A)
        session.commit()
        svc = TradebookImportService.for_session(session, clock=lambda: NOW.replace(second=next(ticks) % 60),
                                                 id_factory=lambda: UUID(int=next(ids) + 0x1000))
        rejections = [[(x.line, x.code) for x in svc.import_tradebook(user_id=USER_A, file_name="f.csv", content=csv_bytes(*u)).rejected]
                      for u in uploads]
        repo = TradeRepository(session)
        effective = repo.list_effective(user_id=USER_A)
        rows = sorted((t.symbol, t.side.value, t.quantity, t.price_per_unit, t.trade_timestamp, t.broker_trade_id) for t in effective)
        folded = fold_ledger([_entry(t) for t in effective])
        holdings = [(h.key, h.quantity, h.invested_amount) for h in folded.holdings]
        facts = PortfolioAnalysisService(repo=repo, provider=FakeBars(), clock=lambda: NOW, config=config()).analyse(USER_A, D_ASOF)
        analysis = ([f.to_dict() for f in facts.facts], facts.provenance["seeds"], facts.provenance["input_fingerprints"])
        return rejections, rows, holdings, analysis


def _entry(t):
    from app.services.tradebook_import import _entry as entry
    return entry(t)


def test_feasible_split_is_identical_in_either_upload_order():
    ab, ba = replay(A, B), replay(B, A)
    assert ab[0] == ba[0] == [[], []] and ab[1:] == ba[1:]
    assert len(ab[1]) == 4 and ab[2] == []  # fully closed: no holdings left


def test_whole_file_equals_split_uploads():
    assert replay(A + B)[1:] == replay(A, B)[1:] == replay(B, A)[1:]


def test_sell_uploaded_before_its_buy_is_rejected_then_converges_on_reupload():
    sell_first = replay(LATE_SELL, EARLY_BUY, LATE_SELL)
    in_order = replay(EARLY_BUY, LATE_SELL)
    assert sell_first[0][0] == [(2, "oversell")] and sell_first[0][1:] == [[], []]
    assert sell_first[1:] == in_order[1:]


def test_a_genuinely_impossible_sell_is_rejected_whatever_the_order():
    one, split_a, split_b = replay(IMPOSSIBLE), replay(IMPOSSIBLE[:1], IMPOSSIBLE[1:]), replay(IMPOSSIBLE[1:], IMPOSSIBLE[:1], IMPOSSIBLE[1:])
    for out in (one, split_a, split_b):
        assert out[1] == one[1] and out[2] == one[2]  # only the buy stands
        assert [c for rej in out[0] for _, c in rej].count("oversell") >= 1
