"""Feature 006 step 1: contracts, error semantics and the import boundary (spec sections 2, 3, 4, 6; plan 006 step 1)."""
import ast
import dataclasses
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app.domain.enums import Exchange, TradeSide
from app.domain.instrument import Instrument
from app.quant.backtest.config import BacktestInputError
from app.quant.backtest.config import Unavailable as BacktestUnavailable
from app.quant.bias_cost import errors, types
from app.quant.bias_cost.errors import BiasInputError, Unavailable
from app.quant.bias_cost.types import (
    BehaviourProfile, BiasAnalysisResult, BiasExclusion, BiasKind, BiasMetric, BiasParameters, BiasResult, ChargeValue,
    LedgerTrade,
)

PKG = Path(__file__).resolve().parent.parent / "app" / "quant" / "bias_cost"
UTC = timezone.utc
T0 = datetime(2026, 1, 5, 4, 0, tzinfo=UTC)


def _trade(**kw):
    base = dict(trade_id="T1", instrument=Instrument("AAA", Exchange.NSE), isin=None, side=TradeSide.BUY,
                quantity=Decimal("10"), price=Decimal("100"), trade_timestamp=T0, charges=ChargeValue.unknown())
    base.update(kw)
    return LedgerTrade(**base)


def _params(**kw):
    base = dict(chasing_lookback_sessions=5, window_start=T0, window_end=T0 + timedelta(days=30),
                formula_version="f1", rule_set_version="r1")
    base.update(kw)
    return BiasParameters(**base)


def _metric(**kw):
    base = dict(bias=BiasKind.OVERTRADING, formula_version="f1", cost_inr=Decimal("1"), unavailable=None)
    base.update(kw)
    return BiasMetric(**base)


# --- Spec 4: error semantics -------------------------------------------------------------------------------------------
def test_errors_are_local_and_independent_of_backtest():
    assert issubclass(BiasInputError, ValueError)
    assert not issubclass(BiasInputError, BacktestInputError)
    assert Unavailable is not BacktestUnavailable
    assert errors.Unavailable.__module__ == "app.quant.bias_cost.errors"


@pytest.mark.parametrize("reason", ["", "   ", "a\x00b", 3])
def test_unavailable_needs_a_real_reason(reason):
    with pytest.raises(BiasInputError):
        Unavailable(reason)


def test_unavailable_is_a_value_not_an_error():
    u = Unavailable("no closed positions")
    assert not isinstance(u, Exception) and u.reason == "no closed positions"


@pytest.mark.parametrize("kw", [
    dict(trade_id=" "), dict(isin="X"), dict(isin=""), dict(quantity=Decimal("0")), dict(quantity=1),
    dict(quantity=Decimal("NaN")), dict(price=Decimal("-1")), dict(price=1.5),
    dict(trade_timestamp=datetime(2026, 1, 5)), dict(trade_timestamp=T0.astimezone(timezone(timedelta(hours=5, minutes=30)))),
    dict(side="BUY"), dict(charges=None), dict(quantity=Decimal(10) ** 16),
])
def test_malformed_trade_raises_bias_input_error(kw):
    with pytest.raises(BiasInputError):
        _trade(**kw)


def test_valid_trade_with_isin_and_no_isin():
    assert _trade(isin="INE000A01010").isin == "INE000A01010"
    assert _trade().isin is None


@pytest.mark.parametrize("kw", [
    dict(chasing_lookback_sessions=0), dict(chasing_lookback_sessions=True), dict(chasing_lookback_sessions=2.0),
    dict(window_start=T0 + timedelta(days=99)), dict(window_end=datetime(2026, 2, 1)), dict(formula_version=""),
])
def test_malformed_parameters_raise(kw):
    with pytest.raises(BiasInputError):
        _params(**kw)


