"""Feature 011: PortfolioAnalysisService (spec A1-A5, A9). Offline: fake bar provider, in-memory SQLite ledger."""

import json
from datetime import date, datetime, timedelta, timezone

import pytest
from analysis_helpers import (
    D_ASOF, NOW, TRADED, TRADED_ISIN, FakeBars, add_trade, close_on, config, seed_round_trips, walk_floats,
)
from conftest import USER_A, USER_B

from app.domain.enums import TradeSide, TradeStatus
from app.repositories.trade_repository import TradeRepository
from app.services.errors import AsOfNotSealedError
from app.services.portfolio_analysis import PortfolioAnalysisService, derive_seed

B_CUTOFF = datetime(2026, 9, 30, 18, 30, tzinfo=timezone.utc)  # IST midnight of D+1


def make(session, provider=None, **cfg):
    return PortfolioAnalysisService(repo=TradeRepository(session), provider=provider or FakeBars(), clock=lambda: NOW,
                                    config=config(**cfg))


def by_name(facts):
    return {f.name: f for f in facts.facts}


@pytest.fixture
def seeded(session):
    seed_round_trips(session, USER_A, 14)
    return session


def test_a1_trade_after_D_is_ignored(seeded):
    base = make(seeded).analyse(USER_A, D_ASOF).to_dict()
    for side, day in ((TradeSide.BUY, date(2026, 10, 10)), (TradeSide.SELL, date(2026, 10, 14))):
        add_trade(seeded, USER_A, side, day)
    seeded.commit()
    assert make(seeded).analyse(USER_A, D_ASOF).to_dict() == base


def test_a1_rows_recorded_after_D_are_disclosed(seeded):
    base = make(seeded).analyse(USER_A, D_ASOF)
    assert base.provenance["late_recorded_row_count"] == 0
    late = datetime(2026, 10, 5, 5, 0, tzinfo=timezone.utc)
    first_sell = TradeRepository(seeded).list_effective(user_id=USER_A)[1]
    add_trade(seeded, USER_A, TradeSide.SELL, first_sell.trade_timestamp.date(), recorded_at=late,
              supersedes=first_sell.id, status=TradeStatus.CANCELLED)  # voided after D: a disclosed, not hidden, change
    seeded.commit()
    after = make(seeded).analyse(USER_A, D_ASOF)
    assert after.provenance["late_recorded_row_count"] == 1


def test_a1_trip_closed_on_D_is_evaluated(seeded):
    before = by_name(make(seeded).analyse(USER_A, D_ASOF))["luck.ALT.trips_evaluated"].value
    add_trade(seeded, USER_A, TradeSide.BUY, D_ASOF - timedelta(days=3))
    add_trade(seeded, USER_A, TradeSide.SELL, D_ASOF)
    seeded.commit()
    after = by_name(make(seeded).analyse(USER_A, D_ASOF))["luck.ALT.trips_evaluated"].value
    assert int(after) == int(before) + 1


def test_a2_bars_after_D_never_reach_an_analysis(seeded):
    base = make(seeded, FakeBars()).analyse(USER_A, D_ASOF).to_dict()
    leaky = make(seeded, FakeBars(leaky=True)).analyse(USER_A, D_ASOF).to_dict()
    perturbed = make(seeded, FakeBars(leaky=True, perturb_after=D_ASOF)).analyse(USER_A, D_ASOF).to_dict()
    assert base == leaky == perturbed


def test_a2_series_are_requested_up_to_D_only(seeded):
    provider = FakeBars()
    make(seeded, provider).analyse(USER_A, D_ASOF)
    assert provider.calls and all(end <= D_ASOF for _, _, end, _ in provider.calls)
    assert len({t for *_, t in provider.calls}) == 1  # one frozen clock reading per analyse()


def test_a3_other_users_trades_are_never_read(session):
    seed_round_trips(session, USER_B, 14)
    spy = TradeRepository(session)
    seen = []
    original = spy.list_effective
    spy.list_effective = lambda **kw: (seen.append(kw["user_id"]), original(**kw))[1]
    provider = FakeBars()
    svc = PortfolioAnalysisService(repo=spy, provider=provider, clock=lambda: NOW, config=config())
    facts = svc.analyse(USER_A, D_ASOF)
    assert seen == [USER_A]
    assert not any(inst == TRADED for inst, *_ in provider.calls)  # A traded nothing: B's listing is never fetched
    assert all(f.value == "Unavailable" or int(f.value) == 0 for f in facts.facts if f.name.endswith("trip_count"))


def test_a4_missing_series_is_unavailable_with_reason_never_zero(seeded):
    facts = make(seeded, FakeBars(missing=frozenset({TRADED}))).analyse(USER_A, D_ASOF)
    f = by_name(facts)
    reasons = dict(facts.unavailable)
    for name in ("bias.DISPOSITION.cost_inr", "bias.CHASING.cost_inr", "bias.OVERTRADING.cost_inr"):
        assert f[name].value == "Unavailable" and reasons[name]


def test_a4_undeclared_corporate_action_coverage_makes_luck_unavailable(seeded):
    facts = make(seeded, corporate_action_reviewed=None).analyse(USER_A, D_ASOF)
    reasons = dict(facts.unavailable)
    assert "CORPORATE_ACTION_COVERAGE_UNDECLARED" in reasons["luck.ALT.mean_excess"]
    assert by_name(facts)["luck.ALT.mean_excess"].value == "Unavailable"


