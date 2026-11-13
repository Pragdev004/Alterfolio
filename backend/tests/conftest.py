import os
import re
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

# Feature 015: AI settings present when the run started (only the opt-in live eval reads them). Every other test runs
# with them cleared and backend/.env disabled, so a developer key never makes an offline test call a model (rule 2).
_AI_NAME = re.compile(r"^(?:AI_[A-Z0-9_]+|[A-Z0-9]+_API_KEY)$")
AI_ENV_AT_START = {k: v for k, v in os.environ.items() if _AI_NAME.match(k)}


@pytest.fixture(autouse=True)
def _offline_ai_env(monkeypatch):
    for name in AI_ENV_AT_START:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AI_DOTENV", "0")


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


def make_batch(session, user_id=USER_A, **overrides):
    """An import batch owned by `user_id`; every source=IMPORT trade must reference one."""
    from uuid import uuid4

    from app.repositories.import_batch_repository import ImportBatchRepository

    fields = dict(id=uuid4(), file_name="synthetic.csv", file_sha256="0" * 64, created_at=T0)
    fields.update(overrides)
    return ImportBatchRepository(session).add(user_id=user_id, **fields)


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
