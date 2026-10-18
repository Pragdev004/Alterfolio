"""Feature 013a: plain read types for the analysis endpoints, built from the retained quant results of one run.

No statistic is computed here. Quant floats become canonical decimal text once (the 011 rule), missing values keep their reason,
and nothing is turned into 0. The API layer formats these values for display (`app/api/analysis_presenter.py`).
"""

import re
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.domain.display import direction, interval_direction
from app.quant.bias_cost.types import BiasAnalysisResult
from app.quant.luck_test.types import BaselineOutcome, BaselineSummary, LuckResult
from app.quant.market_data.fingerprint import canonical_decimal
from app.quant.regime_split.types import RegimeResult
from app.services.portfolio_analysis import AnalysisDetail, Thresholds
from app.services.portfolio_analysis import _stat as stat_text
from app.services.portfolio_analysis import _why as why_text

BASELINES = ("ALT", "NIFTY")
HISTOGRAM_BINS = 20
_SECTOR_LABEL = re.compile(r"^alternatives: (.*) \((\d+)\)$")


def alternatives_presentation(label: str | None) -> tuple[str, str]:
    """(kind, text) from the stored 014 label: 'alternatives: NIFTY BANK (3)' is same-sector, the static universe is same-universe.
    The stored label is unchanged (approved 014 tests pin it); only what the reader sees is reworded."""
    if label is None or label.startswith("alternatives: static universe"):
        return "SAME_UNIVERSE", "Same-universe alternatives"
    m = _SECTOR_LABEL.match(label)
    if m:
        return "SAME_SECTOR", f"Same-sector alternatives ({m.group(1)}, {m.group(2)})"
    return "SAME_SECTOR", f"Same-sector alternatives ({label.removeprefix('alternatives: ')})"


@dataclass(frozen=True)
class Num:
    """A value as exact canonical text (None = unavailable, with a reason) and how to display it (`domain.display` kinds)."""

    value: str | None
    kind: str
    reason: str = ""


@dataclass(frozen=True)
class Sample:
    have: int | None  # None = the analysis did not run (never shown as 0)
    needed: int

    @property
    def enough(self) -> bool:
        return self.have is not None and self.have >= self.needed


@dataclass(frozen=True)
class SummaryView:
    trips_used: int | None
    trips_evaluated: int | None
    mean_excess: Num
    mean_percentile: Num
    ci_lower: Num
    ci_upper: Num
    position: str | None
    sample: Sample
    mean_excess_direction: str | None = None


@dataclass(frozen=True)
class BinView:
    lower: Num
    upper: Num
    count: int


@dataclass(frozen=True)
class HistogramView:
    """The drawn portfolios' returns counted into equal-width bins, with the trip's own return placed among them."""

    bins: tuple[BinView, ...]
    marker_bin: int
    actual_return: Num
    lower: Num
    upper: Num
    portfolio_count: int
    text: str


@dataclass(frozen=True)
class OutcomeView:
    percentile: Num
    excess: Num
    mean_return: Num
    portfolio_count: int | None  # None when the outcome is unavailable (never 0)
    pool_size: int | None
    lost_count: int | None
    reason: str
    excess_direction: str | None = None
    histogram: HistogramView | None = None


@dataclass(frozen=True)
class PickView:
    rank: int
    symbol: str
    exchange: str
    isin: str
    return_ratio: Num


@dataclass(frozen=True)
class RegimeTagView:
    regime: str | None
    volatility: Num
    low_threshold: Num
    high_threshold: Num
    calibration_count: int | None
    reason: str


@dataclass(frozen=True)
class TripView:
    trip_id: str
    symbol: str
    exchange: str
    open_session: date
    close_session: date
    evaluated: bool
    actual_return: Num
    stored_label: str | None
    alt: OutcomeView | None
    nifty: OutcomeView | None
    survivorship_flag: bool | None
    picks: tuple[PickView, ...]
    exclusions: tuple[tuple[str, str, str, str | None, str | None], ...]  # (baseline, isin, reason, symbol, exchange)
    zero_variance_features: tuple[str, ...]
    regime: RegimeTagView
    unavailable_reason: str


@dataclass(frozen=True)
class GroupView:
    label: str
    trip_count: int
    summaries: dict[str, SummaryView]


@dataclass(frozen=True)
class BiasView:
    kind: str
    cost: Num
    gross_cost: Num
    fees_known: Num
    fee_status: str | None
    unknown_fee_trade_count: int | None
    exclusions: tuple[tuple[str, str], ...]
    details: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ProfileView:
    archetype_id: str | None
    reason: str
    metrics: tuple[tuple[str, str], ...]  # (name, canonical text); units are not declared by the quant, so none is guessed


