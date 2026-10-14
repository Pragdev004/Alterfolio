"""Orchestration: validate -> fold -> three metrics -> archetype, with per-metric fingerprints (spec sections 2, 5)."""

from collections.abc import Iterable, Mapping

from app.domain.instrument import Instrument
from app.quant.market_data.series import MarketSeries

from .calculations import (
    ChasingFacts, DispositionFacts, OvertradingFacts, calculate_chasing, calculate_disposition, calculate_overtrading,
    listing_provenance,
)
from .cost_basis import fold_positions
from .errors import Unavailable
from .fingerprint import analysis_fingerprint, metric_fingerprint, profile_fingerprint
from .profile import classify_behaviour
from .types import (
    FORMULA_VERSION, BiasAnalysisResult, BiasKind, BiasMetric, BiasParameters, BiasResult, LedgerTrade,
)
from .validation import ValidatedBiasInputs, listing_name, validate_inputs

_KINDS = (BiasKind.DISPOSITION, BiasKind.CHASING, BiasKind.OVERTRADING)


def _all_unavailable(inputs: ValidatedBiasInputs, reason: str) -> tuple[BiasMetric, ...]:
    return tuple(
        BiasMetric(k, FORMULA_VERSION, None, Unavailable(reason), listings=listing_provenance(inputs)) for k in _KINDS
    )


def analyze_biases(
    trades: Iterable[LedgerTrade],
    series: Mapping[Instrument, MarketSeries],
    parameters: BiasParameters,
    corporate_action_listings: frozenset[Instrument] = frozenset(),
) -> BiasAnalysisResult:
    inputs = validate_inputs(trades, series, parameters, corporate_action_listings)
    exclusions = list(inputs.exclusions)
    facts: tuple[DispositionFacts, ChasingFacts, OvertradingFacts] | None = None
    if inputs.missing_series:
        names = ", ".join(listing_name(i) for i in inputs.missing_series)
        metrics = _all_unavailable(inputs, f"missing series for listing(s): {names}; no other exchange is substituted")
    elif not inputs.trades:
        metrics = _all_unavailable(inputs, "no eligible trades")
    else:
        fold = fold_positions(inputs)
        exclusions.extend(fold.exclusions)
        disposition, d_facts = calculate_disposition(inputs, fold)
        chasing, c_facts = calculate_chasing(inputs)
        overtrading, o_facts = calculate_overtrading(inputs, fold)
        metrics = (disposition, chasing, overtrading)
        facts = (d_facts, c_facts, o_facts)
    results = tuple(
        BiasResult(m, parameters, metric_fingerprint(m.bias, inputs)) for m in metrics
    )
    fingerprints = [r.input_fingerprint for r in results]
    if facts is None:
        profile: object = Unavailable("no computable metrics: " + (metrics[0].unavailable.reason))
        profile_fp = profile_fingerprint(fingerprints, inputs)
    else:
        profile_fp = profile_fingerprint(fingerprints, inputs)
        profile = classify_behaviour(facts[2], facts[1], facts[0], parameters, profile_fp)
    return BiasAnalysisResult(
        results=results, profile=profile, exclusions=tuple(exclusions),
        input_fingerprint=analysis_fingerprint(fingerprints + [profile_fp], inputs),
    )
