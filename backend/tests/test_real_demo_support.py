"""Feature 012: universe flag propagation, review register semantics, bar cache, demo_real smoke. Offline."""

import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from analysis_helpers import D_ASOF, KNOWN, NOW, TRADED, UNIVERSE, FakeBars, config, seed_round_trips
from conftest import USER_A, make_engine
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.analyst.llm import TemplateLLM
from app.analyst.service import ask
from app.api.analyst_wiring import apply_caveats, quant_tools_with_caveats
from app.api.main import create_app
from app.config import Settings
from app.domain.enums import Exchange
from app.domain.instrument import Instrument
from app.repositories.trade_repository import TradeRepository
from app.repositories.user_repository import UserRepository
from app.services.analysis_toml import ReviewedWindow, load_reviewed, load_universe, resolve_corporate_actions
from app.services.portfolio_analysis import PortfolioAnalysisService

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
NOTE = "static universe, survivorship bias acknowledged"


def svc(session, **cfg):
    return PortfolioAnalysisService(repo=TradeRepository(session), provider=FakeBars(), clock=lambda: NOW, config=config(**cfg))


def test_shipped_universe_file_is_flagged_and_loads():
    u = load_universe(ROOT / "config" / "analysis_universe.toml")
    assert u.static is True and u.note == NOTE and len(u.candidates) == 25  # 22 + INDIANB, PSB, UCOBANK added in 014 (niftyindices 2026-10-16)
    assert len({c.isin for c in u.candidates}) == len(u.candidates)


def test_universe_file_without_the_flag_is_rejected(tmp_path):
    p = tmp_path / "u.toml"
    p.write_text('[[instrument]]\nsymbol = "X"\nisin = "INE000X01011"\n', encoding="utf-8")
    with pytest.raises(ValueError):
        load_universe(p)


def test_shipped_register_matches_the_owner_review_and_leaves_the_banks_unreviewed():
    windows = load_reviewed(ROOT / "config" / "corporate_actions_reviewed.toml")
    by = {w.instrument.symbol: w for w in windows}
    assert len(windows) == 24 and all(w.from_date == date(2023, 10, 1) and w.to_date == date(2026, 10, 15) for w in windows)
    assert {s: [d for d, _ in by[s].actions] for s in ("RELIANCE", "WIPRO", "ITC", "HDFCBANK", "HINDUNILVR", "CANBK")} == {
        "RELIANCE": [date(2024, 10, 28)], "WIPRO": [date(2024, 12, 3)], "ITC": [date(2025, 1, 6)],
        "HDFCBANK": [date(2025, 8, 27)], "HINDUNILVR": [date(2025, 12, 5)], "CANBK": [date(2024, 5, 15)]}
    assert all(not w.actions for s, w in by.items() if s not in ("RELIANCE", "WIPRO", "ITC", "HDFCBANK", "HINDUNILVR", "CANBK"))
    unverified = {"PNB", "BANKBARODA", "UNIONBANK", "BANKINDIA", "MAHABANK"}
    assert unverified.isdisjoint(by)  # in the universe, deliberately not reviewed
    assert unverified <= {c.instrument.symbol for c in load_universe(ROOT / "config" / "analysis_universe.toml").candidates}


def test_review_window_must_cover_the_whole_range_and_actions_exclude():
    w = (ReviewedWindow(TRADED, date(2025, 1, 1), date(2026, 12, 31), ()),
         ReviewedWindow(UNIVERSE[0].instrument, date(2025, 6, 1), date(2026, 12, 31), ()),  # starts too late
         ReviewedWindow(UNIVERSE[1].instrument, date(2025, 1, 1), date(2026, 12, 31), ((date(2026, 2, 1), "split 1:2"),)))
    listings = {TRADED, UNIVERSE[0].instrument, UNIVERSE[1].instrument}
    reviewed, known = resolve_corporate_actions(w, listings, date(2025, 1, 1), D_ASOF)
    assert reviewed == {TRADED, UNIVERSE[1].instrument} and known == {UNIVERSE[1].instrument}


def test_unreviewed_instrument_is_excluded_with_a_reason_and_luck_is_unavailable_not_zero(session):
    seed_round_trips(session, USER_A, 14)
    facts = svc(session, corporate_action_reviewed=frozenset({u.instrument for u in UNIVERSE})).analyse(USER_A, D_ASOF)  # TRADED missing
    f = {x.name: x for x in facts.facts}
    assert f["luck.ALT.mean_excess"].value == "Unavailable" and f["luck.ALT.trips_evaluated"].value == "Unavailable"
    assert "all traded listings are excluded" in dict(facts.unavailable)["luck.ALT.mean_excess"]
    assert facts.provenance["excluded_listings"] == [["TEST1", "NSE", "not covered by the corporate-action review register", 14]]
    assert f["luck.coverage.trips_total"].value == "14" and f["luck.coverage.trips_analysed"].value == "Unavailable"