@dataclass(frozen=True)
class BlockView:
    regime: str
    trip_ids: tuple[str, ...]
    sample: Sample
    luck: dict[str, SummaryView] | None
    luck_reason: str
    bias: tuple[BiasView, ...] | None
    bias_reason: str


@dataclass(frozen=True)
class RegimeView:
    round_trip_count: str | None  # as the fact text
    unclassified_count: str | None
    blocks: tuple[BlockView, ...]
    exclusions: tuple[tuple[str, str], ...]
    reason: str
    limitations: tuple[str, ...]
    none_ready_text: str | None = None


@dataclass(frozen=True)
class AnalysisView:
    as_of: date
    thresholds: Thresholds
    trip_count: int | None
    facts_label: str | None
    summaries: dict[str, SummaryView]
    luck_reason: str
    groups: tuple[GroupView, ...]
    trips: tuple[TripView, ...]
    excluded_listings: tuple[tuple[str, str, str, int], ...]
    caveats: tuple[str, ...]
    errors: tuple[tuple[str, str], ...]
    regime: RegimeView
    biases: tuple[BiasView, ...]
    profile: ProfileView
    bias_sample: Sample
    luck_limitations: tuple[str, ...]


def _num(value: float | None, kind: str, reason: str) -> Num:
    text = stat_text(value)
    return Num(text, kind, "" if text is not None else reason or "not available")


def _dec(value, kind: str, reason: str) -> Num:
    return Num(None, kind, reason or "not available") if value is None else Num(canonical_decimal(value), kind)


def _summary(s: BaselineSummary | None, gate: str, needed: int, why: str) -> SummaryView:
    if s is None:
        miss = why or "not computed"
        return SummaryView(None, None, Num(None, "ratio", miss), Num(None, "ratio", miss), Num(None, "ratio", miss),
                           Num(None, "ratio", miss), None, Sample(None, needed))
    mean_why = gate or (why_text(s.mean_unavailable) if s.mean_unavailable else "")
    ci_why = gate or (why_text(s.ci_unavailable) if s.ci_unavailable else "")
    mean_excess = _num(s.mean_excess, "ratio", mean_why)
    ci_lo, ci_hi = _num(s.ci_lower, "ratio", ci_why), _num(s.ci_upper, "ratio", ci_why)
    return SummaryView(
        s.trips_used, s.trips_evaluated, mean_excess, _num(s.mean_percentile, "percentile", mean_why), ci_lo, ci_hi, None if s.position is None else s.position.value,
        Sample(s.trips_used, needed),
        interval_direction(mean_excess.value, ci_lo.value, ci_hi.value))


def _summaries(res: LuckResult | None, needed: int, why: str) -> dict[str, SummaryView]:
    gate = "" if res is None or res.unavailable is None else why_text(res.unavailable)
    parts = {"ALT": None if res is None else res.alt_summary, "NIFTY": None if res is None else res.nifty_summary}
    return {b: _summary(s, gate, needed, why) for b, s in parts.items()}


def _histogram(o: BaselineOutcome, actual: Decimal) -> HistogramView:
    """Count the portfolio returns the quant already drew into 20 equal bins that also span the trip's own return."""
    returns = o.portfolio_returns
    lo, hi = min(min(returns), actual), max(max(returns), actual)
    n = HISTOGRAM_BINS if lo != hi else 1
    width = (hi - lo) / n if n > 1 else Decimal(0)
    edges = [lo] + [lo + width * i for i in range(1, n)] + [hi]  # the ends are the exact extremes, never re-rounded

    def index(r: Decimal) -> int:  # the last bin whose lower edge is <= r, so a value always sits inside its own bin
        return max(0, min(bisect_right(edges, r) - 1, n - 1))

    counts = [0] * n
    for r in returns:
        counts[index(r)] += 1
    bins = tuple(BinView(Num(canonical_decimal(edges[i]), "ratio"), Num(canonical_decimal(edges[i + 1]), "ratio"), counts[i])
                 for i in range(n))
    total, less, same = len(returns), o.beaten, o.ties
    same_clause = f", {same} the same and" if same else " and"  # a zero count is left out, not spelled "0 the same"
    text = f"Of the {total} portfolios drawn, {less} returned less than your trip{same_clause} {total - less - same} more."
    return HistogramView(bins, index(actual), Num(canonical_decimal(actual), "ratio"), bins[0].lower, bins[-1].upper, total, text)


def _outcome(o: BaselineOutcome, actual: Decimal | None = None) -> OutcomeView:
    reason = why_text(o.unavailable) if o.unavailable else ""
    excess = _num(None if o.unavailable else o.excess, "ratio", reason)
    if o.unavailable:  # an unavailable outcome has no counts: never 0
        return OutcomeView(_num(None, "percentile", reason), excess, _dec(None, "ratio", reason), None, None, None, reason)
    hist = None if o.portfolio_returns is None or actual is None else _histogram(o, actual)
    return OutcomeView(_num(o.percentile, "percentile", reason), excess, _dec(o.mean_return, "ratio", reason), o.portfolio_count,
                       o.pool_size, o.lost_count, "", direction(excess.value), hist)


