"""Feature 007 contracts and package-level guards (spec sections 2, 7-9, 10 rows 8-9)."""
import ast
import dataclasses
import sys
from decimal import Decimal as D
from pathlib import Path

import pytest

from app.quant.luck_test import types as luck_types
from app.quant.luck_test.errors import LuckInputError, Unavailable, UnavailableReason
from app.quant.luck_test.types import (
    AlternativePick, Baseline, BaselineOutcome, BaselineSummary, IntervalPosition, LuckParameters, LuckResult, TripLuck,
)
from luck_helpers import OWN, RETRIEVED, isin, session

PACKAGE = Path(luck_types.__file__).parent
FILES = sorted(PACKAGE.glob("*.py"))
STDLIB = set(sys.stdlib_module_names)
STATISTIC_FIELDS = {"distance", "excess", "percentile", "mean_excess", "mean_percentile", "ci_lower", "ci_upper"}


def tree(path):
    return ast.parse(path.read_text(encoding="utf-8"))


def test_the_package_exists_with_the_planned_modules():
    names = {p.stem for p in FILES}
    assert {"errors", "types", "numeric_boundary", "rng", "features", "portfolios", "bootstrap", "fingerprint",
            "analysis"} <= names


def test_package_imports_only_stdlib_domain_market_data_and_siblings_by_relative_import():  # spec 10.9
    for path in FILES:
        for node in ast.walk(tree(path)):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] in STDLIB, f"{path.name} imports {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    assert node.level == 1, f"{path.name} uses a parent-relative import"
                    continue
                name = node.module or ""
                ok = name.split(".")[0] in STDLIB or name == "app.domain" or name.startswith("app.domain.") \
                    or name == "app.quant.market_data" or name.startswith("app.quant.market_data.")
                assert ok, f"{path.name} imports {name}"


def test_package_never_touches_sibling_features_upper_layers_or_banned_modules():
    banned_roots = {"random", "secrets", "time", "os", "sys", "socket", "httpx", "sqlalchemy", "fastapi", "pydantic"}
    banned_prefixes = ("app.quant.bias_cost", "app.quant.backtest", "app.providers", "app.services", "app.api",
                       "app.schemas", "app.models", "app.repositories", "app.db", "app.ai")
    for path in FILES:
        for node in ast.walk(tree(path)):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level:
                names = [node.module or ""]
            for name in names:
                assert name.split(".")[0] not in banned_roots, f"{path.name} imports {name}"
                assert not name.startswith(banned_prefixes), f"{path.name} imports {name}"
            if isinstance(node, ast.Name):
                assert node.id not in {"__import__", "open", "print", "eval", "exec"}, f"{path.name}: {node.id}"
            if isinstance(node, ast.Attribute):
                assert node.attr not in {"now", "utcnow", "today", "log", "exp", "random", "shuffle", "sample"}, \
                    f"{path.name}: .{node.attr}"


def test_decimal_to_float_happens_only_in_the_boundary_module_and_there_are_no_float_literals():  # spec 7, 10.8
    for path in FILES:
        for node in ast.walk(tree(path)):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "float":
                assert path.name == "numeric_boundary.py", f"{path.name}: float() call"
            assert not (isinstance(node, ast.Constant) and isinstance(node.value, float)), f"{path.name}: float literal"


def test_floats_appear_only_on_statistic_fields():  # spec 7
    for cls in (luck_types.TripInput, luck_types.Candidate, luck_types.Membership, LuckParameters, AlternativePick,
                BaselineOutcome, TripLuck, BaselineSummary, LuckResult):
        for f in dataclasses.fields(cls):
            if "float" in str(f.type):
                assert f.name in STATISTIC_FIELDS, f"{cls.__name__}.{f.name} must not be a float"
    for name in ("cost_inr", "proceeds_inr"):
        assert dataclasses.fields(luck_types.TripInput)[[f.name for f in dataclasses.fields(luck_types.TripInput)].index(name)].type is D


def test_public_types_are_frozen_dataclasses():
    for cls in (luck_types.TripInput, luck_types.Candidate, luck_types.Membership, LuckParameters, AlternativePick,
                BaselineOutcome, TripLuck, BaselineSummary, LuckResult, Unavailable):
        assert dataclasses.is_dataclass(cls) and cls.__dataclass_params__.frozen, cls.__name__


def test_unavailable_needs_a_known_reason():
    assert Unavailable(UnavailableReason.NO_MEMBERSHIP).detail == ""
    for bad in ("NO_MEMBERSHIP", None):
        with pytest.raises(LuckInputError):
            Unavailable(bad)
    with pytest.raises(LuckInputError):
        Unavailable(UnavailableReason.NO_MEMBERSHIP, "x" * 257)