# --- Spec 3: unknown charges are never zero ------------------------------------------------------------------------------
def test_unknown_charges_carry_no_numbers_and_cannot_be_zero():
    c = ChargeValue.unknown()
    assert c.known is False and c.fees is None and c.taxes is None
    with pytest.raises(BiasInputError):
        ChargeValue(known=False, fees=Decimal("0"), taxes=Decimal("0"))
    with pytest.raises(BiasInputError):
        ChargeValue(known=True)  # known charges must state both amounts
    with pytest.raises(BiasInputError):
        ChargeValue(known=True, fees=Decimal("-1"), taxes=Decimal("0"))
    with pytest.raises(BiasInputError):
        ChargeValue(known=True, fees=1.0, taxes=Decimal("0"))
    assert ChargeValue(known=True, fees=Decimal("0"), taxes=Decimal("0")).known


# --- Spec 3/4: metric is a cost or Unavailable, never both, never zero-by-default ------------------------------------------
def test_metric_is_exactly_cost_or_unavailable():
    assert _metric().cost_inr == Decimal("1")
    assert _metric(cost_inr=None, unavailable=Unavailable("none eligible")).cost_inr is None
    with pytest.raises(BiasInputError):
        _metric(cost_inr=None, unavailable=None)
    with pytest.raises(BiasInputError):
        _metric(unavailable=Unavailable("x"))
    with pytest.raises(BiasInputError):
        _metric(cost_inr=Decimal("NaN"))
    with pytest.raises(BiasInputError):
        _metric(cost_inr=1.0)
    with pytest.raises(BiasInputError):
        _metric(cost_inr=None, unavailable=Unavailable("x"), is_lower_bound=True)
    assert _metric(is_lower_bound=True).is_lower_bound


def test_result_profile_and_analysis_shapes():
    result = BiasResult(metric=_metric(exclusions=(BiasExclusion("T1", "unknown charge"),)), parameters=_params(),
                        input_fingerprint="abc")
    profile = BehaviourProfile("BALANCED", "r1", (("a", "1"), ("b", "2")), "abc")
    analysis = BiasAnalysisResult(results=(result,), profile=profile, exclusions=(), input_fingerprint="abc")
    assert analysis.schema_version == types.SCHEMA_VERSION == result.schema_version
    assert BiasAnalysisResult((), Unavailable("blocked: rules unapproved"), (), "abc").profile.reason
    with pytest.raises(BiasInputError):
        BiasAnalysisResult((result, result), profile, (), "abc")  # one result per bias
    with pytest.raises(BiasInputError):
        BiasAnalysisResult([result], profile, (), "abc")  # tuples only
    with pytest.raises(BiasInputError):
        BiasAnalysisResult((), None, (), "abc")
    with pytest.raises(BiasInputError):
        BehaviourProfile("BALANCED", "r1", (("b", "2"), ("a", "1")), "abc")  # must be sorted
    with pytest.raises(BiasInputError):
        BehaviourProfile("BALANCED", "r1", (("a", "1"), ("a", "2")), "abc")  # must be unique


# --- Spec 2/3: immutability and Decimal-only money ------------------------------------------------------------------------
PUBLIC = (ChargeValue, LedgerTrade, BiasParameters, BiasExclusion, BiasMetric, BiasResult, BehaviourProfile,
          BiasAnalysisResult, Unavailable)


def test_public_types_are_frozen_dataclasses():
    for cls in PUBLIC:
        assert dataclasses.is_dataclass(cls) and cls.__dataclass_params__.frozen, cls.__name__
    with pytest.raises(dataclasses.FrozenInstanceError):
        _trade().price = Decimal("1")


def test_no_float_annotations_on_financial_fields():
    for cls in PUBLIC:
        for f in dataclasses.fields(cls):
            assert "float" not in str(f.type), f"{cls.__name__}.{f.name}"


# --- Spec 6: import boundary (this package) -------------------------------------------------------------------------------
def _nodes(path):
    return list(ast.walk(ast.parse(path.read_text(encoding="utf-8"))))