def test_universe_flag_reaches_provenance(session):
    seed_round_trips(session, USER_A, 14)
    prov = svc(session, universe_static=True, universe_note=NOTE).analyse(USER_A, D_ASOF).provenance
    assert prov["universe_static"] is True and prov["universe_note"] == NOTE


def test_flag_is_appended_to_every_answer_that_uses_luck_facts(session):
    seed_round_trips(session, USER_A, 14)
    s = svc(session, universe_static=True, universe_note=NOTE)
    for q, expect in (("Was my last buy skill or luck?", True), ("How did I do in each regime?", True),
                      ("What did my behaviour cost me?", False)):
        tools, caveats = quant_tools_with_caveats(s.analyse)
        a = apply_caveats(ask(USER_A, q, D_ASOF, llm=TemplateLLM(), tools=tools), caveats())
        assert a.verified and (NOTE in a.text) is expect


def test_endpoint_answer_carries_the_flag(engine, session):
    seed_round_trips(session, USER_A, 14)
    app = create_app(session_factory=sessionmaker(engine, expire_on_commit=False), settings=Settings(user_id=USER_A),
                     clock=lambda: NOW, history_provider=FakeBars(), analysis_config=config(universe_static=True, universe_note=NOTE))
    r = TestClient(app).post("/api/analyst/ask", json={"question": "Was my last buy skill or luck?", "as_of": D_ASOF.isoformat()})
    assert r.status_code == 200 and NOTE in r.json()["text"] and r.json()["verified"] is True


def test_cache_hit_makes_no_provider_call_and_keeps_the_fingerprint(tmp_path):
    from bar_cache import CachingBars
    from app.services.market_series import MarketSeriesService, ResolvedSeries
    inner = FakeBars()
    cache = CachingBars(inner, tmp_path)
    clock = lambda: NOW
    first = MarketSeriesService(provider=cache, clock=clock).resolve_series([TRADED], date(2026, 1, 1), D_ASOF)
    assert isinstance(first, ResolvedSeries) and len(inner.calls) == 1 and cache.misses == 1
    later = datetime(2026, 12, 5, 9, 0, tzinfo=timezone.utc)  # a different retrieval instant
    second = MarketSeriesService(provider=cache, clock=lambda: later).resolve_series([TRADED], date(2026, 1, 1), D_ASOF)
    assert len(inner.calls) == 1 and cache.hits == 1  # no second call to the underlying provider
    assert second.series.fingerprint == first.series.fingerprint


def test_cache_does_not_store_failures(tmp_path):
    from bar_cache import CachingBars
    inner = FakeBars(missing=frozenset({TRADED}))
    cache = CachingBars(inner, tmp_path)
    for _ in range(2):
        cache.get_daily_bars(TRADED, date(2026, 1, 1), D_ASOF, NOW)
    assert len(inner.calls) == 2 and not list(tmp_path.glob("*.json"))


def test_demo_real_smoke_offline_with_fake_provider(tmp_path):
    import demo_real
    sys.path.insert(0, str(ROOT / "tests" / "fixtures"))
    from build_demo_fixture import tradebook_bytes
    out = tmp_path / "report.md"
    summary = demo_real.run([("a.csv", tradebook_bytes()), ("b.csv", tradebook_bytes())], FakeBars(), D_ASOF, NOW, out,
                            luck_portfolios=20, replicates=200)
    text = out.read_text(encoding="utf-8")
    assert summary["total"] == 4 and NOTE in text and "Not reviewed" in text
    assert summary["imported"] == 30 and summary["duplicates"] == 30 and summary["rejected"] == 0  # b.csv overlaps a.csv fully
    assert "skipped as duplicates 30" in text and "imported once: 2" in text