def _bias_views(res: BiasAnalysisResult | None, why: str) -> tuple[BiasView, ...]:
    kinds = ("DISPOSITION", "CHASING", "OVERTRADING")
    out = []
    for kind in kinds:
        r = None if res is None else next((x for x in res.results if x.metric.bias.value == kind), None)
        if r is None:
            miss = why or "not computed"
            out.append(BiasView(kind, Num(None, "inr", miss), Num(None, "inr", miss), Num(None, "inr", miss), None, None, (), ()))
            continue
        m = r.metric
        reason = m.unavailable.reason if m.unavailable is not None else "not available"
        out.append(BiasView(
            kind, _dec(m.cost_inr, "inr_lower_bound" if m.is_lower_bound else "inr", reason), _dec(m.gross_cost_inr, "inr", reason),
            _dec(m.fees_known, "inr", "no known fees or fees do not apply"), None if m.fee_status is None else m.fee_status.value,
            m.unknown_fee_trade_count if m.cost_inr is not None else None, tuple((e.subject, e.reason) for e in m.exclusions), tuple(m.details)))
    return tuple(out)


def _regime_tag(regime: RegimeResult | None, trip_id: str, why: str) -> RegimeTagView:
    t = None if regime is None else next((x for x in regime.trips if x.trip_id == trip_id), None)
    if t is None:
        miss = why or "no regime label for this trip"
        return RegimeTagView(None, Num(None, "ratio", miss), Num(None, "ratio", miss), Num(None, "ratio", miss), None, miss)
    reason = why_text(t.unavailable) if t.unavailable else ""
    miss = reason or "not available"
    return RegimeTagView(None if t.regime is None else t.regime.value, _num(t.volatility, "ratio", miss),
                         _num(t.low_threshold, "ratio", miss), _num(t.high_threshold, "ratio", miss), t.calibration_count, reason)


def _caveats(detail: AnalysisDetail) -> tuple[str, ...]:
    prov, notes = detail.facts.provenance, []
    if prov.get("universe_static"):
        notes.append(str(prov.get("universe_note") or "static universe: survivorship bias"))
    if prov.get("excluded_listings"):
        notes.append("not analysed in luck/regime: " + ", ".join(f"{s}.{e} ({why})" for s, e, why, _ in prov["excluded_listings"]))
    if prov.get("price_proxies"):
        notes.append(f"{prov.get('price_proxy_note')}: " + ", ".join(f"{b}.{be}" for b, be, _, _ in prov["price_proxies"]))
    if prov.get("late_recorded_row_count"):
        notes.append(f"{prov['late_recorded_row_count']} rows were recorded after this date; trades are placed by trade time")
    notes.append("returns use ledger prices and exclude fees; luck and bias results are heuristics on small samples, not proof of skill or luck")
    return tuple(notes)


