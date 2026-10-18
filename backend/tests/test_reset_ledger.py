"""scripts/reset_ledger.py: dev-only ledger reset. Scoped to one user, refuses non-local databases, dry run by default."""
import sys
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.models.import_batch import ImportBatch
from app.models.trade import Trade
from app.services.tradebook_import import TradebookImportService
from tests.conftest import USER_A, USER_B
from tests.test_tradebook_import import csv_bytes, r

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import reset_ledger  # noqa: E402


def _import(session, clock, id_factory, user, *rows):
    TradebookImportService.for_session(session, clock=clock, id_factory=id_factory).import_tradebook(
        user_id=user, file_name="x.csv", content=csv_bytes(*rows))


def test_reset_deletes_only_the_users_trades_and_batches_then_reimport_works(session, clock, id_factory):
    _import(session, clock, id_factory, USER_A, r(1), r(2, side="sell", qty="10", ts="2020-03-03T10:00:00"))
    _import(session, clock, id_factory, USER_B, r(1))
    assert reset_ledger.counts(session, USER_A) == (2, 1)
    assert reset_ledger.reset_ledger(session, USER_A) == (2, 1)
    assert reset_ledger.counts(session, USER_A) == (0, 0) and reset_ledger.counts(session, USER_B) == (1, 1)
    _import(session, clock, id_factory, USER_A, r(1))  # the same trade id imports again: it is no longer a duplicate
    assert session.scalar(select(func.count()).select_from(Trade).where(Trade.user_id == USER_A)) == 1
    assert session.scalar(select(func.count()).select_from(ImportBatch).where(ImportBatch.user_id == USER_A)) == 1


@pytest.mark.parametrize("url", ["postgresql://u:p@db.example.com/x", "postgresql://u:p@10.0.0.5/x"])
def test_non_local_databases_are_refused(url):
    with pytest.raises(SystemExit):
        reset_ledger.refuse_non_local(url)


@pytest.mark.parametrize("url", ["postgresql://u:p@localhost/x", "postgresql://u:p@127.0.0.1:5432/x", "postgresql:///x", "sqlite://"])
def test_local_databases_are_allowed(url):
    reset_ledger.refuse_non_local(url)


def test_main_without_yes_is_a_dry_run(monkeypatch, capsys):
    class _S:
        database_url = "postgresql://u:p@localhost/x"
        user_id = USER_A

    class _Sess:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def commit(self): raise AssertionError("a dry run must not commit")

    monkeypatch.setattr(reset_ledger, "Settings", _S)
    monkeypatch.setattr(reset_ledger, "make_session_factory", lambda url: _Sess)
    monkeypatch.setattr(reset_ledger, "counts", lambda s, u: (3, 1))
    monkeypatch.setattr(reset_ledger, "reset_ledger", lambda s, u: (_ for _ in ()).throw(AssertionError("must not delete")))
    assert reset_ledger.main([]) == 0
    assert "dry run: would delete 3 trades and 1 import batches" in capsys.readouterr().out
