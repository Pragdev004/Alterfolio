"""Feature 013a: turns the plain analysis read types into JSON bodies. Every number is {value, display, unavailable_reason}.

All rounding and wording happens here and in `domain/display.py`; the frontend renders `display` and formats nothing. Nothing here
computes a statistic, and a missing value is never turned into 0 (spec 013a section 4).
"""

from datetime import date

from app.domain import display as fmt
from app.services.analysis_read import MetaView
from app.services.analysis_view import (
    AnalysisView, BiasView, BlockView, GroupView, HistogramView, Num, OutcomeView, ProfileView, RegimeTagView, Sample, SummaryView,
    TripView, alternatives_presentation,
)

ALTERNATIVES_NOTE = "Same-sector or same-universe alternatives, not a prediction."


def _text(reason: str | None) -> str | None:
    """The plain-English sentence for a reason (None stays None)."""
    return fmt.reason_text(reason) if reason else None


def _num(n: Num) -> dict:
    return fmt.number(n.value, n.kind, n.reason or None)


def _count(n: int | None, reason: str) -> dict:
    return fmt.number(None if n is None else str(n), "count", reason)


def _sample(s: Sample) -> dict:
    if s.have is None:  # the analysis did not run: never a count of 0
        return {"have": None, "needed": s.needed, "enough": False, "text": fmt.UNAVAILABLE}
    return {"have": s.have, "needed": s.needed, "enough": s.enough, "text": "" if s.enough else f"{s.have} trips · {s.needed} needed"}


def _summary(s: SummaryView) -> dict:
    return {"trips_used": s.trips_used, "trips_evaluated": s.trips_evaluated, "mean_excess": _num(s.mean_excess),
            "mean_percentile": _num(s.mean_percentile), "ci_lower": _num(s.ci_lower), "ci_upper": _num(s.ci_upper),
            "position": s.position, "sample": _sample(s.sample), "mean_excess_direction": s.mean_excess_direction}


def _summaries(d: dict[str, SummaryView]) -> dict:
    return {b: _summary(s) for b, s in d.items()}


def _outcome(o: OutcomeView | None) -> dict | None:
    if o is None:
        return None
    return {"percentile": _num(o.percentile), "excess": _num(o.excess), "mean_return": _num(o.mean_return),
            "portfolio_count": o.portfolio_count, "pool_size": o.pool_size, "lost_count": o.lost_count,
            "unavailable_reason": o.reason or None, "reason_text": _text(o.reason), "excess_direction": o.excess_direction}


def _histogram(h: HistogramView | None) -> dict | None:
    if h is None:
        return None
    return {"bins": [{"lower": _num(b.lower), "upper": _num(b.upper), "count": b.count} for b in h.bins], "marker_bin": h.marker_bin,
            "actual_return": _num(h.actual_return), "lower": _num(h.lower), "upper": _num(h.upper),
            "portfolio_count": h.portfolio_count, "text": h.text}


def _regime_tag(r: RegimeTagView) -> dict:
    return {"regime": r.regime, "volatility": _num(r.volatility), "low_threshold": _num(r.low_threshold),
            "high_threshold": _num(r.high_threshold), "calibration_count": r.calibration_count, "reason": r.reason or None,
            "reason_text": _text(r.reason)}


def _alternatives(label: str | None) -> dict:
    if label is None:
        return {"alternatives_kind": None, "alternatives_label": None}
    kind, text = alternatives_presentation(label)
    return {"alternatives_kind": kind, "alternatives_label": text}


def _trip(t: TripView, *, detail: bool = False) -> dict:
    row = {"trip_id": t.trip_id, "symbol": t.symbol, "exchange": t.exchange, "open_session": fmt.date_object(t.open_session),
           "close_session": fmt.date_object(t.close_session), "evaluated": t.evaluated, "actual_return": _num(t.actual_return),
           "actual_return_basis": "LEDGER_PRICES_FEES_EXCLUDED", **_alternatives(t.stored_label), "alt": _outcome(t.alt),
           "nifty": _outcome(t.nifty), "survivorship_flag": t.survivorship_flag, "regime": _regime_tag(t.regime),
           "unavailable_reason": t.unavailable_reason or None, "reason_text": _text(t.unavailable_reason)}
    if detail:
        row["histograms"] = {"ALT": _histogram(None if t.alt is None else t.alt.histogram),
                             "NIFTY": _histogram(None if t.nifty is None else t.nifty.histogram)}
        row["picks"] = [{"rank": p.rank, "symbol": p.symbol, "exchange": p.exchange, "isin": p.isin, "return_ratio": _num(p.return_ratio)}
                        for p in t.picks]
        row["exclusions"] = [{"baseline": b, "isin": i, "symbol": sym, "exchange": ex, "reason": r, "reason_text": _text(r)}
                             for b, i, r, sym, ex in t.exclusions]
        row["zero_variance_features"] = list(t.zero_variance_features)
    return row


