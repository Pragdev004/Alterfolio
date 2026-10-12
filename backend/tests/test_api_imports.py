"""POST /imports/tradebook (Feature 002): transport, contract, file-level failures, 409, provenance, isolation.

Runs on in-memory SQLite. A patched lock proves only the 409 mapping, not PostgreSQL locking (see the live tests).
"""
import ast
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from app.domain import limits
from app.models.import_batch import ImportBatch
from app.models.trade import Trade
from app.repositories.trade_repository import TradeRepository
from app.schemas.imports import ImportResultOut
from tests.conftest import USER_A, USER_B
from tests.test_api import app, as_user, body, client  # noqa: F401  (fixtures)
from tests.test_tradebook_import import ALPHA, BETA, FIXTURE, csv_bytes, r

URL = "/imports/tradebook"


def post_csv(client, content: bytes, name: str = "tradebook.csv", content_type: str = "text/csv"):
    return client.post(URL, files={"file": (name, content, content_type)})


def raw_multipart(parts: list[tuple[str, str | None, bytes]], boundary: str = "XBOUNDARY") -> dict:
    """(field name, filename or None, content) triples as a hand-built multipart request."""
    out = b""
    for field, filename, content in parts:
        disposition = f'form-data; name="{field}"' + (f'; filename="{filename}"' if filename is not None else "")
        out += f"--{boundary}\r\nContent-Disposition: {disposition}\r\n\r\n".encode() + content + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return {"content": out, "headers": {"content-type": f"multipart/form-data; boundary={boundary}"}}


def counts(session):
    session.expire_all()
    return (
        session.scalar(select(func.count()).select_from(ImportBatch)),
        session.scalar(select(func.count()).select_from(Trade)),
    )


# ---- contract ----------------------------------------------------------------------------------------------------

def test_a_valid_upload_is_201_with_the_import_result_contract(client, session):
    resp = post_csv(client, FIXTURE.read_bytes(), name="tradebook_synthetic.csv")
    assert resp.status_code == 201
    out = resp.json()
    assert set(out) == {
        "import_batch_id", "file_name", "file_sha256", "total_rows", "imported", "duplicates", "rejected_total",
        "rejected", "quarantined_isins", "fees_taxes_provided",
    }
    assert (out["file_name"], out["total_rows"], out["imported"], out["duplicates"], out["rejected_total"]) == (
        "tradebook_synthetic.csv", 7, 6, 0, 1,
    )
    assert out["rejected"] == [{"row": 8, "code": "invalid_side", "message": out["rejected"][0]["message"]}]
    assert out["quarantined_isins"] == [] and out["fees_taxes_provided"] is False
    assert len(out["file_sha256"]) == 64
    assert counts(session) == (1, 6)


def test_the_counts_always_add_up(client):
    out = post_csv(client, csv_bytes(r(1), r(1), r(2, side="hold"), r(3, side="sell", qty="99"))).json()
    assert out["imported"] + out["duplicates"] + out["rejected_total"] == out["total_rows"]
    assert (out["imported"], out["duplicates"], out["rejected_total"]) == (1, 1, 2)


def test_reimport_is_201_with_only_duplicates_and_still_creates_a_batch(client, session):
    content = csv_bytes(r(1), r(2, ts="2020-03-02T09:31:00"))
    first = post_csv(client, content).json()
    again = post_csv(client, content)
    assert again.status_code == 201
    out = again.json()
    assert (out["imported"], out["duplicates"], out["rejected_total"]) == (0, 2, 0)
    assert out["import_batch_id"] != first["import_batch_id"] and out["file_sha256"] == first["file_sha256"]
    assert counts(session) == (2, 2)


def test_an_all_rejected_upload_is_still_201_and_creates_a_batch(client, session):
    resp = post_csv(client, csv_bytes(r(1, side="hold"), r(2, side="hold")))
    assert resp.status_code == 201 and resp.json()["rejected_total"] == 2 and resp.json()["imported"] == 0
    assert counts(session) == (1, 0)


def test_only_the_first_200_rejections_are_listed(client):
    out = post_csv(client, csv_bytes(*[r(i, side="hold") for i in range(1, 251)])).json()
    assert out["rejected_total"] == 250 and len(out["rejected"]) == limits.MAX_LISTED_REJECTIONS == 200
    assert [x["row"] for x in out["rejected"]] == list(range(2, 202))


def test_oversell_and_quarantine_are_reported_through_the_route(client):
    out = post_csv(
        client,
        csv_bytes(
            r(1, qty="5", ts="2020-03-02T09:00:00"),
            r(2, side="sell", qty="6", ts="2020-03-02T10:00:00"),
            r(3, qty="1", ts="2020-03-02T11:00:00"),
        ),
    ).json()
    assert [(x["row"], x["code"]) for x in out["rejected"]] == [(3, "oversell"), (4, "after_oversell")]
    assert out["quarantined_isins"] == [ALPHA]


