"""Live PostgreSQL verification. Skipped unless ALTERFOLIO_TEST_DATABASE_URL points at an EMPTY throwaway database."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from uuid import uuid4

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.api.main import create_app
from app.config import Settings
from app.domain.enums import AssetType, Exchange, MarketSession, TradeSide, TradeSource
from app.repositories.trade_repository import TradeRepository
from app.repositories.user_repository import UserRepository
from app.services.errors import OversellError
from app.services.ledger import CorrectionInput, LedgerService, TradeInput
from tests.conftest import T0, USER_A, USER_B, make_batch, trade_fields
from tests.test_migration import LIVE_URL, alembic_config, live_only, require_empty_database

pytestmark = live_only


@pytest.fixture(scope="module")
def pg_engine():
    engine = create_engine(LIVE_URL)
    cfg = alembic_config()
    with engine.begin() as conn:
        require_empty_database(conn)
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
    try:
        yield engine
    finally:
        with engine.begin() as conn:
            # Test isolation only: the tests leave rows behind (imported rows have NULL name/asset_type/market_session) and
            # the 0002 downgrade deliberately refuses to rewrite such rows, so empty the tables before migrating down.
            conn.execute(text("TRUNCATE trades, import_batches, users CASCADE"))
            cfg.attributes["connection"] = conn
            command.downgrade(cfg, "base")
        engine.dispose()


@pytest.fixture
def factory(pg_engine):
    with pg_engine.begin() as conn:
        conn.execute(text("TRUNCATE trades, users CASCADE"))
    maker = sessionmaker(pg_engine, expire_on_commit=False)
    with maker() as s:
        users = UserRepository(s)
        users.ensure(USER_A)
        users.ensure(USER_B)
        s.commit()
    return maker


def ti(**kw):
    base = dict(
        symbol="RELIANCE", name="Reliance Industries", asset_type=AssetType.STOCK,
        exchange=Exchange.NSE, side=TradeSide.BUY, quantity=D("10"), price_per_unit=D("100"),
        trade_timestamp=T0, market_session=MarketSession.REGULAR, isin="ZZ0RELIANCE1",
    )
    base.update(kw)
    return TradeInput(**base)


def service(session):
    ticks = iter(range(10**6))
    return LedgerService.for_session(session, clock=lambda: T0 + timedelta(days=1, seconds=next(ticks)))


def _add(s, user=USER_A, **kw):
    return TradeRepository(s).add(user_id=user, id=kw.pop("id", uuid4()), **trade_fields(**kw))


def test_column_types_are_numeric_20_6_and_timestamptz(pg_engine):
    with pg_engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT column_name, data_type, numeric_precision, numeric_scale FROM information_schema.columns "
            "WHERE table_name = 'trades' AND column_name IN "
            "('quantity','price_per_unit','brokerage_fee','taxes','trade_timestamp','recorded_at')"
        )).all()
    by_name = {r[0]: r[1:] for r in rows}
    for name in ("quantity", "price_per_unit", "brokerage_fee", "taxes"):
        assert by_name[name] == ("numeric", 20, 6), name
    for name in ("trade_timestamp", "recorded_at"):
        assert by_name[name][0] == "timestamp with time zone", name


def test_decimals_round_trip_exactly_at_the_precision_limit(factory):
    with factory() as s:
        t = service(s).record(
            user_id=USER_A,
            data=ti(quantity=D("12345678901234.123456"), price_per_unit=D("0.000001"), taxes=D("0.5")),
        )
        s.commit()
    with factory() as s:
        got = TradeRepository(s).get(user_id=USER_A, trade_id=t.id)
        assert (got.quantity, got.price_per_unit, got.taxes) == (
            D("12345678901234.123456"), D("0.000001"), D("0.5"),
        )
        assert isinstance(got.quantity, D)


def test_timestamps_come_back_aware_utc(factory):
    ist = timezone(timedelta(hours=5, minutes=30))
    with factory() as s:
        t = service(s).record(user_id=USER_A, data=ti(trade_timestamp=datetime(2026, 3, 1, 15, 30, tzinfo=ist)))
        s.commit()
    with factory() as s:
        got = TradeRepository(s).get(user_id=USER_A, trade_id=t.id)
        assert got.trade_timestamp == datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
        assert got.trade_timestamp.utcoffset() == timedelta(0) and got.recorded_at.tzinfo is not None


def test_dedupe_partial_unique_index_applies_to_original_rows_only(factory):
    with factory() as s:
        first = _add(s, broker="zerodha", broker_trade_id="T1")
        _add(s, USER_B, broker="zerodha", broker_trade_id="T1")
        _add(s, broker="zerodha", broker_trade_id=None)
        _add(s, broker="zerodha", broker_trade_id=None)
        _add(s, broker="zerodha", broker_trade_id="T1", supersedes_trade_id=first.id)
        _add(s, broker="zerodha", broker_trade_id="T1", exchange=Exchange.BSE)  # same id, other exchange
        s.commit()
        with pytest.raises(IntegrityError):
            _add(s, broker="zerodha", broker_trade_id="T1")
        s.rollback()
        assert TradeRepository(s).original_by_key(
            user_id=USER_A, broker="zerodha", exchange=Exchange.BSE, broker_trade_id="T1"
        ) is not None


def test_import_columns_constraints_and_batch_foreign_key(factory):
    with factory() as s:
        batch_a = make_batch(s, USER_A)
        batch_b = make_batch(s, USER_B)
        ok = _add(
            s, source=TradeSource.IMPORT, import_batch_id=batch_a.id, charges_provided=False, isin="ZZ0ALPHA0001",
            name=None, asset_type=None, market_session=None,
        )
        s.commit()
        assert ok.charges_provided is False
        for bad in (
            dict(isin="SHORT"),
            dict(source=TradeSource.IMPORT, import_batch_id=None),
            dict(source=TradeSource.MANUAL, import_batch_id=batch_a.id),
            dict(source=TradeSource.IMPORT, import_batch_id=batch_b.id),  # another user's batch
        ):
            with pytest.raises(IntegrityError):
                _add(s, **bad)
            s.rollback()


def test_supersede_uniqueness_and_same_user_foreign_key(factory):
    with factory() as s:
        a = _add(s, USER_A)
        s.commit()
        _add(s, USER_A, supersedes_trade_id=a.id)
        s.commit()
        with pytest.raises(IntegrityError):
            _add(s, USER_A, supersedes_trade_id=a.id)
        s.rollback()
        with pytest.raises(IntegrityError):
            _add(s, USER_B, supersedes_trade_id=a.id)
        s.rollback()


@pytest.mark.parametrize(
    "bad",
    [{"quantity": D("0")}, {"price_per_unit": D("0")}, {"brokerage_fee": D("-0.01")}, {"taxes": D("-1")}],
)
def test_check_constraints_hold_in_postgres(factory, bad):
    with factory() as s:
        with pytest.raises(IntegrityError):
            _add(s, **bad)
        s.rollback()


def test_enum_check_constraints_reject_unlisted_values(factory):
    with factory() as s:
        with pytest.raises(IntegrityError):
            s.execute(text(
                "INSERT INTO trades (id, user_id, symbol, name, asset_type, exchange, currency, side, quantity, "
                "price_per_unit, brokerage_fee, taxes, trade_timestamp, recorded_at, source, market_session, status) "
                "VALUES (:id, :u, 'X', 'X', 'STOCK', 'NFO', 'INR', 'BUY', 1, 1, 0, 0, now(), now(), 'MANUAL', "
                "'REGULAR', 'EXECUTED')"
            ), {"id": uuid4(), "u": USER_A})
        s.rollback()


def test_trades_are_append_only_in_postgres_too(factory):
    with factory() as s:
        t = _add(s)
        s.commit()
        t.quantity = D("99")
        with pytest.raises(Exception, match="append-only"):
            s.flush()
        s.rollback()
        s.delete(t)
        with pytest.raises(Exception, match="append-only"):
            s.flush()
        s.rollback()


def test_ledger_flow_with_fees_correction_void_and_oversell_rollback(factory):
    with factory() as s:
        svc = service(s)
        buy = svc.record(user_id=USER_A, data=ti(brokerage_fee=D("10"), taxes=D("5")))
        s.commit()
        (h,) = svc.holdings(user_id=USER_A)
        assert (h.invested_amount, h.average_buy_price) == (D("1015"), D("101.5"))
        with pytest.raises(OversellError):
            svc.record(user_id=USER_A, data=ti(
                side=TradeSide.SELL, quantity=D("11"), trade_timestamp=T0 + timedelta(hours=1)))
        s.rollback()
        assert len(svc.list_trades(user_id=USER_A)) == 1
        fixed = svc.correct(
            user_id=USER_A, trade_id=buy.id,
            data=CorrectionInput(
                symbol="RELIANCE", isin="ZZ0RELIANCE1", name="Reliance Industries", asset_type=AssetType.STOCK,
                exchange=Exchange.NSE, side=TradeSide.BUY, quantity=D("8"), price_per_unit=D("100"),
                trade_timestamp=T0, market_session=MarketSession.REGULAR, brokerage_fee=D("10"), taxes=D("5"),
            ),
        )
        svc.void(user_id=USER_A, trade_id=fixed.id)
        s.commit()
        assert svc.holdings(user_id=USER_A) == []
        assert len(svc.list_trades(user_id=USER_A)) == 3
        assert svc.list_trades(user_id=USER_B) == []


def test_api_end_to_end_on_postgres(factory):
    app = create_app(session_factory=factory, settings=Settings(user_id=USER_A))
    client = TestClient(app)
    payload = {
        "symbol": "RELIANCE", "isin": "ZZ0RELIANCE1", "name": "Reliance Industries", "asset_type": "STOCK",
        "exchange": "NSE", "side": "BUY", "quantity": "10", "price_per_unit": "100", "brokerage_fee": "10", "taxes": "5",
        "trade_timestamp": "2026-01-01T10:00:00Z", "market_session": "REGULAR",
    }
    r = client.post("/trades", json=payload)
    assert r.status_code == 201 and r.json()["quantity"] == "10.000000"
    (h,) = client.get("/portfolio/holdings").json()
    assert (h["invested_amount"], h["average_buy_price"]) == ("1015.000000", "101.500000")
    assert client.get(f"/trades/{r.json()['id']}").json()["price_per_unit"] == "100.000000"


# ---- regression coverage for the four release-review defects, against real PostgreSQL ----

from app.services.errors import DuplicateTradeError  # noqa: E402

PG_BODY = {
    "symbol": "RELIANCE", "isin": "ZZ0RELIANCE1", "name": "Reliance Industries", "asset_type": "STOCK", "exchange": "NSE",
    "side": "BUY", "quantity": "10", "price_per_unit": "100",
    "trade_timestamp": "2026-01-01T10:00:00Z", "market_session": "REGULAR",
}


def _client(factory):
    return TestClient(create_app(session_factory=factory, settings=Settings(user_id=USER_A)), raise_server_exceptions=False)


@pytest.mark.parametrize(
    "field,limit",
    [("symbol", 64), ("name", 256), ("broker", 64), ("broker_trade_id", 128), ("order_id", 128), ("notes", 2000)],
)
def test_text_limits_hold_on_real_varchar_columns(factory, field, limit):
    client = _client(factory)
    ok = client.post("/trades", json={**PG_BODY, field: "é" * limit})  # multibyte: limits count characters
    assert ok.status_code == 201 and ok.json()[field] == "é" * limit
    over = client.post("/trades", json={**PG_BODY, field: "x" * (limit + 1)})
    assert over.status_code == 422 and over.json()["detail"]["code"] == "invalid_trade"  # not a database 500


def test_numeric_ceiling_on_real_numeric_columns(factory):
    client = _client(factory)
    rejected = client.post("/trades", json={**PG_BODY, "quantity": "99999999999999", "price_per_unit": "99999999999999"})
    assert rejected.status_code == 422 and rejected.json()["detail"]["code"] == "numeric_limit_exceeded"
    assert client.get("/portfolio/holdings").json() == []
    near = client.post("/trades", json={**PG_BODY, "quantity": "9", "price_per_unit": "99999999999999"})
    assert near.status_code == 201
    (h,) = client.get("/portfolio/holdings").json()
    assert h["invested_amount"] == "899999999999991.000000"
    over = client.post("/trades", json={**PG_BODY, "quantity": "9", "price_per_unit": "99999999999999",
                                        "trade_timestamp": "2026-01-02T10:00:00Z"})
    assert over.status_code == 422 and client.get("/portfolio/holdings").status_code == 200


def test_duplicate_broker_trade_id_is_a_client_error_on_postgres(factory):
    client = _client(factory)
    first = client.post("/trades", json={**PG_BODY, "broker": "zerodha", "broker_trade_id": "T1"})
    again = client.post("/trades", json={**PG_BODY, "broker": "zerodha", "broker_trade_id": "T1"})
    assert first.status_code == 201 and again.status_code == 422
    assert again.json()["detail"]["code"] == "duplicate_trade"
    assert len(client.get("/trades").json()) == 1


def test_unique_index_backstop_and_savepoint_on_postgres(factory, monkeypatch):
    with factory() as s:
        svc = service(s)
        data = dict(broker="zerodha", broker_trade_id="T1")
        first = svc.record(user_id=USER_A, data=ti(**data))
        s.commit()
        real = TradeRepository.original_by_key
        calls = []

        def racing(self, **kw):
            calls.append(kw)
            return None if len(calls) == 1 else real(self, **kw)

        monkeypatch.setattr(TradeRepository, "original_by_key", racing)
        with pytest.raises(DuplicateTradeError) as err:
            svc.record(user_id=USER_A, data=ti(trade_timestamp=T0 + timedelta(hours=1), **data))
        assert err.value.existing_trade_id == first.id and len(calls) == 2
        monkeypatch.undo()
        svc.record(user_id=USER_A, data=ti(trade_timestamp=T0 + timedelta(hours=2)))  # same transaction still usable
        s.commit()
        assert len(svc.list_trades(user_id=USER_A)) == 2


# ---- review round 3, against real PostgreSQL ----

def test_empty_string_broker_duplicate_is_422_on_postgres(factory):
    client = _client(factory)
    first = client.post("/trades", json={**PG_BODY, "broker": "", "broker_trade_id": "T1"})
    again = client.post("/trades", json={**PG_BODY, "broker": "", "broker_trade_id": "T1"})
    assert first.status_code == 201 and again.status_code == 422
    assert again.json()["detail"]["code"] == "duplicate_trade"


LONG_TRAILING_ZEROS = "5." + "0" * 20000  # PostgreSQL refuses this numeric literal (value overflows numeric format)


@pytest.mark.parametrize("field", ["brokerage_fee", "taxes"])
@pytest.mark.parametrize("bad", ["0E+1000000", "0E-21", "1.000000000000000000000", LONG_TRAILING_ZEROS])
def test_extreme_decimal_exponents_never_reach_postgres(factory, field, bad):
    client = _client(factory)
    r = client.post("/trades", json={**PG_BODY, field: bad})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_trade"
    assert client.get("/trades").json() == []


@pytest.mark.parametrize("field", ["symbol", "name", "broker", "broker_trade_id", "order_id", "notes"])
def test_nul_characters_are_a_client_error_on_postgres(factory, field):
    client = _client(factory)
    r = client.post("/trades", json={**PG_BODY, field: "a\u0000b"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_trade"
    assert client.get("/trades").json() == []


def test_postgres_behaviour_the_validation_protects_against(pg_engine):
    """Documents what the database does with the inputs the service now rejects before they reach it."""
    from decimal import Decimal

    from sqlalchemy.exc import DBAPIError

    with pg_engine.connect() as conn:
        with pytest.raises(DBAPIError):  # NUL in text is refused by PostgreSQL (would have been a 500)
            conn.execute(text("SELECT CAST(:v AS text)"), {"v": "a\x00b"})
        conn.rollback()
        with pytest.raises(DBAPIError):  # a non-zero value with thousands of trailing zeros overflows numeric
            conn.execute(text("SELECT CAST(:v AS numeric(20,6))"), {"v": Decimal(LONG_TRAILING_ZEROS)})
        conn.rollback()
        # A zero with a huge exponent is accepted by PostgreSQL itself; the bounded range keeps it out regardless.
        assert conn.execute(text("SELECT CAST(:v AS numeric(20,6))"), {"v": Decimal("0E+1000000")}).scalar() == 0


# ---- final review M1/M2 against real PostgreSQL ----

from app.config import DEFAULT_USER_ID  # noqa: E402


def test_real_startup_path_seeds_the_default_user_and_serves(pg_engine):
    """settings URL -> make_session_factory -> lifespan seeding -> first request, with nothing pre-seeded."""
    with pg_engine.begin() as conn:
        conn.execute(text("TRUNCATE trades, users CASCADE"))
    app = create_app(settings=Settings(database_url=LIVE_URL, user_id=DEFAULT_USER_ID))
    try:
        with TestClient(app) as client:
            assert client.post("/trades", json=PG_BODY).status_code == 201
            assert client.get("/portfolio/holdings").status_code == 200
        with TestClient(app):  # restart is idempotent
            pass
        with pg_engine.connect() as conn:
            assert [r[0] for r in conn.execute(text("SELECT id FROM users"))] == [DEFAULT_USER_ID]
    finally:
        app.state.session_factory.kw["bind"].dispose()


@pytest.mark.parametrize("ts", ["0001-01-01T00:00:00+05:30", "9999-12-31T23:59:59-05:00"])
def test_overflowing_timestamps_are_422_on_postgres(factory, ts):
    r = _client(factory).post("/trades", json={**PG_BODY, "trade_timestamp": ts})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_trade"


WINDOW_EDGES = ["0001-01-02T00:00:00Z", "9999-12-30T23:59:59.999999Z"]
SESSION_TIMEZONES = ["Asia/Calcutta", "America/New_York", "Pacific/Kiritimati", "Pacific/Pago_Pago", "UTC"]  # +14 .. -11


@pytest.mark.parametrize("ts", ["0001-01-01T00:00:00Z", "9999-12-31T23:59:59Z"])
def test_calendar_edge_timestamps_are_422_on_postgres(factory, ts):
    r = _client(factory).post("/trades", json={**PG_BODY, "trade_timestamp": ts})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_trade"


@pytest.mark.parametrize("session_tz", SESSION_TIMEZONES)
def test_window_edge_timestamps_read_back_under_any_session_timezone(factory, pg_engine, session_tz):
    """PostgreSQL returns timestamptz in the session timezone; the window keeps every such conversion representable."""
    writer = _client(factory)
    ids = [writer.post("/trades", json={**PG_BODY, "trade_timestamp": ts, "symbol": f"S{n}"}).json()["id"]
           for n, ts in enumerate(WINDOW_EDGES)]
    zone_engine = create_engine(LIVE_URL, connect_args={"options": f"-c timezone={session_tz}"})
    try:
        reader = _client(sessionmaker(zone_engine, expire_on_commit=False))
        assert reader.get("/trades").status_code == 200
        assert reader.get("/portfolio/holdings").status_code == 200
        assert all(reader.get(f"/trades/{i}").status_code == 200 for i in ids)
    finally:
        zone_engine.dispose()


# ---- Feature 002c: per-user NOWAIT lock and the import service on real PostgreSQL -------------------------------

from pathlib import Path  # noqa: E402

from app.models.import_batch import ImportBatch  # noqa: E402
from app.models.trade import Trade  # noqa: E402
from app.services.errors import LedgerBusyError  # noqa: E402
from app.services.tradebook_import import TradebookImportService  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

_FIXTURE = Path(__file__).parent / "fixtures" / "tradebook_synthetic.csv"


def _importer(session):
    ticks = iter(range(10**6))
    return TradebookImportService.for_session(session, clock=lambda: T0 + timedelta(days=1, seconds=next(ticks)))


def _count(factory, model):
    with factory() as s:
        return s.scalar(select(func.count()).select_from(model))


def test_nowait_lock_refuses_a_second_writer_and_releases_on_rollback(factory):
    holder, other = factory(), factory()
    try:
        service(holder).lock_user(user_id=USER_A)
        with pytest.raises(LedgerBusyError):
            service(other).lock_user(user_id=USER_A)
        other.rollback()
        service(other).lock_user(user_id=USER_B)  # another user's lock is independent
        holder.rollback()
        service(other).lock_user(user_id=USER_A)  # free again after the holder ends its transaction
    finally:
        holder.close()
        other.close()


def test_a_manual_write_is_refused_while_an_import_holds_the_lock_and_vice_versa(factory):
    holder, other = factory(), factory()
    try:
        service(holder).record(user_id=USER_A, data=ti())  # uncommitted: holds the user's lock
        with pytest.raises(LedgerBusyError):
            _importer(other).import_tradebook(user_id=USER_A, file_name="x.csv", content=_FIXTURE.read_bytes())
        other.rollback()
        assert _count(factory, ImportBatch) == 0  # a refused lock creates no batch
        holder.rollback()

        _importer(holder)._ledger.lock_user(user_id=USER_A)  # stands in for an import in its write transaction
        with pytest.raises(LedgerBusyError):
            service(other).record(user_id=USER_A, data=ti())
        other.rollback()
    finally:
        holder.close()
        other.close()
    assert _count(factory, Trade) == 0


def test_import_end_to_end_on_postgres(factory):
    with factory() as s:
        first = _importer(s).import_tradebook(user_id=USER_A, file_name="synthetic.csv", content=_FIXTURE.read_bytes())
    assert (first.total_rows, first.imported, first.duplicates, first.rejected_total) == (7, 6, 0, 1)
    with factory() as s:
        again = _importer(s).import_tradebook(user_id=USER_A, file_name="synthetic.csv", content=_FIXTURE.read_bytes())
    assert (again.imported, again.duplicates, again.rejected_total) == (0, 6, 1)
    with factory() as s:
        rows = s.scalars(select(Trade).where(Trade.user_id == USER_A)).all()
        assert len(rows) == 6 and {t.import_batch_id for t in rows} == {first.import_batch_id}
        assert all(t.source is TradeSource.IMPORT and t.charges_provided is False and t.name is None for t in rows)
        assert s.scalar(select(func.count()).select_from(ImportBatch).where(ImportBatch.user_id == USER_A)) == 2


def test_a_failed_import_leaves_no_batch_and_no_rows_on_postgres(factory, monkeypatch):
    real = TradeRepository.add
    calls = []

    def fail_on_third(self, **kw):
        calls.append(1)
        if len(calls) == 3:
            raise RuntimeError("boom")
        return real(self, **kw)

    monkeypatch.setattr(TradeRepository, "add", fail_on_third)
    with factory() as s, pytest.raises(RuntimeError, match="boom"):
        _importer(s).import_tradebook(user_id=USER_A, file_name="synthetic.csv", content=_FIXTURE.read_bytes())
    assert _count(factory, ImportBatch) == 0 and _count(factory, Trade) == 0


# ---- Feature 002 routes on real PostgreSQL (live only; skipped without ALTERFOLIO_TEST_DATABASE_URL) -------------------

from tests.test_tradebook_import import csv_bytes as _csv_bytes, r as _csv_row  # noqa: E402


def _post_csv(client, content):
    return client.post("/imports/tradebook", files={"file": ("tradebook.csv", content, "text/csv")})


def test_import_route_end_to_end_on_postgres_including_the_threadpool_session(factory):
    client = _client(factory)
    first = _post_csv(client, _csv_bytes(_csv_row(1, qty="10", price="100"), _csv_row(2, qty="5", exchange="BSE", price="110")))
    assert first.status_code == 201 and first.json()["imported"] == 2
    again = _post_csv(client, _csv_bytes(_csv_row(1, qty="10", price="100"), _csv_row(2, qty="5", exchange="BSE", price="110")))
    assert again.status_code == 201 and (again.json()["imported"], again.json()["duplicates"]) == (0, 2)
    (h,) = client.get("/portfolio/holdings").json()
    assert (h["quantity"], h["cost_basis_complete"], len(h["listings"])) == ("15.000000", False, 2)
    rows = client.get("/trades").json()
    assert {t["source"] for t in rows} == {"IMPORT"} and {t["name"] for t in rows} == {None}
    assert _count(factory, ImportBatch) == 2


def test_import_route_is_409_while_another_transaction_holds_the_user_lock(factory):
    holder = factory()
    try:
        service(holder).lock_user(user_id=USER_A)
        resp = _post_csv(_client(factory), _csv_bytes(_csv_row(1)))
        assert resp.status_code == 409 and resp.json()["detail"]["code"] == "ledger_busy"
    finally:
        holder.rollback()
        holder.close()
    assert _count(factory, ImportBatch) == 0 and _count(factory, Trade) == 0
    assert _post_csv(_client(factory), _csv_bytes(_csv_row(1))).status_code == 201  # free again


def test_manual_write_routes_are_409_while_another_transaction_holds_the_user_lock(factory):
    client = _client(factory)
    created = client.post("/trades", json=PG_BODY).json()
    holder = factory()
    try:
        service(holder).lock_user(user_id=USER_A)
        assert client.post("/trades", json=PG_BODY).status_code == 409
        assert client.post(f"/trades/{created['id']}/void").status_code == 409
        correction = {k: v for k, v in PG_BODY.items()}
        assert client.post(f"/trades/{created['id']}/correct", json=correction).status_code == 409
    finally:
        holder.rollback()
        holder.close()
    assert len(client.get("/trades").json()) == 1


def test_void_of_an_imported_row_on_postgres(factory):
    client = _client(factory)
    assert _post_csv(client, _csv_bytes(_csv_row(1))).status_code == 201
    (imported,) = client.get("/trades").json()
    void = client.post(f"/trades/{imported['id']}/void")
    assert void.status_code == 201
    assert (void.json()["isin"], void.json()["charges_provided"], void.json()["import_batch_id"]) == ("ZZ0ALPHA0001", False, None)


def test_correcting_an_imported_row_needs_stated_fees_on_postgres(factory):
    client = _client(factory)
    assert _post_csv(client, _csv_bytes(_csv_row(1))).status_code == 201
    (imported,) = client.get("/trades").json()
    body = {k: PG_BODY[k] for k in ("symbol", "exchange", "side", "quantity", "price_per_unit", "trade_timestamp")}
    body["isin"] = "ZZ0ALPHA0001"
    url = f"/trades/{imported['id']}/correct"
    for fees in ({}, {"brokerage_fee": "0"}, {"taxes": None, "brokerage_fee": "0"}, {"brokerage_fee": None, "taxes": "0"}):
        assert client.post(url, json={**body, **fees}).status_code == 422
    ok = client.post(url, json={**body, "brokerage_fee": "0", "taxes": "0"})
    assert ok.status_code == 201
    assert (ok.json()["charges_provided"], ok.json()["source"], ok.json()["import_batch_id"]) == (True, "MANUAL", None)
    assert len(client.get("/trades").json()) == 2