def _group(g: GroupView) -> dict:
    return {"label": g.label, **_alternatives(g.label), "trip_count": g.trip_count, **_summaries(g.summaries)}


def _bias(b: BiasView) -> dict:
    return {"kind": b.kind, "cost_inr": _num(b.cost), "gross_cost_inr": _num(b.gross_cost), "fees_known": _num(b.fees_known),
            "fee_status": b.fee_status, "unknown_fee_trade_count": b.unknown_fee_trade_count,
            "exclusions": [{"subject": s, "reason": r, "reason_text": _text(r)} for s, r in b.exclusions], "details": [{"name": k, "value": v} for k, v in b.details]}


def _profile(p: ProfileView) -> dict:
    return {"archetype_id": p.archetype_id, "unavailable_reason": p.reason or None, "reason_text": _text(p.reason),
            "supporting_metrics": [{"name": n, "value": v, "display": v, "unit": "unitless"} for n, v in p.metrics]}


def _block(b: BlockView) -> dict:
    return {"regime": b.regime, "trip_ids": list(b.trip_ids), "trip_count": b.sample.have, "sample": _sample(b.sample),
            "luck": None if b.luck is None else _summaries(b.luck), "luck_unavailable_reason": b.luck_reason or None,
            "luck_reason_text": _text(b.luck_reason),
            "bias": None if b.bias is None else [_bias(x) for x in b.bias], "bias_unavailable_reason": b.bias_reason or None,
            "bias_reason_text": _text(b.bias_reason)}


def _head(as_of: date, defaulted: bool) -> dict:
    return {"as_of": fmt.date_object(as_of), "as_of_defaulted": defaulted}


def _errors(v: AnalysisView) -> list[dict]:
    return [{"analysis": a, "reason": r, "reason_text": _text(r)} for a, r in v.errors]


def meta(m: MetaView) -> dict:
    t = m.thresholds
    return {
        "latest_sealed_as_of": fmt.date_object(m.latest_sealed_as_of), "today_ist": fmt.date_object(m.today_ist),
        "last_bar_date": None if m.last_bar_date is None else fmt.date_object(m.last_bar_date),
        "last_bar_date_unavailable_reason": m.last_bar_reason or None, "last_bar_date_reason_text": _text(m.last_bar_reason),
        "thresholds": {"luck_min_trips": _count(t.luck_min_trips, ""),
                       "regime_min_trips_per_regime": _count(t.regime_min_trips_per_regime, ""),
                       "bias_min_round_trips": _count(t.bias_min_round_trips, "")},
        "alternatives_note": ALTERNATIVES_NOTE,
        "limitations": {"luck": list(m.luck_limitations), "regime": list(m.regime_limitations)},
    }


def trips(v: AnalysisView, defaulted: bool) -> dict:
    return {
        **_head(v.as_of, defaulted),
        "summary": {"trip_count": v.trip_count, "trip_count_unavailable_reason": None if v.trip_count is not None else (v.luck_reason or "not available"),
                    "trip_count_reason_text": None if v.trip_count is not None else _text(v.luck_reason or "not available"),
                    "trips_evaluated": v.summaries["ALT"].trips_evaluated, **_alternatives(v.facts_label), **_summaries(v.summaries)},
        "groups": [_group(g) for g in v.groups],
        "trips": [_trip(t) for t in v.trips],
        "excluded_listings": [{"symbol": s, "exchange": e, "reason": why, "reason_text": _text(why), "trips": n}
                              for s, e, why, n in v.excluded_listings],
        "caveats": list(v.caveats), "analysis_errors": _errors(v),
        "luck_limitations": list(v.luck_limitations), "alternatives_note": ALTERNATIVES_NOTE,
    }


def trip_detail(v: AnalysisView, trip: TripView, defaulted: bool) -> dict:
    return {**_head(v.as_of, defaulted), "trip": _trip(trip, detail=True), "caveats": list(v.caveats),
            "alternatives_note": ALTERNATIVES_NOTE}


def regimes(v: AnalysisView, defaulted: bool) -> dict:
    r = v.regime
    return {
        **_head(v.as_of, defaulted),
        "round_trip_count": None if r.round_trip_count is None else int(r.round_trip_count),
        "unclassified_count": None if r.unclassified_count is None else int(r.unclassified_count),
        "blocks": [_block(b) for b in r.blocks],
        "exclusions": [{"subject": s, "reason": why, "reason_text": _text(why)} for s, why in r.exclusions],
        "unavailable_reason": r.reason or None, "reason_text": _text(r.reason), "none_ready_text": r.none_ready_text,
        "limitations": list(r.limitations),
        "caveats": list(v.caveats), "analysis_errors": _errors(v),
    }


def biases(v: AnalysisView, defaulted: bool) -> dict:
    return {**_head(v.as_of, defaulted), "biases": [_bias(b) for b in v.biases], "profile": _profile(v.profile),
            "sample": _sample(v.bias_sample), "caveats": list(v.caveats), "analysis_errors": _errors(v)}