def test_aliased_symbol_is_fetched_by_alias_and_ledger_identity_is_unchanged(tmp_path):
    from bar_cache import AliasingBars
    from app.services.market_series import MarketSeriesService, ResolvedSeries
    ledger = Instrument("OLDNAME", Exchange.NSE)
    seen = []

    class Inner:
        def get_daily_bars(self, instrument, start, end, retrieved_at):
            seen.append(instrument)
            return FakeBars().get_daily_bars(TRADED if instrument.symbol == "TEST1" else instrument, start, end, retrieved_at)

    provider = AliasingBars(Inner(), {"OLDNAME": "TEST1"})
    r = MarketSeriesService(provider=provider, clock=lambda: NOW).resolve_series([ledger], date(2026, 1, 1), D_ASOF)
    assert isinstance(r, ResolvedSeries) and seen == [Instrument("TEST1", Exchange.NSE)]  # fetched by the alias
    assert r.series.instrument == ledger  # the series still carries the ledger symbol
    seen.clear()
    provider.get_daily_bars(TRADED, date(2026, 1, 1), D_ASOF, NOW)
    assert seen == [TRADED]  # unaliased symbols pass through


def test_shipped_alias_file_maps_zomato_to_eternal():
    from app.services.analysis_toml import load_aliases
    assert load_aliases(ROOT / "config" / "symbol_aliases.toml") == {"ZOMATO": "ETERNAL"}


def test_partial_coverage_runs_on_the_remaining_trips_and_names_the_excluded_listing(session):
    other = UNIVERSE[0].instrument
    seed_round_trips(session, USER_A, 14)
    seed_round_trips(session, USER_A, 6, first=date(2026, 3, 4), instrument=other, isin=UNIVERSE[0].isin)
    facts = PortfolioAnalysisService(repo=TradeRepository(session), provider=FakeBars(missing=frozenset({other})), clock=lambda: NOW,
                                     config=config(universe_static=True, universe_note=NOTE)).analyse(USER_A, D_ASOF)
    f = {x.name: x for x in facts.facts}
    assert (f["luck.coverage.trips_total"].value, f["luck.coverage.trips_analysed"].value) == ("20", "14")
    assert (f["regime.coverage.trips_total"].value, f["regime.coverage.trips_analysed"].value) == ("20", "14")
    assert f["luck.coverage.excluded_listing_count"].value == "1" and f["luck.trip_count"].value == "14"
    (sym, exch, why, trips), = facts.provenance["excluded_listings"]
    assert (sym, exch, trips) == (other.symbol, "NSE", 6) and why.startswith("no market-data series")
    assert f["luck.ALT.trips_evaluated"].value != "Unavailable"
    assert f["bias.OVERTRADING.cost_inr"].value == "Unavailable"  # 006 keeps its strict completeness rule


def test_exclusions_are_stated_in_the_answer_never_silent(session):
    other = UNIVERSE[0].instrument
    seed_round_trips(session, USER_A, 14)
    seed_round_trips(session, USER_A, 6, first=date(2026, 3, 4), instrument=other, isin=UNIVERSE[0].isin)
    s = PortfolioAnalysisService(repo=TradeRepository(session), provider=FakeBars(missing=frozenset({other})), clock=lambda: NOW, config=config())
    tools, caveats = quant_tools_with_caveats(s.analyse)
    a = apply_caveats(ask(USER_A, "Was my last buy skill or luck?", D_ASOF, llm=TemplateLLM(), tools=tools), caveats())
    assert a.verified and "not analysed in luck/regime" in a.text and f"{other.symbol}.NSE" in a.text


def test_register_is_keyed_by_isin_so_one_review_covers_nse_and_bse():
    bse = Instrument(TRADED.symbol, Exchange.BSE)
    isin_of = {TRADED: "INE000T01011", bse: "INE000T01011"}
    w = (ReviewedWindow(TRADED, date(2023, 10, 1), date(2026, 12, 31), ((date(2024, 5, 15), "split"),)),)
    reviewed, known = resolve_corporate_actions(w, {TRADED, bse, Instrument("OTHER", Exchange.BSE)}, date(2024, 1, 1), D_ASOF, isin_of)
    assert reviewed == {TRADED, bse} and known == {TRADED, bse}  # OTHER (no ISIN match) stays unreviewed


def test_bse_listing_is_priced_by_the_nse_series_and_the_proxy_is_disclosed(session):
    from analysis_helpers import TRADED_ISIN
    from app.quant.luck_test.types import Candidate
    bse = Instrument(TRADED.symbol, Exchange.BSE)
    seed_round_trips(session, USER_A, 14, instrument=bse)
    provider = FakeBars()
    s = PortfolioAnalysisService(
        repo=TradeRepository(session), provider=provider, clock=lambda: NOW,
        config=config(universe=UNIVERSE + (Candidate(TRADED, TRADED_ISIN),),
                      corporate_action_reviewed=frozenset(set(config().corporate_action_reviewed) | {bse})))
    facts = s.analyse(USER_A, D_ASOF)
    assert facts.provenance["price_proxies"] == [["TEST1", "BSE", "TEST1", "NSE"]]
    assert facts.provenance["price_proxy_note"] == "price proxy: NSE series for BSE listing"
    assert bse not in {inst for inst, *_ in provider.calls}  # never fetched under its own exchange
    f = {x.name: x for x in facts.facts}
    assert f["bias.OVERTRADING.cost_inr"].value != "Unavailable" and f["luck.coverage.trips_analysed"].value == "14"
    tools, caveats = quant_tools_with_caveats(s.analyse)
    a = apply_caveats(ask(USER_A, "What did my behaviour cost me?", D_ASOF, llm=TemplateLLM(), tools=tools), caveats())
    assert "price proxy: NSE series for BSE listing" in a.text