def test_package_imports_only_stdlib_domain_and_siblings_via_relative_imports():
    files = sorted(PKG.glob("*.py"))
    assert {p.name for p in files} >= {"__init__.py", "errors.py", "types.py"}
    for path in files:
        for node in _nodes(path):
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    assert node.level == 1, f"{path.name}: parent-relative import"
                    continue
                name = node.module or ""
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
                assert all(n.split(".")[0] in sys.stdlib_module_names for n in names), f"{path.name} imports {names}"
                continue
            else:
                continue
            ok = name.split(".")[0] in sys.stdlib_module_names or name == "app.domain" or name.startswith("app.domain.")
            ok = ok or name == "app.quant.market_data" or name.startswith("app.quant.market_data.")  # Feature 006 plan section 2
            assert ok, f"{path.name} imports {name}"


def test_package_never_depends_on_backtest_or_upper_layers():
    banned = ("app.quant.backtest", "app.providers", "app.services", "app.api", "app.models", "app.repositories", "app.db",
              "app.schemas", "app.ai", "sqlalchemy", "httpx", "fastapi", "pydantic")
    for path in PKG.glob("*.py"):
        for node in _nodes(path):
            mods = []
            if isinstance(node, ast.ImportFrom):
                mods = [("." * node.level) + (node.module or "")]
            elif isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            for m in mods:
                assert "backtest" not in m, f"{path.name} reaches backtest via {m}"
                assert not m.startswith(banned), f"{path.name} imports {m}"


def test_package_has_no_float_clock_or_randomness():
    for path in PKG.glob("*.py"):
        for node in _nodes(path):
            assert not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "float"), path.name
            assert not (isinstance(node, ast.Constant) and isinstance(node.value, float)), path.name
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                assert not {m.split(".")[0] for m in mods} & {"random", "secrets", "time"}, path.name
            if isinstance(node, ast.Attribute) and node.attr in {"now", "utcnow", "today"}:
                raise AssertionError(f"{path.name} reads the clock via .{node.attr}")


# --- Step 1 validation follow-up (spec sections 2, 3, 4, 5) ---------------------------------------------------------------
def test_known_zero_charges_are_distinct_from_unknown_charges():  # spec 3
    zero = ChargeValue(known=True, fees=Decimal("0"), taxes=Decimal("0"))
    unknown = ChargeValue.unknown()
    assert zero != unknown and hash(zero) != hash(unknown)
    assert zero.known is True and unknown.known is False
    assert zero.fees == Decimal("0") and unknown.fees is None
    assert _trade(charges=zero) != _trade(charges=unknown)


def test_result_rejects_metric_with_a_different_formula_version_than_its_parameters():  # spec 5
    ok = BiasResult(metric=_metric(formula_version="f1"), parameters=_params(formula_version="f1"), input_fingerprint="abc")
    assert ok.metric.formula_version == ok.parameters.formula_version
    with pytest.raises(BiasInputError):
        BiasResult(metric=_metric(formula_version="f2"), parameters=_params(formula_version="f1"), input_fingerprint="abc")


def _result(fp="abc", **param_kw):
    return BiasResult(metric=_metric(), parameters=_params(**param_kw), input_fingerprint=fp)


def test_analysis_results_must_share_parameters():  # spec 5
    a = _result()
    b = BiasResult(metric=_metric(bias=BiasKind.CHASING), parameters=_params(), input_fingerprint="abc")
    assert len(BiasAnalysisResult((a, b), Unavailable("rules unapproved"), (), "abc").results) == 2
    other_params = BiasResult(metric=_metric(bias=BiasKind.CHASING), parameters=_params(chasing_lookback_sessions=9),
                              input_fingerprint="abc")
    with pytest.raises(BiasInputError):
        BiasAnalysisResult((a, other_params), Unavailable("x"), (), "abc")


