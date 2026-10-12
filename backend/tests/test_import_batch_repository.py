"""ImportBatch model and repository (plan 002 OPEN-10): user-scoped, counters updated once, trades untouched."""
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.import_batch import ImportBatch
from app.repositories.import_batch_repository import ImportBatchRepository
from tests.conftest import T0, USER_A, USER_B, make_batch


@pytest.fixture
def repo(session):
    return ImportBatchRepository(session)


def test_add_creates_a_batch_with_zero_counts_and_round_trips(repo, session):
    batch = make_batch(session, file_name="a.csv", file_sha256="ab" * 32, created_at=T0 + timedelta(hours=1))
    session.commit()
    session.expire_all()
    got = repo.get(user_id=USER_A, batch_id=batch.id)
    assert (got.file_name, got.file_sha256) == ("a.csv", "ab" * 32)
    assert (got.total_rows, got.imported, got.duplicates, got.rejected_total) == (0, 0, 0, 0)
    assert got.created_at == T0 + timedelta(hours=1) and got.created_at.tzinfo is not None


def test_get_is_scoped_to_the_user(repo, session):
    batch = make_batch(session, USER_A)
    assert repo.get(user_id=USER_B, batch_id=batch.id) is None
    assert repo.get(user_id=USER_A, batch_id=uuid4()) is None


def test_update_counts_sets_the_four_counters(repo, session):
    batch = make_batch(session)
    updated = repo.update_counts(user_id=USER_A, batch_id=batch.id, total_rows=7, imported=4, duplicates=2, rejected_total=1)
    session.commit()
    session.expire_all()
    got = repo.get(user_id=USER_A, batch_id=batch.id)
    assert updated.id == got.id
    assert (got.total_rows, got.imported, got.duplicates, got.rejected_total) == (7, 4, 2, 1)
    assert got.file_name == "synthetic.csv"  # nothing else changes


def test_update_counts_cannot_touch_another_users_batch(repo, session):
    batch = make_batch(session, USER_A)
    with pytest.raises(LookupError):
        repo.update_counts(user_id=USER_B, batch_id=batch.id, total_rows=1, imported=1, duplicates=0, rejected_total=0)
    with pytest.raises(LookupError):
        repo.update_counts(user_id=USER_A, batch_id=uuid4(), total_rows=1, imported=1, duplicates=0, rejected_total=0)
    session.expire_all()
    assert repo.get(user_id=USER_A, batch_id=batch.id).total_rows == 0


def test_the_same_file_can_be_uploaded_twice_so_sha256_is_not_unique(repo, session):
    make_batch(session, file_sha256="cd" * 32)
    make_batch(session, file_sha256="cd" * 32)
    make_batch(session, USER_B, file_sha256="cd" * 32)
    session.commit()
    assert session.query(ImportBatch).count() == 3


def test_a_batch_needs_an_existing_user(session):
    with pytest.raises(IntegrityError):
        make_batch(session, user_id=uuid4())
    session.rollback()


def test_the_repository_exposes_no_delete_and_only_update_counts_mutates():
    public = {name for name in vars(ImportBatchRepository) if not name.startswith("_")}
    assert public == {"add", "get", "update_counts"}


@pytest.mark.parametrize("method", ["get", "update_counts", "add"])
def test_every_method_requires_keyword_only_user_id(method):
    import inspect

    sig = inspect.signature(getattr(ImportBatchRepository, method))
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for n, p in sig.parameters.items() if n != "self")
    assert "user_id" in sig.parameters
