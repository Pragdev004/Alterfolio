"""Feature 012: universe flag propagation, review register semantics, bar cache, demo_real smoke. Offline."""

import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from analysis_helpers import D_ASOF, NOW, TRADED, UNIVERSE, FakeBars, config, seed_round_trips
from conftest import USER_A
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
from app.services.analysis_toml import ReviewedWindow, load_reviewed, load_universe, resolve_corporate_actions
from app.services.portfolio_analysis import PortfolioAnalysisService

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
NOTE = "static universe, survivorship bias acknowledged"


def svc(session, **cfg):
    return PortfolioAnalysisService(repo=TradeRepository(session), provider=FakeBars(), clock=lambda: NOW, config=config(**cfg))


def test_shipped_universe_file_is_flagged_and_loads():
    u = load_universe(ROOT / "config" / "analysis_universe.toml")
    assert u.static is True and u.note == NOTE and len(u.candidates) == 22
    assert len({c.isin for c in u.candidates}) == len(u.candidates)


def test_universe_file_without_the_flag_is_rejected(tmp_path):
    p = tmp_path / "u.toml"
    p.write_text('[[instrument]]\nsymbol = "X"\nisin = "INE000X01011"\n', encoding="utf-8")
    with pytest.raises(ValueError):
        load_universe(p)


def test_shipped_register_matches_the_owner_review_and_leaves_the_banks_unreviewed():
    windows = load_reviewed(ROOT / "config" / "corporate_actions_reviewed.toml")
    by = {w.instrument.symbol: w for w in windows}
    assert len(windows) == 24 and all(w.from_date == date(2024, 7, 29) and w.to_date == date(2026, 10, 15) for w in windows)
    assert {s: [d for d, _ in by[s].actions] for s in ("RELIANCE", "WIPRO", "ITC", "HDFCBANK", "HINDUNILVR")} == {
        "RELIANCE": [date(2024, 10, 28)], "WIPRO": [date(2024, 12, 3)], "ITC": [date(2025, 1, 6)],
        "HDFCBANK": [date(2025, 8, 27)], "HINDUNILVR": [date(2025, 12, 5)]}
    assert all(not w.actions for s, w in by.items() if s not in ("RELIANCE", "WIPRO", "ITC", "HDFCBANK", "HINDUNILVR"))
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


def test_unreviewed_instrument_makes_luck_unavailable_not_zero(session):
    seed_round_trips(session, USER_A, 14)
    facts = svc(session, corporate_action_reviewed=frozenset({u.instrument for u in UNIVERSE})).analyse(USER_A, D_ASOF)  # TRADED missing
    f = {x.name: x for x in facts.facts}
    assert f["luck.ALT.mean_excess"].value == "Unavailable" and f["luck.ALT.trips_evaluated"].value == "0"
    assert "CORPORATE_ACTION_UNKNOWN" in dict(facts.unavailable)["luck.ALT.mean_excess"]


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
    assert "skipped as duplicates 30" in text and "a.csv: 30/0/0" in text and "b.csv: 0/30/0" in text


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
