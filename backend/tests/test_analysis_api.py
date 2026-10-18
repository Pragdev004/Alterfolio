"""Feature 013a: read-only analysis endpoints (spec 013a, tests T1-T9b, T12, T13). Offline: fake bars, in-memory ledger."""

import re
import socket
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from analysis_helpers import (
    D_ASOF, NOW, TRADED, TRADED_ISIN, UNIVERSE, FakeBars, add_trade, config, seed_round_trips, walk_floats,
)
from conftest import USER_A, USER_B
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.analyst.llm import FakeLLM, TemplateLLM
from app.analyst.types import Draft
from app.api.deps import get_current_user_id
from app.api.main import create_app
from app.config import Settings
from app.domain.enums import TradeSide
from app.repositories.trade_repository import TradeRepository
from app.services.portfolio_analysis import PortfolioAnalysisService

ASOF = D_ASOF.isoformat()
NOTE = "Same-sector or same-universe alternatives, not a prediction."
CANONICAL = re.compile(r"^-?\d+(\.\d+)?$")
RAW_CODE = re.compile(r"\b[A-Z]{2,}(?:_[A-Z]+)+\b")  # an enum code such as NO_MEMBERSHIP: never primary text
ENDPOINTS = ("trips", "regimes", "biases")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):  # T13
    original = socket.socket.connect

    def guarded(self, address, *a, **k):
        if not (isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1", "localhost")):
            raise AssertionError(f"network access in a test: {address!r}")
        return original(self, address, *a, **k)
    monkeypatch.setattr(socket.socket, "connect", guarded)


def make_app(engine, user=USER_A, provider=None, llm=None, **cfg):
    return create_app(session_factory=sessionmaker(engine, expire_on_commit=False), settings=Settings(user_id=user),
                      clock=lambda: NOW, history_provider=provider or FakeBars(), analysis_config=config(**cfg), analyst_llm=llm)


def get(client, path, as_of=ASOF, **params):
    if as_of is not None:
        params["as_of"] = as_of
    return client.get(f"/api/analysis/{path}", params=params)


def walk_numbers(obj, path="root"):
    """Yield every number object ({value, display, unavailable_reason}) in a JSON body."""
    if isinstance(obj, dict):
        if {"value", "display", "unavailable_reason"} <= set(obj):
            yield path, obj
        for k, v in obj.items():
            yield from walk_numbers(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_numbers(v, f"{path}[{i}]")


def text_key(key: str) -> str | None:
    if key == "reason":
        return "reason_text"
    return key.replace("unavailable_reason", "reason_text") if key.endswith("unavailable_reason") else None


def assert_reasons_have_plain_text(obj, path="root"):
    """Every non-null reason string has a plain-English sibling that is not an enum code."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            tk = text_key(k)
            if tk is not None and isinstance(v, str) and v:
                assert obj.get(tk) and not RAW_CODE.search(obj[tk]), (path, k, obj.get(tk))
                assert obj[tk] != v, (path, k)
        for k, v in obj.items():
            assert_reasons_have_plain_text(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            assert_reasons_have_plain_text(v, f"{path}[{i}]")


def assert_numbers_honest(body):
    assert_reasons_have_plain_text(body)
    count = 0
    for path, n in walk_numbers(body):
        count += 1
        if n["value"] is None:
            assert n["display"] == "Unavailable" and n["unavailable_reason"], path  # T6/T7: missing is never 0 or blank
            assert n["reason_text"] and not RAW_CODE.search(n["reason_text"]), (path, n["reason_text"])
        else:
            assert CANONICAL.match(n["value"]), (path, n["value"])  # T8: plain decimal text, no exponent, no NaN
            assert n["display"] not in ("", "Unavailable") and n["unavailable_reason"] is None, path
            assert n["reason_text"] is None, path
    assert not list(walk_floats(body))  # T8
    return count


@pytest.fixture
def seeded(session):
    seed_round_trips(session, USER_A, 14)
    return session


# --- T3 sealed / meta ---------------------------------------------------------------------------------------------

def test_t3_meta_reports_latest_sealed_day_thresholds_and_note(engine, seeded):
    m = TestClient(make_app(engine)).get("/api/analysis/meta").json()
    assert m["latest_sealed_as_of"] == {"iso": "2026-11-30", "display": "30 Nov 2026"}
    assert m["today_ist"] == {"iso": "2026-12-01", "display": "1 Dec 2026"}
    assert m["alternatives_note"] == NOTE and m["limitations"]
    t = m["thresholds"]
    assert t["luck_min_trips"]["value"] == "10" and t["luck_min_trips"]["display"] == "10"
    assert t["regime_min_trips_per_regime"]["value"] == "3"  # the test config's RegimeParameters
    assert t["bias_min_round_trips"]["value"] == "10"
    assert m["last_bar_date"] == {"iso": "2026-11-30", "display": "30 Nov 2026"}
    assert_numbers_honest(m)


def test_t3_meta_last_bar_date_unavailable_when_no_bars(engine, seeded):
    m = TestClient(make_app(engine, provider=FakeBars(missing=frozenset({TRADED, *[c.instrument for c in UNIVERSE]})))
                   ).get("/api/analysis/meta").json()
    assert m["last_bar_date"] is None and m["last_bar_date_unavailable_reason"]


def test_t3_omitted_as_of_is_the_latest_sealed_day_and_never_today(engine, seeded):
    client = TestClient(make_app(engine))
    r = get(client, "trips", as_of=None)
    assert r.status_code == 200
    assert r.json()["as_of"]["iso"] == "2026-11-30" and r.json()["as_of_defaulted"] is True
    assert get(client, "trips").json()["as_of_defaulted"] is False
    for path in ENDPOINTS:
        for bad in ("2026-12-01", "2026-12-02"):  # today (IST) and the future
            r = get(client, path, as_of=bad)
            assert r.status_code == 422 and r.json()["detail"]["code"] == "as_of_not_sealed"
        assert get(client, path, as_of="not-a-date").status_code == 422


# --- shape, labels, sample ---------------------------------------------------------------------------------------

def test_trips_list_shape_label_and_sample(engine, seeded):
    b = get(TestClient(make_app(engine)), "trips").json()
    assert b["as_of"]["iso"] == ASOF and b["as_of_defaulted"] is False
    assert b["summary"]["trip_count"] == 14
    alt = b["summary"]["ALT"]
    assert alt["sample"]["needed"] == 10 and alt["sample"]["have"] == alt["trips_used"] and alt["sample"]["enough"] is True
    assert alt["sample"]["text"] == ""
    assert len(b["trips"]) == 14
    keys = [(t["open_session"]["iso"], t["close_session"]["iso"], t["trip_id"]) for t in b["trips"]]
    assert keys == sorted(keys)
    t = b["trips"][0]
    assert {"trip_id", "symbol", "exchange", "open_session", "close_session", "evaluated", "actual_return",
            "actual_return_basis", "alternatives_kind", "alternatives_label", "alt", "nifty", "survivorship_flag", "regime",
            "unavailable_reason"} <= set(t)
    assert t["actual_return_basis"] == "LEDGER_PRICES_FEES_EXCLUDED" and t["open_session"]["display"]
    assert t["alternatives_kind"] == "SAME_UNIVERSE" and t["alternatives_label"] == "Same-universe alternatives"
    assert b["caveats"] and b["excluded_listings"] == []
    assert_numbers_honest(b)


def test_t9_sector_alternatives_are_labelled_by_how_they_were_chosen(engine, seeded):
    cfg = {"alternatives": {TRADED_ISIN: (UNIVERSE, f"alternatives: NIFTY BANK ({len(UNIVERSE)})")}}
    t = get(TestClient(make_app(engine, **cfg)), "trips").json()["trips"][0]
    assert t["alternatives_kind"] == "SAME_SECTOR"
    assert t["alternatives_label"] == f"Same-sector alternatives (NIFTY BANK, {len(UNIVERSE)})"


def test_alternatives_presentation_function():
    from app.services.analysis_view import alternatives_presentation as ap
    assert ap("alternatives: static universe") == ("SAME_UNIVERSE", "Same-universe alternatives")
    assert ap("alternatives: static universe (fallback)") == ("SAME_UNIVERSE", "Same-universe alternatives")
    assert ap("alternatives: NIFTY BANK (3)") == ("SAME_SECTOR", "Same-sector alternatives (NIFTY BANK, 3)")
    assert ap("alternatives: industry Fin (3)") == ("SAME_SECTOR", "Same-sector alternatives (industry Fin, 3)")
    assert ap(None) == ("SAME_UNIVERSE", "Same-universe alternatives")


def test_trip_detail_has_picks_and_unknown_id_is_404(engine, seeded):
    client = TestClient(make_app(engine))
    first = get(client, "trips").json()["trips"][0]
    d = get(client, f"trips/{first['trip_id']}")
    assert d.status_code == 200
    body = d.json()
    assert body["trip"]["trip_id"] == first["trip_id"]
    assert {"picks", "exclusions", "zero_variance_features"} <= set(body["trip"])
    assert all({"rank", "symbol", "exchange", "return_ratio"} <= set(p) for p in body["trip"]["picks"])
    assert "distance" not in str(body["trip"]["picks"])
    assert_numbers_honest(body)
    miss = get(client, "trips/no-such-trip")
    assert miss.status_code == 404 and miss.json()["detail"]["code"] == "analysis_trip_not_found"


def test_regimes_always_three_blocks_with_sample_text(engine, seeded):
    b = get(TestClient(make_app(engine)), "regimes").json()
    assert [x["regime"] for x in b["blocks"]] == ["LOW", "NORMAL", "HIGH"]
    for blk in b["blocks"]:
        assert blk["sample"]["needed"] == 3 and blk["sample"]["have"] == blk["trip_count"]
        assert blk["sample"]["enough"] == (blk["trip_count"] >= 3)
        if not blk["sample"]["enough"]:
            assert blk["sample"]["text"] == f"{blk['trip_count']} trips · 3 needed"
    assert b["limitations"]
    assert_numbers_honest(b)


def test_biases_three_kinds_profile_and_unitless_metrics(engine, seeded):
    b = get(TestClient(make_app(engine)), "biases").json()
    assert [x["kind"] for x in b["biases"]] == ["DISPOSITION", "CHASING", "OVERTRADING"]
    for x in b["biases"]:
        assert {"cost_inr", "gross_cost_inr", "fees_known", "fee_status", "unknown_fee_trade_count", "exclusions",
                "details"} <= set(x)
    p = b["profile"]
    assert p["archetype_id"] or p["unavailable_reason"]
    for m in p["supporting_metrics"]:
        assert m["unit"] == "unitless" and m["display"] == m["value"]  # units are not declared: never guessed
    assert b["sample"]["needed"] == 10 and b["sample"]["have"] == 14
    assert_numbers_honest(b)


# --- T7 Unavailable fixtures -----------------------------------------------------------------------------------------

def test_t7_nine_trips_say_nine_of_ten_and_no_interval(engine, session):
    seed_round_trips(session, USER_A, 9)
    b = get(TestClient(make_app(engine)), "trips").json()
    alt = b["summary"]["ALT"]
    assert alt["sample"] == {"have": 9, "needed": 10, "text": "9 trips · 10 needed", "enough": False}
    assert alt["ci_lower"]["value"] is None and alt["ci_lower"]["display"] == "Unavailable"
    assert "INSUFFICIENT_TRIPS" in alt["ci_lower"]["unavailable_reason"]
    assert_numbers_honest(b)


def test_t7_no_trades_is_200_with_unavailable_everywhere(engine, session):
    client = TestClient(make_app(engine))
    for path in ENDPOINTS:
        r = get(client, path)
        assert r.status_code == 200
        assert_numbers_honest(r.json())
    t = get(client, "trips").json()
    assert t["trips"] == [] and t["summary"]["ALT"]["sample"]["have"] is None  # nothing ran: Unavailable, never "0 of 10"
    assert t["summary"]["ALT"]["sample"]["text"] == "Unavailable" and t["summary"]["ALT"]["trips_used"] is None
    assert all(x["cost_inr"]["display"] == "Unavailable" for x in get(client, "biases").json()["biases"])


def test_t7_t9_excluded_listing_trips_are_listed_with_reason_not_hidden(engine, seeded):
    b = get(TestClient(make_app(engine, provider=FakeBars(missing=frozenset({TRADED})))), "trips").json()
    (ex,) = b["excluded_listings"]
    assert (ex["symbol"], ex["exchange"], ex["trips"]) == ("TEST1", "NSE", 14) and "no market-data series" in ex["reason"]
    assert len(b["trips"]) == 14
    for t in b["trips"]:
        assert t["evaluated"] is False and t["actual_return"]["value"] is None
        assert t["actual_return"]["display"] == "Unavailable" and "excluded" in t["actual_return"]["unavailable_reason"]
        assert t["unavailable_reason"] and t["regime"]["regime"] is None and t["regime"]["reason"]
    assert_numbers_honest(b)


def test_t7_undeclared_corporate_action_coverage_gives_reasons_not_zeros(engine, seeded):
    client = TestClient(make_app(engine, corporate_action_reviewed=None))
    for path in ENDPOINTS:
        assert_numbers_honest(get(client, path).json())
    assert all(t["alt"] is None or t["alt"]["percentile"]["value"] is None for t in get(client, "trips").json()["trips"])


# --- T1 isolation, T2 point-in-time, T4 parity ----------------------------------------------------------------------

def test_t1_routes_are_user_isolated(engine, seeded):
    provider = FakeBars()
    app = make_app(engine, provider=provider)
    client = TestClient(app)
    a_trips = get(client, "trips").json()
    a_id = a_trips["trips"][0]["trip_id"]
    assert a_trips["summary"]["trip_count"] == 14
    calls_before = sum(1 for inst, *_ in provider.calls if inst == TRADED)
    app.dependency_overrides[get_current_user_id] = lambda: USER_B
    b_trips = get(client, "trips").json()
    assert b_trips["trips"] == [] and b_trips["summary"]["trip_count"] is None  # no ledger: Unavailable, not 0
    assert get(client, f"trips/{a_id}").status_code == 404  # A's trip id is unknown to B
    assert all(x["cost_inr"]["value"] is None for x in get(client, "biases").json()["biases"])
    assert all(b["trip_ids"] == [] for b in get(client, "regimes").json()["blocks"])
    assert TestClient(app).get("/api/analysis/meta").json()["thresholds"]  # meta holds no user data
    assert sum(1 for inst, *_ in provider.calls if inst == TRADED) == calls_before  # B's request never fetched A's listing
    assert TestClient(app).get("/api/analysis/trips", params={"as_of": ASOF, "user_id": str(USER_A)}).json()["trips"] == []


def test_t2_nothing_after_as_of_changes_any_response(engine, seeded):
    base = {p: get(TestClient(make_app(engine)), p).json() for p in ENDPOINTS}
    add_trade(seeded, USER_A, TradeSide.BUY, date(2026, 10, 10))
    add_trade(seeded, USER_A, TradeSide.SELL, date(2026, 10, 14))
    seeded.commit()
    later = {p: get(TestClient(make_app(engine, provider=FakeBars(perturb_after=D_ASOF))), p).json() for p in ENDPOINTS}
    assert later == base


def _facts(engine, provider=None):
    with sessionmaker(engine)() as s:
        svc = PortfolioAnalysisService(repo=TradeRepository(s), provider=provider or FakeBars(), clock=lambda: NOW, config=config())
        return svc.analyse(USER_A, D_ASOF)


def _num(n):
    return "Unavailable" if n["value"] is None else n["value"]


def test_t4_every_endpoint_number_equals_the_matching_fact(engine, seeded):
    facts = {f.name: f.value for f in _facts(engine).facts}
    client = TestClient(make_app(engine))
    trips, regimes, biases = (get(client, p).json() for p in ENDPOINTS)
    checked = 0
    for base in ("ALT", "NIFTY"):
        s = trips["summary"][base]
        for n in ("mean_excess", "mean_percentile", "ci_lower", "ci_upper"):
            assert _num(s[n]) == facts[f"luck.{base}.{n}"], (base, n)
            checked += 1
        assert str(s["trips_used"]) == facts[f"luck.{base}.trips_used"]
        assert str(s["trips_evaluated"]) == facts[f"luck.{base}.trips_evaluated"]
    assert str(trips["summary"]["trip_count"]) == facts["luck.trip_count"]
    for x in biases["biases"]:
        assert _num(x["cost_inr"]) == facts[f"bias.{x['kind']}.cost_inr"]
        checked += 1
    assert str(regimes["round_trip_count"]) == facts["regime.round_trip_count"]
    for blk in regimes["blocks"]:
        assert str(blk["trip_count"]) == facts[f"regime.{blk['regime']}.trip_count"]
        for x in blk["bias"] or []:
            assert _num(x["cost_inr"]) == facts[f"regime.{blk['regime']}.bias.{x['kind']}.cost_inr"]
            checked += 1
    last = max(trips["trips"], key=lambda t: (t["open_session"]["iso"], t["close_session"]["iso"], t["trip_id"]))
    assert _num(last["actual_return"]) == facts["luck.last_trip.actual_return"]
    assert checked > 15


def test_t4_counts_are_null_not_zero_when_the_analysis_did_not_run(engine, seeded):
    provider = FakeBars(missing=frozenset({TRADED}))
    facts = {f.name: f.value for f in _facts(engine, provider).facts}
    client = TestClient(make_app(engine, provider=provider))
    trips, regimes, biases = (get(client, p).json() for p in ENDPOINTS)
    for base in ("ALT", "NIFTY"):
        assert facts[f"luck.{base}.trips_used"] == "Unavailable" and trips["summary"][base]["trips_used"] is None
        assert trips["summary"][base]["trips_evaluated"] is None and trips["summary"][base]["sample"]["have"] is None
    for blk in regimes["blocks"]:
        assert facts[f"regime.{blk['regime']}.trip_count"] == "Unavailable"
        assert blk["trip_count"] is None and blk["sample"]["have"] is None and blk["sample"]["text"] == "Unavailable"
    assert facts["bias.OVERTRADING.unknown_fee_trade_count"] == "Unavailable"
    assert all(x["unknown_fee_trade_count"] is None for x in biases["biases"])


def test_t4_analyse_is_unchanged_by_analyse_detail(engine, seeded):
    with sessionmaker(engine)() as s:
        svc = PortfolioAnalysisService(repo=TradeRepository(s), provider=FakeBars(), clock=lambda: NOW, config=config())
        assert svc.analyse_detail(USER_A, D_ASOF).facts.to_dict() == svc.analyse(USER_A, D_ASOF).to_dict()


def test_t5_trip_ids_agree_between_luck_and_regime(engine, seeded):
    client = TestClient(make_app(engine))
    trips = get(client, "trips").json()["trips"]
    ids = {t["trip_id"] for t in trips}
    blocks = get(client, "regimes").json()["blocks"]
    in_blocks = {i for b in blocks for i in b["trip_ids"]}
    assert in_blocks and in_blocks <= ids
    tagged = {t["trip_id"] for t in trips if t["regime"]["regime"] in ("LOW", "NORMAL", "HIGH")}
    assert tagged == in_blocks  # the per-trip tag is the 008 label, joined by trip id
    for t in trips:
        assert t["regime"]["regime"] is not None or t["regime"]["reason"]


# --- T9b cache -------------------------------------------------------------------------------------------------------

def test_t9b_cache_hits_across_endpoints_and_invalidates_on_ledger_change(engine, seeded):
    provider = FakeBars()
    client = TestClient(make_app(engine, provider=provider))
    first = get(client, "trips").json()
    n = len(provider.calls)
    assert n > 0
    assert get(client, "trips").json() == first and get(client, "regimes").status_code == 200
    assert get(client, "biases").status_code == 200
    assert len(provider.calls) == n  # nothing recomputed
    add_trade(seeded, USER_A, TradeSide.BUY, date(2026, 8, 20))
    add_trade(seeded, USER_A, TradeSide.SELL, date(2026, 8, 24))
    seeded.commit()
    after = get(client, "trips").json()
    assert len(provider.calls) > n and after["summary"]["trip_count"] == 15
    other = get(client, "trips", as_of="2026-10-31")
    assert other.status_code == 200 and len(provider.calls) > n  # keyed by as_of too


def test_t9b_results_with_unavailable_series_are_not_cached(engine, seeded):
    provider = FakeBars(missing=frozenset({TRADED}))
    client = TestClient(make_app(engine, provider=provider))
    get(client, "trips")
    n = len(provider.calls)
    get(client, "trips")
    assert len(provider.calls) > n  # a transient fetch failure cannot stick


def test_ledger_version_is_user_scoped_and_changes_with_any_row(session):
    repo = TradeRepository(session)
    assert repo.ledger_version(user_id=USER_B) == (0, None)
    seed_round_trips(session, USER_A, 2)
    v = repo.ledger_version(user_id=USER_A)
    assert v[0] == 4 and v[1] is not None and repo.ledger_version(user_id=USER_B) == (0, None)
    add_trade(session, USER_A, TradeSide.BUY, date(2026, 9, 1))
    session.commit()
    assert repo.ledger_version(user_id=USER_A) != v


# --- T12 answer_source -----------------------------------------------------------------------------------------------

def test_t12_ask_labels_template_answers_and_analysis_needs_no_ai(engine, seeded, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "none")
    client = TestClient(make_app(engine))
    assert get(client, "biases").status_code == 200  # no AI configured at all
    r = client.post("/api/analyst/ask", json={"question": "What did my behaviour cost me?", "as_of": ASOF})
    assert r.status_code == 200 and r.json()["answer_source"] == "template"
    assert {"text", "citations", "verified", "as_of", "attempts"} <= set(r.json())
    llm = FakeLLM([Draft("The chasing cost is shown in the facts.", ())] * 2)
    r2 = TestClient(make_app(engine, llm=llm)).post("/api/analyst/ask", json={"question": "What did my behaviour cost me?", "as_of": ASOF})
    assert r2.status_code == 200 and r2.json()["answer_source"] == "llm"
    assert TemplateLLM  # imported for the template/llm distinction above


def test_t4_per_trip_and_regime_luck_values_equal_the_quant_results(engine, seeded):
    """Parity with what was already computed (no new statistic): each trip's ALT/NIFTY outcome and each regime block's luck mean."""
    from app.services.portfolio_analysis import _stat
    with sessionmaker(engine)() as s:
        svc = PortfolioAnalysisService(repo=TradeRepository(s), provider=FakeBars(), clock=lambda: NOW, config=config())
        detail = svc.analyse_detail(USER_A, D_ASOF)
    facts = {f.name: f.value for f in detail.facts.facts}
    client = TestClient(make_app(engine))
    rows = {t["trip_id"]: t for t in get(client, "trips").json()["trips"]}
    checked = 0
    for group in detail.luck_groups:
        for trip in group.result.trips:
            row = rows[trip.trip_id]
            assert row["evaluated"] is trip.evaluated
            if not trip.evaluated:
                continue
            for key, outcome in (("alt", trip.alt), ("nifty", trip.nifty)):
                if outcome.unavailable is None:
                    assert row[key]["percentile"]["value"] == _stat(outcome.percentile)
                    assert row[key]["excess"]["value"] == _stat(outcome.excess)
                    checked += 1
                else:
                    assert row[key]["percentile"]["value"] is None and row[key]["unavailable_reason"]
    assert checked >= 14
    for blk in get(client, "regimes").json()["blocks"]:
        fact = facts[f"regime.{blk['regime']}.luck.ALT.mean_excess"]
        got = blk["luck"]["ALT"]["mean_excess"]["value"] if blk["luck"] else None
        assert ("Unavailable" if got is None else got) == fact


# --- review round: reason_text, percentile, histogram, direction, null counts, regimes sentence ---------------------------

def _detail(engine, **cfg):
    with sessionmaker(engine)() as s:
        svc = PortfolioAnalysisService(repo=TradeRepository(s), provider=cfg.pop("provider", None) or FakeBars(), clock=lambda: NOW,
                                       config=config(**cfg))
        return svc.analyse_detail(USER_A, D_ASOF)


def first_trip(client):
    trips = get(client, "trips").json()["trips"]
    return get(client, f"trips/{trips[0]['trip_id']}").json()["trip"]


def test_reason_text_is_plain_english_in_every_scenario(engine, session):
    seed_round_trips(session, USER_A, 14)
    scenarios = [
        {}, {"provider": FakeBars(missing=frozenset({TRADED}))}, {"corporate_action_reviewed": None}, {"nifty50": ()},
        {"provider": FakeBars(missing=frozenset({UNIVERSE[3].instrument}))},
    ]
    seen = 0
    for cfg in scenarios:
        client = TestClient(make_app(engine, **cfg))
        for path in ("meta", *ENDPOINTS):
            body = get(client, path).json()
            seen += assert_numbers_honest(body)
        trip = get(client, "trips").json()["trips"][0]
        assert_numbers_honest(get(client, f"trips/{trip['trip_id']}").json())
    assert seen > 100


def test_reason_text_when_nothing_is_there(engine, session):
    client = TestClient(make_app(engine))
    for path in ENDPOINTS:
        assert_numbers_honest(get(client, path).json())


def test_left_out_rows_name_the_ticker_and_a_plain_reason(engine, seeded):
    client = TestClient(make_app(engine, provider=FakeBars(missing=frozenset({UNIVERSE[3].instrument}))))
    ex = first_trip(client)["exclusions"]
    row = next(e for e in ex if e["symbol"] == "UNIV03")
    assert row["exchange"] == "NSE" and row["reason"] == "NO_SERIES" and row["baseline"] == "ALT"
    assert row["reason_text"] and not RAW_CODE.search(row["reason_text"])


def test_percentiles_display_with_no_decimals(engine, seeded):
    b = get(TestClient(make_app(engine)), "trips").json()
    t = first_trip(TestClient(make_app(engine)))
    for n in (b["summary"]["ALT"]["mean_percentile"], t["alt"]["percentile"], t["nifty"]["percentile"]):
        assert n["value"] is not None and re.fullmatch(r"-?\d+%", n["display"]), n
    assert b["summary"]["ALT"]["mean_excess"]["display"].count(".") == 1  # other ratios keep two decimals


def test_direction_is_explicit_and_follows_the_sign(engine, seeded):
    client = TestClient(make_app(engine))
    t = first_trip(client)
    for key in ("alt", "nifty"):
        o = t[key]
        sign = Decimal(o["excess"]["value"])
        assert o["excess_direction"] == ("ahead" if sign > 0 else "behind" if sign < 0 else "level")
    s = get(client, "trips").json()["summary"]["ALT"]
    mean = Decimal(s["mean_excess"]["value"])
    assert s["mean_excess_direction"] == ("ahead" if mean > 0 else "behind" if mean < 0 else "level")


def test_counts_and_direction_are_null_when_an_outcome_is_unavailable(engine, seeded):
    t = first_trip(TestClient(make_app(engine, nifty50=())))
    n = t["nifty"]
    assert n["percentile"]["value"] is None and n["excess_direction"] is None
    assert n["portfolio_count"] is None and n["pool_size"] is None and n["lost_count"] is None
    assert n["unavailable_reason"] and n["reason_text"]
    assert t["alt"]["portfolio_count"] is not None and t["histograms"]["NIFTY"] is None and t["histograms"]["ALT"] is not None


def test_quant_retains_the_portfolio_returns_it_already_computed(engine, seeded):
    detail = _detail(engine)
    checked = 0
    for g in detail.luck_groups:
        for trip in g.result.trips:
            for o in (trip.alt, trip.nifty):
                if o.unavailable is None:
                    assert o.portfolio_returns is not None and len(o.portfolio_returns) == o.portfolio_count
                    assert sum(1 for r in o.portfolio_returns if r < trip.actual_return) == o.beaten
                    checked += 1
                else:
                    assert o.portfolio_returns is None
    assert checked >= 14


def test_histogram_bins_match_the_computed_portfolios(engine, seeded):
    detail = _detail(engine)
    client = TestClient(make_app(engine))
    trips = {t["trip_id"]: t for t in get(client, "trips").json()["trips"]}
    group_trips = {t.trip_id: t for g in detail.luck_groups for t in g.result.trips}
    for tid in list(trips)[:5]:
        h = get(client, f"trips/{tid}").json()["trip"]["histograms"]["ALT"]
        q = group_trips[tid]
        assert len(h["bins"]) == 20 and sum(b["count"] for b in h["bins"]) == q.alt.portfolio_count == h["portfolio_count"]
        for a, b in zip(h["bins"], h["bins"][1:]):
            assert a["upper"]["value"] == b["lower"]["value"]  # contiguous, no gaps
        assert all(Decimal(b["lower"]["value"]) < Decimal(b["upper"]["value"]) for b in h["bins"])
        marker = h["bins"][h["marker_bin"]]
        actual = Decimal(h["actual_return"]["value"])
        assert Decimal(marker["lower"]["value"]) <= actual <= Decimal(marker["upper"]["value"])
        below = sum(b["count"] for b in h["bins"][:h["marker_bin"]])
        through = below + marker["count"]
        assert below <= q.alt.beaten <= through  # the portfolios the trip beat sit in or before its bin
        assert str(q.alt.portfolio_count) in h["text"] and "your trip" in h["text"]
        assert h["lower"]["display"] == h["bins"][0]["lower"]["display"] and h["upper"]["display"] == h["bins"][-1]["upper"]["display"]
    assert_numbers_honest(get(client, f"trips/{tid}").json())


def test_regimes_say_so_in_one_sentence_when_no_regime_has_enough_trips(engine, seeded):
    from app.quant.regime_split.types import RegimeParameters
    client = TestClient(make_app(engine, regime_parameters=RegimeParameters(min_trips_per_regime=100)))
    b = get(client, "regimes").json()
    counts = {x["regime"]: x["trip_count"] for x in b["blocks"]}
    assert b["none_ready_text"] == (f"Not enough trips in any regime yet: Low {counts['LOW']}, Normal {counts['NORMAL']}, "
                                    f"High {counts['HIGH']} (100 needed each)")
    assert all(x["sample"]["text"] == f"{x['trip_count']} trips · 100 needed" for x in b["blocks"])
    ready = get(TestClient(make_app(engine)), "regimes").json()  # 3 needed each: at least one regime has enough
    assert ready["none_ready_text"] is None


def test_regimes_sentence_when_the_analysis_did_not_run(engine, session):
    b = get(TestClient(make_app(engine)), "regimes").json()
    assert b["none_ready_text"] is None  # nothing to count: the Unavailable reason speaks instead
    assert b["unavailable_reason"] and b["reason_text"]