def _csv(rows):
    head = "symbol,isin,trade_date,exchange,segment,series,trade_type,auction,quantity,price,trade_id,order_id,order_execution_time"
    return ("\n".join([head, *rows]) + "\n").encode()


def _rows():
    from datetime import timedelta
    from analysis_helpers import TRADED_ISIN, close_on
    rows, n = [], 0
    for k in range(14):
        d = date(2026, 3, 2) + timedelta(days=8 * k)
        for side, day in (("buy", d), ("sell", d + timedelta(days=3))):
            n += 1
            rows.append((side, f"TEST1,{TRADED_ISIN},{day},NSE,EQ,EQ,{side},false,10.000000,{close_on(0, day):.6f},{930000 + n},{3000000000000000 + n},{day}T10:30:00"))
    return rows


def test_import_order_cause_and_fix(tmp_path):
    """Cause: the importer rejects a sell whose buy is not in the ledger yet, so separate imports depend on their order.
    Fix: merge the files and import once; the analyses key trades by content, not by random row ids."""
    from uuid import UUID
    from sqlalchemy.orm import Session
    import demo_real
    from app.services.tradebook_import import TradebookImportService
    rows = _rows()
    buys = _csv([r for side, r in rows if side == "buy"])
    sells = _csv([r for side, r in rows if side == "sell"])

    def sequential(first, second):
        ids = iter(range(1, 10_000))
        with Session(make_engine()) as ses:
            UserRepository(ses).ensure(USER_A)
            ses.commit()
            imp = TradebookImportService.for_session(ses, clock=lambda: NOW, id_factory=lambda: UUID(int=next(ids) + 0x9000))
            return [imp.import_tradebook(user_id=USER_A, file_name="f", content=c).imported for c in (first, second)]
    assert sequential(sells, buys) != sequential(buys, sells)  # the importer alone is order-dependent

    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "analysis_universe.toml").write_text('static_universe = true\nnote = "static universe, survivorship bias acknowledged"\n' + "".join(
        f'[[instrument]]\nsymbol = "{c.instrument.symbol}"\nisin = "{c.isin}"\n' for c in UNIVERSE), encoding="utf-8")
    (cfg / "corporate_actions_reviewed.toml").write_text("".join(
        f'[[reviewed]]\nsymbol = "{i.symbol}"\nfrom = "2023-10-01"\nto = "2026-10-15"\nactions = []\n' for i in KNOWN), encoding="utf-8")
    outs = []
    for name, books in (("ab", [("a", sells), ("b", buys)]), ("ba", [("b", buys), ("a", sells)])):
        outs.append(demo_real.run(books, FakeBars(), D_ASOF, NOW, tmp_path / f"{name}.md", config_dir=cfg, luck_portfolios=20, replicates=200))
    assert outs[0]["imported"] == outs[1]["imported"] == 28 and outs[0]["rejected"] == 0
    assert outs[0]["facts"] == outs[1]["facts"] and outs[0]["provenance"] == outs[1]["provenance"]  # incl. fingerprints and seeds
    assert (tmp_path / "ab.md").read_text(encoding="utf-8") == (tmp_path / "ba.md").read_text(encoding="utf-8")
    assert outs[0]["provenance"]["input_fingerprints"]["007"] and outs[0]["verified"] == 4


def test_analysis_identity_does_not_depend_on_row_ids(session):
    from uuid import uuid4
    from sqlalchemy import update
    from app.models.trade import Trade
    seed_round_trips(session, USER_A, 14)
    a = svc(session).analyse(USER_A, D_ASOF)
    for old in [t.id for t in TradeRepository(session).list_effective(user_id=USER_A)]:  # re-key every row
        session.execute(update(Trade).where(Trade.id == old).values(id=uuid4()))
    session.commit()
    assert svc(session).analyse(USER_A, D_ASOF).to_dict() == a.to_dict()
