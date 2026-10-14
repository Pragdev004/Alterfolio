"""Orchestration: validate -> round trips -> label -> per-regime Feature 007 and 006 (spec sections 4-7).

Features 006 and 007 are called unchanged. Labels, thresholds, counts and exclusions never depend on the minimum; only the
regime-level aggregates (the 007 result and the 006 result) are withheld below `min_trips_per_regime`.
"""

import hashlib
import json
from collections.abc import Iterable, Mapping

from app.domain.instrument import Instrument
from app.quant.bias_cost.analysis import analyze_biases
from app.quant.bias_cost.cost_basis import fold_positions
from app.quant.bias_cost.types import BiasParameters, LedgerTrade
from app.quant.bias_cost.validation import listing_name, validate_inputs
from app.quant.luck_test.analysis import analyze_luck
from app.quant.luck_test.features import ListingBars
from app.quant.luck_test.fingerprint import input_fingerprint as luck_input_fingerprint
from app.quant.luck_test.types import Candidate, LuckParameters, Membership
from app.quant.market_data.fingerprint import canonical_decimal, iso_utc
from app.quant.market_data.series import MarketSeries

from .classify import Label, ListingClassifier
from .errors import RegimeInputError, Unavailable, UnavailableReason
from .trips import MappedTrip, map_round_trips
from .types import FORMULA_VERSION, SCHEMA_VERSION, Regime, RegimeBlock, RegimeParameters, RegimeResult, TripRegime

FINGERPRINT_VERSION = 1
_ORDER = (Regime.LOW, Regime.NORMAL, Regime.HIGH)


def _trade_row(t: LedgerTrade) -> list[object]:
    c = t.charges
    return [t.trade_id, t.instrument.symbol, t.instrument.exchange.value, t.isin, t.side.value, canonical_decimal(t.quantity),
            canonical_decimal(t.price), iso_utc(t.trade_timestamp),
            [c.known, None if c.fees is None else canonical_decimal(c.fees), None if c.taxes is None else canonical_decimal(c.taxes)]]


def _bias_params(p: BiasParameters) -> dict:
    return {
        "chasing_lookback_sessions": p.chasing_lookback_sessions, "window": [iso_utc(p.window_start), iso_utc(p.window_end)],
        "formula_version": p.formula_version, "rule_set_version": p.rule_set_version, "forward_sessions": p.forward_sessions,
        "chase_threshold": canonical_decimal(p.chase_threshold), "short_term_sessions": p.short_term_sessions,
        "min_round_trips": p.min_round_trips, "churner_share": canonical_decimal(p.churner_share),
        "chaser_share": canonical_decimal(p.chaser_share), "disposition_threshold": canonical_decimal(p.disposition_threshold),
    }


def _fingerprint(
    parameters: RegimeParameters, trades: Iterable[LedgerTrade], bias_parameters: BiasParameters, luck_fingerprint: str,
) -> str:
    payload = {
        "v": FINGERPRINT_VERSION, "schema": SCHEMA_VERSION, "formula": FORMULA_VERSION, "regime": parameters.to_dict(),
        "bias_trades": sorted(_trade_row(t) for t in trades), "bias_params": _bias_params(bias_parameters),
        "luck": luck_fingerprint,
    }
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def _trip_regime(mapped: MappedTrip, label: Label | None) -> TripRegime:
    t = mapped.trip
    if label is None:  # excluded before labelling (ambiguous ISIN)
        return TripRegime(t.trip_id, t.instrument, t.open_session, t.close_session, None, None, None, None, None,
                          mapped.unavailable)
    return TripRegime(t.trip_id, t.instrument, t.open_session, t.close_session, label.regime, label.volatility,
                      label.low_threshold, label.high_threshold, label.calibration_count, label.unavailable)


def analyze_regimes(
    trades: Iterable[LedgerTrade],
    series: Mapping[Instrument, MarketSeries],
    universe: Iterable[Candidate],
    nifty50: Iterable[Membership],
    corporate_action_listings: frozenset[Instrument],
    bias_parameters: BiasParameters,
    luck_parameters: LuckParameters,
    parameters: RegimeParameters,
    *,
    corporate_action_reviewed: frozenset[Instrument] | None = None,
) -> RegimeResult:
    if not isinstance(parameters, RegimeParameters):
        raise RegimeInputError("parameters must be RegimeParameters")
    if not isinstance(luck_parameters, LuckParameters):
        raise RegimeInputError("luck_parameters must be LuckParameters")
    ledger = tuple(trades)
    universe_t, nifty_t = tuple(universe), tuple(nifty50)
    validated = validate_inputs(ledger, series, bias_parameters, corporate_action_listings)

    unavailable: Unavailable | None = None
    mapped: tuple[MappedTrip, ...] = ()
    if validated.missing_series:
        names = ", ".join(listing_name(i) for i in validated.missing_series)
        unavailable = Unavailable(UnavailableReason.NO_TRIP_SERIES, f"missing series for listing(s): {names}")
    elif validated.trades:
        mapped = map_round_trips(fold_positions(validated).round_trips)

    classifiers: dict[Instrument, ListingClassifier] = {}
    rows: list[tuple[MappedTrip, TripRegime]] = []
    for m in mapped:
        if m.unavailable is not None:
            rows.append((m, _trip_regime(m, None)))
            continue
        inst = m.trip.instrument
        if inst not in classifiers:
            classifiers[inst] = ListingClassifier(ListingBars.build(series[inst]), parameters)
        rows.append((m, _trip_regime(m, classifiers[inst].label(m.trip.open_session))))
    rows.sort(key=lambda r: (r[1].open_session, r[1].close_session, r[1].trip_id))

    blocks: list[RegimeBlock] = []
    for regime in _ORDER:
        members = [m for m, tr in rows if tr.regime is regime]
        ids = tuple(m.trip.trip_id for m in members)
        if len(members) < parameters.min_trips_per_regime:
            gate = Unavailable(UnavailableReason.INSUFFICIENT_TRIPS_IN_REGIME,
                               f"{len(members)} classified trips, need {parameters.min_trips_per_regime}")
            blocks.append(RegimeBlock(regime, ids, gate, gate))
            continue
        luck = analyze_luck([m.trip for m in members], series, universe_t, nifty_t, corporate_action_listings,
                            luck_parameters, corporate_action_reviewed=corporate_action_reviewed)
        bias = analyze_biases([t for m in members for t in m.round_trip.trades], series, bias_parameters,
                              corporate_action_listings)
        blocks.append(RegimeBlock(regime, ids, luck, bias))

    used = {m.trip.instrument for m in mapped} | {c.instrument for c in universe_t}
    luck_fp = luck_input_fingerprint(
        [m.trip for m in mapped],
        [(i.symbol, i.exchange.value, series[i].fingerprint) for i in sorted(used, key=lambda i: (i.symbol, i.exchange.value))
         if i in series],
        universe_t, nifty_t, corporate_action_listings, luck_parameters, corporate_action_reviewed)
    exclusions = tuple((e.subject, e.reason) for e in validated.exclusions)
    return RegimeResult(
        parameters=parameters, as_of=luck_parameters.as_of, round_trip_count=len(rows), trips=tuple(tr for _, tr in rows),
        blocks=tuple(blocks), exclusions=exclusions, unavailable=unavailable,
        input_fingerprint=_fingerprint(parameters, ledger, bias_parameters, luck_fp),
    )
