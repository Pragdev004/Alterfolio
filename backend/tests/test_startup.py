"""The production entry path: settings -> session factory -> lifespan seeding -> serving requests."""
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

import app.api.main as api_main
from app.api.main import create_app
from app.config import DEFAULT_USER_ID, Settings
from app.db.session import make_session_factory
from app.models.user import User
from app.services.users import ensure_user

BODY = {
    "symbol": "RELIANCE", "isin": "ZZ0RELIANCE1", "name": "Reliance Industries", "asset_type": "STOCK", "exchange": "NSE",
    "side": "BUY", "quantity": "10", "price_per_unit": "100",
    "trade_timestamp": "2026-01-01T10:00:00Z", "market_session": "REGULAR",
}


def user_ids(engine) -> list[UUID]:
    with Session(engine) as s:
        return [u.id for u in s.scalars(select(User))]


def test_ensure_user_is_idempotent(session):
    new = UUID(int=0xC)
    assert ensure_user(session, new) is None
    ensure_user(session, new)
    session.commit()
    assert [u.id for u in session.scalars(select(User).where(User.id == new))] == [new]


def test_lifespan_seeds_the_configured_user_so_the_first_request_works(engine, monkeypatch):
    monkeypatch.setattr(api_main, "make_session_factory", lambda url: sessionmaker(engine, expire_on_commit=False))
    app = create_app(settings=Settings(database_url="postgresql://stub/stub", user_id=DEFAULT_USER_ID))
    assert user_ids(engine) == []  # create_app alone seeds nothing; startup does
    with TestClient(app) as client:
        assert user_ids(engine) == [DEFAULT_USER_ID]
        assert client.post("/trades", json=BODY).status_code == 201
        assert len(client.get("/trades").json()) == 1
    with TestClient(app):  # a restart is idempotent
        pass
    assert user_ids(engine) == [DEFAULT_USER_ID]


def test_lifespan_seeds_a_non_default_configured_user(engine, monkeypatch):
    other = UUID(int=0x77)
    monkeypatch.setattr(api_main, "make_session_factory", lambda url: sessionmaker(engine, expire_on_commit=False))
    app = create_app(settings=Settings(database_url="postgresql://stub/stub", user_id=other))
    with TestClient(app) as client:
        assert client.post("/trades", json=BODY).status_code == 201
    assert user_ids(engine) == [other]


def test_an_injected_session_factory_is_not_seeded_by_the_app(engine):
    app = create_app(session_factory=sessionmaker(engine, expire_on_commit=False), settings=Settings())
    with TestClient(app):
        pass
    assert user_ids(engine) == []  # tests and embedders own their data


def test_make_session_factory_builds_a_lazy_non_expiring_factory():
    factory = make_session_factory("postgresql+psycopg://localhost/placeholder")  # builds an engine; never connects
    try:
        assert factory.kw["expire_on_commit"] is False
        assert factory.kw["bind"].url.host == "localhost" and factory.kw["bind"].url.database == "placeholder"
    finally:
        factory.kw["bind"].dispose()


@pytest.mark.parametrize("url", ["sqlite:///x.db", "mysql://localhost/x", "postgres-ish"])
def test_the_server_refuses_anything_that_is_not_postgresql(url):
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        create_app(settings=Settings(database_url=url))
