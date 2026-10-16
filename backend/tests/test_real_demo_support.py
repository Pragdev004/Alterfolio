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
    assert u.static is True and u.note == NOTE and 15 <= len(u.candidates) <= 20
    assert len({c.isin for c in u.candidates}) == len(u.candidates)


def test_universe_file_without_the_flag_is_rejected(tmp_path):
    p = tmp_path / "u.toml"
    p.write_text('[[instrument]]\nsymbol = "X"\nisin = "INE000X01011"\n', encoding="utf-8")
    with pytest.raises(ValueError):
        load_universe(p)


def test_shipped_register_is_empty_so_everything_is_unreviewed():
    windows = load_reviewed(ROOT / "config" / "corporate_actions_reviewed.toml")
    assert windows == ()
    reviewed, known = resolve_corporate_actions(windows, {TRADED}, date(2025, 1, 1), D_ASOF)
    assert reviewed == frozenset() and known == frozenset()


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
    summary = demo_real.run(tradebook_bytes(), FakeBars(), D_ASOF, NOW, out, luck_portfolios=20, replicates=200)
    text = out.read_text(encoding="utf-8")
    assert summary["total"] == 4 and NOTE in text and "Not reviewed" in text
    assert Instrument("DEMOCO", Exchange.NSE).symbol in text or "DEMOCO" in text