def build_view(detail: AnalysisDetail, as_of: date) -> AnalysisView:
    th, facts = detail.thresholds, {f.name: f.value for f in detail.facts.facts}
    errors = dict(detail.errors)
    luck_why = errors.get("007", "")
    labels = dict(detail.trip_labels)
    regime = detail.regime
    regime_why = errors.get("008", "") or ("" if regime is None or regime.unavailable is None else why_text(regime.unavailable))

    trips: dict[str, TripView] = {}
    for group in detail.luck_groups:
        for t in group.result.trips:
            reason = ""
            if not t.evaluated or t.alt.unavailable or t.nifty.unavailable:
                first = t.alt.unavailable or t.nifty.unavailable  # the per-baseline reasons are on `alt` and `nifty` themselves
                reason = why_text(first) if first else ""
            if t.evaluated:
                lost = t.alt.lost_count > 0 or t.nifty.lost_count > 0
                alt, nifty = _outcome(t.alt, t.actual_return), _outcome(t.nifty, t.actual_return)
            else:
                lost, alt, nifty = None, None, None
            ar = _dec(t.actual_return, "ratio_fees_excluded", "actual return not available")
            trips[t.trip_id] = TripView(
                t.trip_id, t.instrument.symbol, t.instrument.exchange.value, t.open_session, t.close_session, t.evaluated, ar,
                labels.get(t.trip_id), alt, nifty, lost,
                tuple(PickView(p.rank, p.instrument.symbol, p.instrument.exchange.value, p.isin, _dec(p.return_ratio, "ratio", "no exit bar"))
                      for p in t.picks) if t.evaluated else (),
                tuple((e.baseline.value, e.isin, e.reason.value, None if e.instrument is None else e.instrument.symbol,
                       None if e.instrument is None else e.instrument.exchange.value) for e in t.exclusions) if t.evaluated else (),
                tuple(t.zero_variance_features) if t.evaluated else (), _regime_tag(regime, t.trip_id, regime_why), reason)
    if regime is not None:  # trips 008 saw but 007 did not (e.g. an ambiguous ISIN), listed with the reason
        for t in regime.trips:
            if t.trip_id not in trips:
                why = luck_why or (why_text(t.unavailable) if t.unavailable else "not part of the luck test")
                trips[t.trip_id] = TripView(
                    t.trip_id, t.instrument.symbol, t.instrument.exchange.value, t.open_session, t.close_session, False,
                    Num(None, "ratio_fees_excluded", f"not computed: not in the luck test ({why})"), None, None, None, None, (), (), (),
                    _regime_tag(regime, t.trip_id, regime_why), why)
    for x in detail.excluded_trips:
        if x.trip_id not in trips:
            trips[x.trip_id] = TripView(
                x.trip_id, x.symbol, x.exchange, x.open_date, x.close_date, False,
                Num(None, "ratio_fees_excluded", f"not computed: listing excluded ({x.reason})"), None, None, None, None, (), (), (),
                RegimeTagView(None, Num(None, "ratio", x.reason), Num(None, "ratio", x.reason), Num(None, "ratio", x.reason), None,
                              f"listing excluded: {x.reason}"), x.reason)

    blocks = []
    for b in () if regime is None or regime.unavailable is not None else regime.blocks:
        luck = b.luck if isinstance(b.luck, LuckResult) else None
        bias = b.bias if isinstance(b.bias, BiasAnalysisResult) else None
        luck_reason = "" if luck is not None else why_text(b.luck)
        bias_reason = "" if bias is not None else why_text(b.bias)
        blocks.append(BlockView(
            b.regime.value, tuple(b.trip_ids), Sample(len(b.trip_ids), th.regime_min_trips_per_regime),
            None if luck is None else _summaries(luck, th.regime_min_trips_per_regime, ""), luck_reason,
            _bias_views(bias, bias_reason) if bias is not None else None, bias_reason))
    if not blocks:  # no regime analysis ran: the three blocks are still present, each Unavailable with the reason
        why = regime_why or errors.get("008", "") or "not computed"
        blocks = [BlockView(r, (), Sample(None, th.regime_min_trips_per_regime), None, why, None, why) for r in ("LOW", "NORMAL", "HIGH")]
    ran = regime is not None and regime.unavailable is None
    none_ready = None
    if ran and blocks and all(b.sample.have is not None and not b.sample.enough for b in blocks):
        c = {b.regime: b.sample.have for b in blocks}
        none_ready = (f"Not enough trips in any regime yet: Low {c['LOW']}, Normal {c['NORMAL']}, High {c['HIGH']} "
                      f"({th.regime_min_trips_per_regime} needed each)")
    rv = RegimeView(facts.get("regime.round_trip_count") if regime is not None and regime.unavailable is None else None,
                    facts.get("regime.unclassified_count") if regime is not None and regime.unavailable is None else None,
                    tuple(blocks), () if regime is None else tuple(regime.exclusions), regime_why or ("" if regime is not None else "not computed"),
                    () if regime is None else tuple(regime.limitations), none_ready)

    bias = detail.bias
    profile = bias.profile if bias is not None else None
    if profile is None:
        pv = ProfileView(None, errors.get("006", "not computed"), ())
    elif hasattr(profile, "archetype_id"):
        pv = ProfileView(profile.archetype_id, "", tuple(profile.supporting_metrics))
    else:
        pv = ProfileView(None, profile.reason, ())

    facts_group = detail.facts.provenance["luck_alternatives"]["facts_group"]
    count = facts.get("luck.trip_count")
    group_views = tuple(GroupView(g.label, len(g.result.trips), _summaries(g.result, th.luck_min_trips, luck_why)) for g in detail.luck_groups)
    ordered = tuple(sorted(trips.values(), key=lambda t: (t.open_session, t.close_session, t.trip_id)))
    return AnalysisView(
        as_of, th, None if count in (None, "Unavailable") else int(count), facts_group,
        _summaries(detail.luck_facts, th.luck_min_trips, luck_why or "not computed"), luck_why, group_views, ordered,
        tuple((s, e, why, int(n)) for s, e, why, n in detail.facts.provenance["excluded_listings"]), _caveats(detail), detail.errors, rv,
        _bias_views(bias, errors.get("006", "")), pv, Sample(detail.trips_total, th.bias_min_round_trips),
        () if detail.luck_facts is None else tuple(detail.luck_facts.limitations))
