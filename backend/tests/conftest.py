from datetime import datetime, timedelta, timezone
from decimal import Decimal
from itertools import count
from uuid import UUID

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.repositories.user_repository import UserRepository

USER_A = UUID(int=0xA)
USER_B = UUID(int=0xB)
T0 = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)


def make_engine():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):
        dbapi_conn.isolation_level = None  # pysqlite recipe so SAVEPOINT works (see SQLAlchemy sqlite docs)
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    @event.listens_for(engine, "begin")
    def _begin(conn):
        conn.exec_driver_sql("BEGIN")

    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def engine():
    eng = make_engine()
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        users = UserRepository(s)
        users.ensure(USER_A)
        users.ensure(USER_B)
        s.commit()
        yield s


@pytest.fixture
def clock():
    ticks = count()
    return lambda: T0 + timedelta(days=1, seconds=next(ticks))


@pytest.fixture
def id_factory():
    ids = count(1)
    return lambda: UUID(int=next(ids) + 0x1000)


def trade_fields(**overrides):
    """Valid FR-1 field set for the repository (recorded_at/id supplied by caller)."""
    from app.domain.enums import (
        AssetType, Currency, Exchange, MarketSession, TradeSide, TradeSource, TradeStatus,
    )

    base = dict(
        symbol="RELIANCE", name="Reliance Industries", asset_type=AssetType.STOCK,
        exchange=Exchange.NSE, currency=Currency.INR, side=TradeSide.BUY,
        quantity=Decimal("10"), price_per_unit=Decimal("100"),
        brokerage_fee=Decimal("0"), taxes=Decimal("0"),
        trade_timestamp=T0, recorded_at=T0 + timedelta(days=1),
        broker=None, broker_trade_id=None, order_id=None, supersedes_trade_id=None,
        source=TradeSource.MANUAL, market_session=MarketSession.REGULAR,
        status=TradeStatus.EXECUTED, notes=None,
    )
    base.update(overrides)
    return base