def test_a4_every_unavailable_fact_says_unavailable_and_has_a_reason(seeded):
    facts = make(seeded, corporate_action_reviewed=None).analyse(USER_A, D_ASOF)
    f = by_name(facts)
    assert facts.unavailable
    for name, reason in facts.unavailable:
        assert reason.strip()
        if name in f:
            assert f[name].value == "Unavailable"
    assert not [x for x in facts.facts if x.value == "Unavailable" and x.name not in dict(facts.unavailable)]


def test_a4_user_without_trades_gets_unavailable_not_zero_costs(session):
    facts = make(session).analyse(USER_A, D_ASOF)
    f = by_name(facts)
    assert all(f[n].value == "Unavailable" for n in f if n.endswith("cost_inr"))


def test_a4_short_history_trips_are_unclassified_not_guessed(session):
    seed_round_trips(session, USER_A, 12, first=date(2025, 2, 3), step=8)
    f = by_name(make(session).analyse(USER_A, D_ASOF))
    assert f["regime.round_trip_count"].value == "12" and f["regime.unclassified_count"].value == "12"


def test_a4_malformed_stored_isin_is_unavailable_not_an_error(session):
    seed_round_trips(session, USER_A, 12, isin="ine000t01011")
    facts = make(session).analyse(USER_A, D_ASOF)
    assert facts.unavailable and all(f.value == "Unavailable" for f in facts.facts if f.name.startswith("bias."))


@pytest.mark.parametrize("as_of", [date(2026, 12, 1), date(2026, 12, 2)])
def test_d_not_sealed_is_rejected(seeded, as_of):
    with pytest.raises(AsOfNotSealedError):
        make(seeded).analyse(USER_A, as_of)


def test_a5_identical_inputs_identical_facts_and_seeds(seeded):
    a, b = make(seeded).analyse(USER_A, D_ASOF), make(seeded).analyse(USER_A, D_ASOF)
    assert a == b and a.to_dict() == b.to_dict()
    assert a.provenance["seeds"] == b.provenance["seeds"]


def test_a5_seed_depends_on_user_date_and_name_and_fits_64_bits():
    seeds = {derive_seed(u, d, n) for u in (USER_A, USER_B) for d in (D_ASOF, D_ASOF + timedelta(days=1))
             for n in ("luck_test", "regime_split")}
    assert len(seeds) == 8 and all(0 <= s < 2**64 for s in seeds)
    assert derive_seed(USER_A, D_ASOF, "luck_test") == derive_seed(USER_A, D_ASOF, "luck_test")


def test_a5_luck_and_regime_use_different_recorded_seeds(seeded):
    s = make(seeded).analyse(USER_A, D_ASOF).provenance["seeds"]
    assert s["luck_test"] != s["regime_split"] and s["luck_test"] == derive_seed(USER_A, D_ASOF, "luck_test")


def test_a6_real_numbers_come_through(seeded):
    f = by_name(make(seeded).analyse(USER_A, D_ASOF))
    assert f["regime.round_trip_count"].value == "14"
    assert f["luck.trip_count"].value == "14"
    assert f["luck.ALT.trips_evaluated"].value != "Unavailable"
    assert f["regime.round_trip_count"].source.startswith("008:")
    assert f["luck.trip_count"].source.startswith("007:")
    assert f["bias.OVERTRADING.cost_inr"].source.startswith("006:")


def test_a9_frozen_json_and_no_floats(seeded):
    facts = make(seeded).analyse(USER_A, D_ASOF)
    with pytest.raises(Exception):
        facts.facts = ()  # frozen
    payload = facts.to_dict()
    assert json.loads(json.dumps(payload)) == payload
    assert list(walk_floats(payload)) == []
    for f in facts.facts:
        assert f.value == "Unavailable" or f.value.lstrip("-").replace(".", "", 1).isdigit()


def test_close_on_is_positive_and_deterministic():
    assert close_on(0, date(2026, 3, 2)) == close_on(0, date(2026, 3, 2)) > 0
    assert TRADED_ISIN


def test_014_alternatives_label_per_trip_and_reference_provenance_reach_the_facts(seeded):
    from analysis_helpers import TRADED_ISIN, UNIVERSE
    cfg = {"alternatives": {TRADED_ISIN: (UNIVERSE, "alternatives: TEST INDEX (%d)" % len(UNIVERSE))},
           "reference_provenance": ({"file_name": "f_2026-10-16.csv", "sha256": "ab", "download_date": "2026-10-16", "source_label": "t"},)}
    prov = make(seeded, **cfg).analyse(USER_A, date(2026, 9, 30)).provenance
    assert prov["luck_alternatives"]["facts_group"].startswith("alternatives: TEST INDEX")
    assert {row[2] for row in prov["luck_alternatives"]["per_trip"]} == {prov["luck_alternatives"]["facts_group"]}
    assert prov["reference_data"][0]["sha256"] == "ab"
    default = make(seeded).analyse(USER_A, date(2026, 9, 30)).provenance
    assert default["luck_alternatives"]["facts_group"] == "alternatives: static universe"