def test_the_same_isin_on_nse_and_bse_is_one_position_for_oversell(client):
    out = post_csv(
        client, csv_bytes(r(1, qty="10"), r(2, side="sell", qty="10", exchange="BSE", ts="2020-03-03T10:00:00"))
    ).json()
    assert (out["imported"], out["rejected_total"]) == (2, 0)


def test_the_result_schema_refuses_counts_that_do_not_add_up():
    good = dict(
        import_batch_id="00000000-0000-0000-0000-000000000001", file_name="a.csv", file_sha256="0" * 64, total_rows=3,
        imported=1, duplicates=1, rejected_total=1, rejected=[], quarantined_isins=[], fees_taxes_provided=False,
    )
    ImportResultOut(**good)
    with pytest.raises(ValidationError):
        ImportResultOut(**{**good, "imported": 2})


# ---- file-level failures: 422 invalid_import_file, nothing persisted ------------------------------------------------

BAD_FILES = {
    "empty": b"",
    "header-only": csv_bytes()[: csv_bytes().index(b"\n") + 1],
    "wrong-header": b"symbol,isin\nA,B\n",
    "not-utf8": b"\xff\xfe\x00 not text",
    "cell-count": csv_bytes(r(1)).replace(b",NSE,", b",NSE,extra,"),
    "over-row-cap": csv_bytes(*[r(i) for i in range(1, limits.MAX_IMPORT_ROWS + 2)]),
}


@pytest.mark.parametrize("name", sorted(BAD_FILES))
def test_a_bad_file_is_422_and_creates_nothing(client, session, name):
    resp = post_csv(client, BAD_FILES[name])
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "invalid_import_file"
    assert counts(session) == (0, 0)


def test_a_file_over_2_mib_is_422_while_exactly_2_mib_is_read_to_the_parser(client, session):
    over = post_csv(client, b"x" * (limits.MAX_IMPORT_FILE_BYTES + 1))
    assert over.status_code == 422 and over.json()["detail"]["code"] == "invalid_import_file"
    size_message = f"larger than {limits.MAX_IMPORT_FILE_BYTES} bytes"
    assert size_message in over.json()["detail"]["message"]
    at_limit = post_csv(client, b"x" * limits.MAX_IMPORT_FILE_BYTES)  # accepted by the reader, rejected by the parser
    assert at_limit.status_code == 422 and size_message not in at_limit.json()["detail"]["message"]
    assert counts(session) == (0, 0)


TRANSPORT_FAILURES = {
    "no-parts": raw_multipart([]),
    "wrong-field-name": raw_multipart([("upload", "a.csv", csv_bytes(r(1)))]),
    "extra-form-field": raw_multipart([("file", "a.csv", csv_bytes(r(1))), ("note", None, b"hi")]),
    "two-file-parts": raw_multipart([("file", "a.csv", csv_bytes(r(1))), ("file", "b.csv", csv_bytes(r(2)))]),
    "no-filename": raw_multipart([("file", None, csv_bytes(r(1)))]),
    "empty-filename": raw_multipart([("file", "", csv_bytes(r(1)))]),
    "dot-filename": raw_multipart([("file", "..", csv_bytes(r(1)))]),
    "malformed-body": {"content": b"not multipart at all", "headers": {"content-type": "multipart/form-data; boundary=zz"}},
    "no-boundary": {"content": b"x", "headers": {"content-type": "multipart/form-data"}},
    "json-instead": {"content": b"{}", "headers": {"content-type": "application/json"}},
}


@pytest.mark.parametrize("name", sorted(TRANSPORT_FAILURES))
def test_a_transport_failure_is_422_invalid_import_file_and_creates_nothing(client, session, name):
    resp = client.post(URL, **TRANSPORT_FAILURES[name])
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "invalid_import_file"
    assert counts(session) == (0, 0)


def test_the_part_content_type_is_not_checked(client):
    assert post_csv(client, csv_bytes(r(1)), content_type="application/octet-stream").status_code == 201


def test_a_path_in_the_filename_is_reduced_to_its_base_name(client):
    for raw, expected in (("C:\\Users\\me\\tradebook.csv", "tradebook.csv"), ("/tmp/x/tradebook.csv", "tradebook.csv")):
        assert post_csv(client, csv_bytes(r(1)), name=raw).json()["file_name"] == expected


# ---- ledger_busy -> 409 --------------------------------------------------------------------------------------------

def _hold_the_lock(monkeypatch):
    class Orig(Exception):
        sqlstate = "55P03"

    def refuse(self, **kw):
        raise OperationalError("SELECT ... FOR UPDATE NOWAIT", {}, Orig("lock not available"))

    monkeypatch.setattr(TradeRepository, "lock_user_ledger", refuse)