def test_per_bias_and_profile_fingerprints_may_differ_from_each_other_and_the_analysis():  # spec 7 (test 11)
    a = _result(fp="disposition-fp")
    b = BiasResult(metric=_metric(bias=BiasKind.CHASING), parameters=_params(), input_fingerprint="chasing-fp")
    profile = BehaviourProfile("BALANCED", "r1", (), "profile-fp")
    analysis = BiasAnalysisResult((a, b), profile, (), "overall-fp")
    assert {r.input_fingerprint for r in analysis.results} == {"disposition-fp", "chasing-fp"}
    assert analysis.profile.input_fingerprint == "profile-fp" and analysis.input_fingerprint == "overall-fp"
    with pytest.raises(BiasInputError):
        BiasAnalysisResult((a,), Unavailable("x"), (), "")  # a fingerprint must still be real text


def test_analysis_profile_must_match_rule_set_version():  # spec 5
    a = _result()
    assert BiasAnalysisResult((a,), BehaviourProfile("BALANCED", "r1", (), "abc"), (), "abc")
    with pytest.raises(BiasInputError):
        BiasAnalysisResult((a,), BehaviourProfile("BALANCED", "r2", (), "abc"), (), "abc")


@pytest.mark.parametrize("bad", [True, False, 0, 2, 1.0, "1", None])
def test_schema_version_must_be_the_exact_int_and_never_a_bool(bad):  # spec 2
    with pytest.raises(BiasInputError):
        BiasResult(metric=_metric(), parameters=_params(), input_fingerprint="abc", schema_version=bad)
    with pytest.raises(BiasInputError):
        BiasAnalysisResult((), Unavailable("x"), (), "abc", schema_version=bad)
    assert BiasResult(metric=_metric(), parameters=_params(), input_fingerprint="abc", schema_version=1)


def test_cost_inr_is_never_rounded_silently_and_has_no_invented_sign_or_magnitude_rule():  # spec 2
    assert _metric(cost_inr=Decimal("0.123456")).cost_inr == Decimal("0.123456")
    assert _metric(cost_inr=Decimal("100")).cost_inr == Decimal("100")
    # SUPERSEDED by the owner decision of 2026-10-14 (spec 2/3): internal values stay exact, only presentation quantizes.
    # This assertion used to require a rejection of more than 6 decimal places.
    assert _metric(cost_inr=Decimal("0.1234567")).cost_inr == Decimal("0.1234567")
    # Sign and magnitude are unspecified (open blocker): negative and large values are accepted, not guessed at.
    assert _metric(cost_inr=Decimal("-5")).cost_inr == Decimal("-5")
    assert _metric(cost_inr=Decimal("1E+20")).cost_inr == Decimal("1E+20")


@pytest.mark.parametrize("isin", ["!!!!!!!!!!!!", "ine000a01010", "INE000A0101", "INE000A010101", " INE000A0101", "INE000A0101 ",
                                  "INE000A0101\n", "INÉ000A01010", "INE-00A01010", ""])
def test_malformed_isin_is_rejected_and_never_normalized(isin):  # spec 3
    with pytest.raises(BiasInputError):
        _trade(isin=isin)


@pytest.mark.parametrize("isin", [123, 123456789012, b"INE000A01010", ["INE000A01010"], 1.5])
def test_non_string_isin_is_rejected(isin):  # spec 3
    with pytest.raises(BiasInputError):
        _trade(isin=isin)


def test_well_formed_isin_is_kept_verbatim():  # spec 3
    assert _trade(isin="INE000A01010").isin == "INE000A01010"
    assert _trade(isin="US0378331005").isin == "US0378331005"


@pytest.mark.parametrize("trade_id", [" T1", "T1 ", "T 1", "T1\n", "\nT1", "T1\r\n", "T\t1", "T1\u00a0", "T\u20031", "a\nb", "T\x001"])
def test_trade_id_rejects_any_whitespace_or_control_text(trade_id):  # spec 5
    with pytest.raises(BiasInputError):
        _trade(trade_id=trade_id)


def test_trade_id_accepts_plain_identifiers():  # spec 5
    for ok in ("T1", "ZRD-2026/0001", "a_b.c:9"):
        assert _trade(trade_id=ok).trade_id == ok
    with pytest.raises(BiasInputError):
        _trade(trade_id="x" * 129)