def _ok_outcome(**kw):
    base = dict(baseline=Baseline.ALT, portfolio_count=10, pool_size=5, lost_count=0, beaten=3, ties=1,
                mean_return=D("0.1"), excess=0.01, percentile=0.35, unavailable=None)
    base.update(kw)
    return BaselineOutcome(**base)


def test_an_outcome_is_numbers_or_unavailable_never_both_and_never_a_silent_zero():  # spec 8
    assert _ok_outcome().excess == 0.01
    un = Unavailable(UnavailableReason.INSUFFICIENT_ALTERNATIVES)
    empty = dict(portfolio_count=0, pool_size=0, beaten=None, ties=None, mean_return=None, excess=None, percentile=None,
                 unavailable=un)
    assert _ok_outcome(**empty).unavailable is un
    with pytest.raises(LuckInputError):
        _ok_outcome(**{**empty, "excess": 0.0})  # a number beside an Unavailable
    with pytest.raises(LuckInputError):
        _ok_outcome(unavailable=None, excess=None)  # neither
    with pytest.raises(LuckInputError):
        _ok_outcome(beaten=9, ties=2)  # more than the portfolios drawn
    with pytest.raises(LuckInputError):
        _ok_outcome(excess=1)  # not a float statistic


def test_a_summary_has_exactly_one_of_interval_or_reason_and_one_of_means_or_reason():  # spec 8
    un = Unavailable(UnavailableReason.INSUFFICIENT_TRIPS)
    gone = Unavailable(UnavailableReason.NO_AVAILABLE_TRIPS)
    ok = dict(baseline=Baseline.ALT, trips_used=10, trips_unavailable=0, unavailable_counts=(), trips_evaluated=10,
              survivorship_trip_count=0,
              mean_excess=0.1, mean_percentile=0.5, mean_unavailable=None, ci_lower=0.0, ci_upper=0.2,
              position=IntervalPosition.CONTAINS_ZERO, ci_unavailable=None)
    assert BaselineSummary(**ok).position is IntervalPosition.CONTAINS_ZERO
    with pytest.raises(LuckInputError):
        BaselineSummary(**{**ok, "ci_unavailable": un})
    with pytest.raises(LuckInputError):
        BaselineSummary(**{**ok, "ci_lower": None, "ci_upper": None, "position": None, "ci_unavailable": None})
    with pytest.raises(LuckInputError):
        BaselineSummary(**{**ok, "position": None})
    # an unavailable INTERVAL keeps the point estimates; unavailable point estimates need a reason and no interval
    few = {**ok, "ci_lower": None, "ci_upper": None, "position": None, "ci_unavailable": un}
    assert BaselineSummary(**few).mean_excess == 0.1
    none = {**few, "mean_excess": None, "mean_percentile": None, "mean_unavailable": gone}
    assert BaselineSummary(**none).mean_unavailable is gone
    with pytest.raises(LuckInputError):
        BaselineSummary(**{**none, "mean_unavailable": None})  # neither means nor a reason
    with pytest.raises(LuckInputError):
        BaselineSummary(**{**few, "mean_unavailable": gone})  # both
    with pytest.raises(LuckInputError):
        BaselineSummary(**{**ok, "mean_excess": None, "mean_percentile": None, "mean_unavailable": gone})  # CI without means


def test_alternative_pick_validates_and_a_lost_pick_has_no_return():
    assert AlternativePick(1, OWN, isin(1), 0.5, None).return_ratio is None
    for kw in (dict(rank=0), dict(distance=1), dict(return_ratio=1.5)):
        with pytest.raises(LuckInputError):
            AlternativePick(**{**dict(rank=1, instrument=OWN, isin=isin(1), distance=0.5, return_ratio=None), **kw})


def test_parameters_defaults_are_the_approved_values():  # spec 3
    p = LuckParameters(seed=1, as_of=RETRIEVED)
    assert (p.portfolio_count, p.max_alternatives, p.min_alternatives, p.nifty_portfolio_size) == (500, 10, 5, 10)
    assert (p.bootstrap_replicates, p.confidence_level, p.min_trips) == (10_000, D("0.95"), 10)
    assert (p.momentum_lookback, p.volatility_lookback, p.history_needed, p.formula_version) == (20, 60, 61, "luck-v1")


def test_result_rejects_a_mismatched_schema_or_baseline():
    from luck_helpers import params, reviewed_all, world, trip
    from app.quant.luck_test.analysis import analyze_luck
    mapping, universe, members = world(14)
    r = analyze_luck([trip()], mapping, universe, members, frozenset(), params(),
                     corporate_action_reviewed=reviewed_all([trip()], universe))
    with pytest.raises(LuckInputError):
        dataclasses.replace(r, schema_version=2)
    with pytest.raises(LuckInputError):
        dataclasses.replace(r, schema_version=True)
    with pytest.raises(LuckInputError):
        dataclasses.replace(r, alt_summary=r.nifty_summary)
    assert r.schema_version == 1 and r.rng_version == "luck-rng-v1" and session(70) == r.trips[0].open_session