def test_a_held_lock_is_409_ledger_busy_and_creates_no_batch(client, session, monkeypatch):
    _hold_the_lock(monkeypatch)
    resp = post_csv(client, csv_bytes(r(1)))
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "ledger_busy"
    assert counts(session) == (0, 0)


def test_a_bad_file_is_still_422_not_409_because_parsing_precedes_the_lock(client, monkeypatch):
    _hold_the_lock(monkeypatch)
    resp = post_csv(client, b"")
    assert resp.status_code == 422 and resp.json()["detail"]["code"] == "invalid_import_file"


def test_every_manual_write_route_maps_a_held_lock_to_409(client, monkeypatch):
    created = client.post("/trades", json=body()).json()
    _hold_the_lock(monkeypatch)
    assert client.post("/trades", json=body()).status_code == 409
    correction = {k: v for k, v in body().items()}
    assert client.post(f"/trades/{created['id']}/correct", json=correction).status_code == 409
    assert client.post(f"/trades/{created['id']}/void").status_code == 409
    assert len(client.get("/trades").json()) == 1


# ---- provenance, serialization and isolation -----------------------------------------------------------------------

def test_imported_rows_serialize_with_null_descriptive_fields_and_string_decimals(client):
    batch = post_csv(client, csv_bytes(r(1, qty="10.5", price="100.25", order_id="777"))).json()
    (trade,) = client.get("/trades").json()
    assert trade["source"] == "IMPORT" and trade["import_batch_id"] == batch["import_batch_id"]
    assert trade["isin"] == ALPHA and trade["charges_provided"] is False
    assert (trade["name"], trade["asset_type"], trade["market_session"]) == (None, None, None)
    assert (trade["quantity"], trade["price_per_unit"], trade["brokerage_fee"], trade["taxes"]) == (
        "10.500000", "100.250000", "0.000000", "0.000000",
    )
    assert (trade["broker"], trade["broker_trade_id"], trade["order_id"]) == ("ZERODHA", "1", "777")
    assert trade["trade_timestamp"].startswith("2020-03-02T04:00:00")  # 09:30 IST
    one = client.get(f"/trades/{trade['id']}")
    assert one.status_code == 200 and one.json() == trade


def test_imported_and_manual_rows_list_together(client):
    post_csv(client, csv_bytes(r(1)))
    client.post("/trades", json=body())
    rows = client.get("/trades").json()
    assert {t["source"] for t in rows} == {"IMPORT", "MANUAL"}
    assert [t["import_batch_id"] is None for t in rows if t["source"] == "MANUAL"] == [True]


def test_holdings_after_an_import_are_per_isin_with_incomplete_cost_basis(client):
    post_csv(
        client,
        csv_bytes(
            r(1, qty="1", price="10", ts="2020-03-02T09:00:00"),
            r(2, qty="2", price="20", exchange="BSE", ts="2020-03-02T10:00:00"),
            r(3, isin=BETA, symbol="BETACO", qty="1", price="5", ts="2020-03-02T11:00:00"),
        ),
    )
    alpha, beta = client.get("/portfolio/holdings").json()
    assert alpha == {
        "isin": ALPHA, "listings": [{"symbol": "ALPHACO", "exchange": "BSE"}, {"symbol": "ALPHACO", "exchange": "NSE"}],
        "name": None, "quantity": "3.000000", "average_buy_price": "16.666667", "invested_amount": "50.000000",
        "cost_basis_complete": False,
    }
    assert beta["isin"] == BETA and beta["cost_basis_complete"] is False


def test_another_users_import_is_independent_and_invisible(client, app):
    content = csv_bytes(r(1), r(2, side="sell", qty="4", ts="2020-03-03T10:00:00"))
    assert post_csv(client, content).json()["imported"] == 2
    as_user(app, USER_B)
    assert client.get("/trades").json() == [] and client.get("/portfolio/holdings").json() == []
    again = post_csv(client, content).json()
    assert (again["imported"], again["duplicates"]) == (2, 0)
    assert len(client.get("/trades").json()) == 2
    as_user(app, USER_A)
    assert len(client.get("/trades").json()) == 2


def test_a_second_users_sell_is_not_covered_by_the_first_users_buy(client, app):
    post_csv(client, csv_bytes(r(1, qty="10")))
    as_user(app, USER_B)
    out = post_csv(client, csv_bytes(r(2, side="sell", qty="1", ts="2020-03-03T10:00:00"))).json()
    assert [(x["code"]) for x in out["rejected"]] == ["oversell"]


# ---- the route stays thin --------------------------------------------------------------------------------------------

def test_the_route_streams_through_the_reader_and_never_uses_uploadfile():
    path = Path(__file__).resolve().parent.parent / "app" / "api" / "routes" / "imports.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "read_tradebook_upload" in names
    assert not names & {"UploadFile", "File", "Form"}