def test_a_result_is_unavailable_exactly_when_coverage_is_undeclared():  # spec 8
    from luck_helpers import params, reviewed_all, trip, world
    from app.quant.luck_test.analysis import analyze_luck
    mapping, universe, members = world(14)
    declared = analyze_luck([trip()], mapping, universe, members, frozenset(), params(),
                            corporate_action_reviewed=reviewed_all([trip()], universe))
    undeclared = analyze_luck([trip()], mapping, universe, members, frozenset(), params())
    assert declared.unavailable is None and undeclared.unavailable.reason is UnavailableReason.CORPORATE_ACTION_COVERAGE_UNDECLARED
    with pytest.raises(LuckInputError):
        dataclasses.replace(declared, corporate_action_coverage="UNDECLARED")  # undeclared needs its Unavailable
    with pytest.raises(LuckInputError):
        dataclasses.replace(undeclared, unavailable=None)  # ...and an Unavailable needs undeclared coverage
    with pytest.raises(LuckInputError):
        dataclasses.replace(undeclared, unavailable=Unavailable(UnavailableReason.NO_MEMBERSHIP))  # only the one reason
    with pytest.raises(LuckInputError):
        dataclasses.replace(declared, corporate_action_coverage="NOT_DECLARED")
    assert "COVERAGE_IS_A_CALLER_DECLARATION_NOT_PROOF_OF_COMPLETENESS" in declared.limitations


def _gated_and_evaluated():
    from luck_helpers import params, reviewed_all, trip, world
    from app.quant.luck_test.analysis import analyze_luck
    from app.domain.instrument import Instrument
    from app.domain.enums import Exchange
    mapping, universe, members = world(14)
    trips = [trip("OK"), trip("GATED", instrument=Instrument("NOSERIES", Exchange.NSE), trip_isin=None)]
    r = analyze_luck(trips, mapping, universe, members, frozenset(), params(), corporate_action_reviewed=reviewed_all(trips, universe))
    by = {t.trip_id: t for t in r.trips}
    return by["OK"], by["GATED"]


def test_trip_evaluation_status_invariants():  # fix 2
    ok, gated = _gated_and_evaluated()
    assert ok.evaluated is True and gated.evaluated is False
    with pytest.raises(LuckInputError):
        dataclasses.replace(gated, evaluated=True)  # an evaluated trip cannot carry a gate reason
    with pytest.raises(LuckInputError):
        dataclasses.replace(ok, evaluated=False)  # a not-evaluated trip needs the gate reason on both baselines
    with pytest.raises(LuckInputError):
        dataclasses.replace(gated, picks=ok.picks)  # not evaluated => no picks
    with pytest.raises(LuckInputError):
        dataclasses.replace(gated, zero_variance_features=("momentum",))
    with pytest.raises(LuckInputError):
        dataclasses.replace(gated, evaluated=1)  # a real bool
    with pytest.raises(LuckInputError):
        dataclasses.replace(gated, alt=dataclasses.replace(gated.alt, unavailable=Unavailable(UnavailableReason.CORPORATE_ACTION)))


def test_trip_actual_return_basis_is_fixed_to_ledger_prices_fees_excluded():  # fix 4
    ok, gated = _gated_and_evaluated()
    assert ok.actual_return_basis == gated.actual_return_basis == "LEDGER_PRICES_FEES_EXCLUDED"
    with pytest.raises(LuckInputError):
        dataclasses.replace(ok, actual_return_basis="LEDGER_PRICES_NET_OF_FEES")


def test_summary_survivorship_count_is_none_exactly_when_no_trip_was_evaluated():  # fix 2
    un = Unavailable(UnavailableReason.CORPORATE_ACTION)
    base = dict(baseline=Baseline.ALT, trips_used=0, trips_unavailable=3, unavailable_counts=(("CORPORATE_ACTION", 3),),
                trips_evaluated=0, survivorship_trip_count=None, mean_excess=None, mean_percentile=None, mean_unavailable=un,
                ci_lower=None, ci_upper=None, position=None, ci_unavailable=un)
    assert BaselineSummary(**base).survivorship_trip_count is None
    with pytest.raises(LuckInputError):
        BaselineSummary(**{**base, "survivorship_trip_count": 0})  # zero would read as "nothing lost"
    with pytest.raises(LuckInputError):
        BaselineSummary(**{**base, "trips_evaluated": 2})  # evaluated trips need a real count
    assert BaselineSummary(**{**base, "trips_evaluated": 2, "survivorship_trip_count": 0}).survivorship_trip_count == 0
