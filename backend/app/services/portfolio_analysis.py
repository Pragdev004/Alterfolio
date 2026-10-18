"""Feature 011: run the 006 bias-cost, 007 luck-test and 008 regime-split analyses on one user's real trades as of a day D.

Reads: the user's effective trades as the ledger stood at the end of D (IST), and daily bars truncated to D through the
history port. Never imports `app.analyst`; the analyst adapter lives in `app/api/analyst_wiring.py`. An analysis that lacks
an input answers Unavailable with a reason; nothing is invented, estimated or turned into 0 (spec 011).
"""

import hashlib
import json
import math
from collections.abc import Callable
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from app.domain.enums import Exchange, TradeSide
from app.domain.instrument import Instrument
from app.domain.timezones import IST, IST_OFFSET
from app.quant.bias_cost.analysis import analyze_biases
from app.quant.bias_cost.cost_basis import fold_positions
from app.quant.bias_cost.errors import BiasInputError
from app.quant.bias_cost.types import BiasAnalysisResult, BiasKind, BiasParameters, ChargeValue, LedgerTrade
from app.quant.bias_cost.validation import validate_inputs
from app.quant.luck_test.analysis import analyze_luck
from app.quant.luck_test.errors import LuckInputError
from app.quant.luck_test.types import Candidate, LuckParameters, LuckResult, Membership
from app.quant.market_data.exchange_time import local_date
from app.quant.market_data.fingerprint import canonical_decimal
from app.quant.market_data.series import MarketSeries
from app.quant.regime_split.analysis import analyze_regimes
from app.quant.regime_split.errors import RegimeInputError
from app.quant.regime_split.trips import map_round_trips
from app.quant.regime_split.types import Regime, RegimeParameters, RegimeResult
from app.repositories.trade_repository import TradeRepository
from app.services.errors import AsOfNotSealedError
from app.services.market_series import MarketSeriesService, ResolvedSeries

UNAVAILABLE = "Unavailable"
HISTORY_DAYS = 300  # bars fetched before the first trade (chasing 21, luck 61, regime 181 sessions need history)
BIAS_WINDOW_START = datetime(2000, 1, 1, tzinfo=timezone.utc)
RULE_SET_VERSION = "archetype-v1"
SEED_NAMES = ("luck_test", "regime_split")
PROXY_NOTE = "price proxy: NSE series for BSE listing"


def content_trade_id(t, ordinal: int) -> str:
    """Analysis identity of a ledger row from its CONTENT, not its random row id: the same trades give the same ids (hence the
    same trip ids, RNG sub-streams and fingerprints) whatever order they were imported in. `ordinal` separates identical rows."""
    payload = json.dumps([t.symbol, t.exchange.value, t.side.value, str(t.quantity), str(t.price_per_unit), t.trade_timestamp.isoformat(),
                          t.isin, t.broker, t.broker_trade_id, t.order_id, str(t.brokerage_fee), str(t.taxes), t.charges_provided])
    return "t" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24] + (f"-{ordinal}" if ordinal else "")


def count_round_trips(trades) -> int:
    """Flat -> open -> flat on one listing (the 006 definition), counted from the trade sequence alone (no series needed)."""
    held, count = Decimal(0), 0
    for t in sorted(trades, key=lambda t: (t.trade_timestamp, t.trade_id)):
        held += t.quantity if t.side is TradeSide.BUY else -t.quantity
        if held == 0:
            count += 1
        elif held < 0:
            held = Decimal(0)  # a sell before any buy (opened before the window) is not a trip
    return count


def derive_seed(user_id: UUID, as_of: date, name: str) -> int:
    """Deterministic 64-bit seed from (user_id, as_of, analysis name); recorded in the facts provenance."""
    payload = json.dumps([str(user_id), as_of.isoformat(), name]).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


@dataclass(frozen=True)
class AnalysisConfig:
    """Caller-supplied, recorded in provenance. Defaults carry no invented universe, membership or corporate-action claim."""

    universe: tuple[Candidate, ...] = ()
    nifty50: tuple[Membership, ...] = ()
    corporate_action_listings: frozenset[Instrument] = frozenset()
    corporate_action_reviewed: frozenset[Instrument] | None = None  # None = undeclared: luck is Unavailable by 007's rule
    universe_static: bool = False  # True: a fixed list, not point-in-time membership (survivorship bias)
    universe_note: str = ""
    # Feature 014: traded ISIN -> (alternatives for its trips, label). Empty = every trip uses `universe` (the 012 behaviour).
    alternatives: dict[str, tuple[tuple[Candidate, ...], str]] = field(default_factory=dict)
    reference_provenance: tuple[dict, ...] = ()  # file provenance of the reference data in use, copied to the facts provenance
    luck_portfolio_count: int = 500
    luck_bootstrap_replicates: int = 10_000
    regime_parameters: RegimeParameters = field(default_factory=RegimeParameters)

    def __post_init__(self) -> None:
        isins = [c.isin for c in self.universe]
        listings = [c.instrument for c in self.universe]
        if len(set(isins)) != len(isins) or len(set(listings)) != len(listings):
            raise ValueError("the universe must hold exactly one listing per ISIN")


@dataclass(frozen=True)
class AnalysisFact:
    name: str
    value: str  # canonical decimal text or "Unavailable"
    source: str  # "006|007|008:<field>"
    unit: str = ""

    def __post_init__(self) -> None:
        if self.value != UNAVAILABLE:
            if not isinstance(self.value, str) or not Decimal(self.value).is_finite() or "e" in self.value.lower():
                raise ValueError("fact value must be plain decimal text or 'Unavailable'")
        if self.source.split(":", 1)[0] not in ("006", "007", "008"):
            raise ValueError("fact source must start with 006, 007 or 008")

    def to_dict(self) -> dict:
        return {"name": self.name, "value": self.value, "source": self.source, "unit": self.unit}


@dataclass(frozen=True)
class AnalysisFacts:
    as_of: date
    facts: tuple[AnalysisFact, ...]
    provenance: dict
    unavailable: tuple[tuple[str, str], ...]  # (fact name or analysis source, reason)

    def to_dict(self) -> dict:
        return {"as_of": self.as_of.isoformat(), "facts": [f.to_dict() for f in self.facts], "provenance": self.provenance,
                "unavailable": [list(u) for u in self.unavailable]}


class _Out:
    def __init__(self) -> None:
        self.facts: list[AnalysisFact] = []
        self.unavailable: list[tuple[str, str]] = []

    def num(self, name: str, source: str, value: str, unit: str = "") -> None:
        self.facts.append(AnalysisFact(name, value, source, unit))

    def na(self, name: str, source: str, reason: str, unit: str = "") -> None:
        self.facts.append(AnalysisFact(name, UNAVAILABLE, source, unit))
        self.unavailable.append((name, reason or "unavailable"))

    def opt(self, name: str, source: str, value: str | None, reason: str, unit: str = "") -> None:
        if value is None:
            self.na(name, source, reason, unit)
        else:
            self.num(name, source, value, unit)


def _why(u) -> str:
    reason = getattr(u.reason, "value", u.reason)
    detail = getattr(u, "detail", "")
    return f"{reason}: {detail}" if detail else str(reason)


def _stat(x: float | None) -> str | None:
    """A statistic float -> canonical decimal text, once. NaN/inf/None -> None (Unavailable)."""
    if x is None or not math.isfinite(x):
        return None
    text = canonical_decimal(Decimal(repr(x)))
    return "0" if text in ("-0", "-0.0") else text


def _count(n: int) -> str:
    return str(int(n))


def _bias_results(res: BiasAnalysisResult | None, why: str) -> dict[BiasKind, tuple[str | None, str, str, int | None]]:
    """kind -> (cost text | None, unit, reason, unknown_fee_trade_count | None)."""
    out = {}
    for kind in BiasKind:
        r = None if res is None else next((x for x in res.results if x.metric.bias is kind), None)
        if r is None:
            out[kind] = (None, "INR", why or "not computed", None)
        elif r.metric.cost_inr is None:
            out[kind] = (None, "INR", r.metric.unavailable.reason, None)
        else:
            m = r.metric
            out[kind] = (canonical_decimal(m.cost_inr), "INR_LOWER_BOUND" if m.is_lower_bound else "INR", "",
                         m.unknown_fee_trade_count)
    return out


def _emit_bias(out: _Out, prefix: str, source_prefix: str, res: BiasAnalysisResult | None, why: str) -> None:
    for kind, (cost, unit, reason, unknown) in _bias_results(res, why).items():
        out.opt(f"{prefix}{kind.value}.cost_inr", f"{source_prefix}:{kind.value}.cost_inr", cost, reason, unit)
        if kind is BiasKind.OVERTRADING:
            out.opt(f"{prefix}OVERTRADING.unknown_fee_trade_count", f"{source_prefix}:OVERTRADING.unknown_fee_trade_count",
                    None if unknown is None else _count(unknown), reason or why)


def _emit_summary(out: _Out, prefix: str, source: str, base: str, s, gate: str | None, per_trip: str = "") -> None:
    suffix = f" (trips: {per_trip})" if per_trip else ""
    mean_why = gate or (_why(s.mean_unavailable) + suffix if s.mean_unavailable else "")
    ci_why = gate or (_why(s.ci_unavailable) + suffix if s.ci_unavailable else "")
    out.num(f"{prefix}{base}.trips_used", f"{source}:{base}.trips_used", _count(s.trips_used))
    out.num(f"{prefix}{base}.trips_evaluated", f"{source}:{base}.trips_evaluated", _count(s.trips_evaluated))
    for field_name, value, reason in (("mean_excess", s.mean_excess, mean_why), ("mean_percentile", s.mean_percentile, mean_why),
                                      ("ci_lower", s.ci_lower, ci_why), ("ci_upper", s.ci_upper, ci_why)):
        out.opt(f"{prefix}{base}.{field_name}", f"{source}:{base}.{field_name}", _stat(value), reason)


def _emit_luck(out: _Out, res: LuckResult | None, trip_count: int | None, why: str) -> None:
    names = ("trips_used", "trips_evaluated", "mean_excess", "mean_percentile", "ci_lower", "ci_upper")
    if res is None:
        out.na("luck.trip_count", "007:trip_count", why)
        for base in ("ALT", "NIFTY"):
            for n in names:
                out.na(f"luck.{base}.{n}", f"007:{base}.{n}", why)
        out.na("luck.last_trip.actual_return", "007:last_trip.actual_return", why)
        for base in ("ALT", "NIFTY"):
            for n in ("percentile", "excess"):
                out.na(f"luck.last_trip.{base}.{n}", f"007:last_trip.{base}.{n}", why)
        return
    gate = _why(res.unavailable) if res.unavailable else None
    out.num("luck.trip_count", "007:trip_count", _count(len(res.trips) if trip_count is None else trip_count))
    for base, attr, summary in (("ALT", "alt", res.alt_summary), ("NIFTY", "nifty", res.nifty_summary)):
        counts: dict[str, int] = {}
        for t in res.trips:  # per-trip outcome reasons (gates included), so a summary reason is never opaque
            o = getattr(t, attr)
            if o.unavailable is not None:
                key = getattr(o.unavailable.reason, "value", str(o.unavailable.reason))
                counts[key] = counts.get(key, 0) + 1
        _emit_summary(out, "luck.", "007", base, summary, gate, "; ".join(f"{r} x{n}" for r, n in sorted(counts.items())))
    last = res.trips[-1] if res.trips else None
    out.opt("luck.last_trip.actual_return", "007:last_trip.actual_return",
            None if last is None or last.actual_return is None else canonical_decimal(last.actual_return),
            "no round trip" if last is None else "actual return not available", "RATIO_FEES_EXCLUDED")
    for base, attr in (("ALT", "alt"), ("NIFTY", "nifty")):
        o = None if last is None else getattr(last, attr)
        reason = "no round trip" if o is None else (_why(o.unavailable) if o.unavailable else "")
        for n in ("percentile", "excess"):
            val = None if o is None or o.unavailable else _stat(getattr(o, n))
            out.opt(f"luck.last_trip.{base}.{n}", f"007:last_trip.{base}.{n}", val, reason)


def _emit_regime(out: _Out, res: RegimeResult | None, why: str) -> None:
    if res is None or res.unavailable is not None:
        reason = why if res is None else _why(res.unavailable)
        out.na("regime.round_trip_count", "008:round_trip_count", reason)
        out.na("regime.unclassified_count", "008:unclassified_count", reason)
        blocks = {}
    else:
        reason = ""
        out.num("regime.round_trip_count", "008:round_trip_count", _count(res.round_trip_count))
        out.num("regime.unclassified_count", "008:unclassified_count", _count(sum(1 for t in res.trips if t.regime is None)))
        blocks = {b.regime: b for b in res.blocks}
    for regime in Regime:
        b, p = blocks.get(regime), f"regime.{regime.value}."
        s = f"008:{regime.value}."
        out.opt(p + "trip_count", s + "trip_count", None if b is None else _count(len(b.trip_ids)), reason)
        luck = None if b is None else b.luck
        lwhy = reason if luck is None else (_why(luck) if not isinstance(luck, LuckResult) else "")
        summary = luck.alt_summary if isinstance(luck, LuckResult) else None
        out.opt(p + "luck.ALT.mean_excess", s + "luck.ALT.mean_excess", None if summary is None else _stat(summary.mean_excess),
                lwhy or (_why(summary.mean_unavailable) if summary and summary.mean_unavailable else ""))
        bias = None if b is None or not isinstance(b.bias, BiasAnalysisResult) else b.bias
        bwhy = reason if b is None else (_why(b.bias) if bias is None else "")
        for kind, (cost, unit, kreason, _) in _bias_results(bias, bwhy or "not computed").items():
            out.opt(f"{p}bias.{kind.value}.cost_inr", f"{s}bias.{kind.value}.cost_inr", cost, kreason, unit)


class PortfolioAnalysisService:
    def __init__(self, *, repo: TradeRepository, provider,  # a HistoricalBarProvider (only the series service imports the port)
                 clock: Callable[[], datetime],
                 config: AnalysisConfig) -> None:
        self._repo, self._provider, self._clock, self._config = repo, provider, clock, config

    @classmethod
    def for_session(cls, session, *, provider, clock: Callable[[], datetime], config: AnalysisConfig) -> "PortfolioAnalysisService":
        return cls(repo=TradeRepository(session), provider=provider, clock=clock, config=config)

    def require_sealed(self, as_of: date) -> None:
        """Raise AsOfNotSealedError unless D is before today's IST date (callable without running an analysis)."""
        self._require_sealed(as_of, self._clock())

    @staticmethod
    def _require_sealed(as_of: date, now: datetime) -> None:
        if isinstance(as_of, datetime) or not isinstance(as_of, date):
            raise TypeError("as_of must be a date")
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("the clock must return a timezone-aware datetime")
        if as_of >= local_date(now, IST_OFFSET):
            raise AsOfNotSealedError(as_of)

    def analyse(self, user_id: UUID, as_of: date) -> AnalysisFacts:
        now = self._clock()  # the one clock reading of this run
        self._require_sealed(as_of, now)
        boundary = datetime.combine(as_of + timedelta(days=1), time.min, IST).astimezone(timezone.utc)  # IST midnight of D+1
        rows = [t for t in self._repo.list_effective(user_id=user_id, as_of=boundary - timedelta(microseconds=1))
                if t.user_id == user_id and t.trade_timestamp < boundary]
        # Backfilled imports are recorded after D by nature, so recording time does not filter; it is disclosed instead.
        late_rows = sum(1 for t in self._repo.list_for_user(user_id=user_id)
                        if t.trade_timestamp < boundary and t.recorded_at > boundary)
        out, cfg = _Out(), self._config
        latest = max((t.recorded_at for t in rows), default=None)
        seeds = {name: derive_seed(user_id, as_of, name) for name in SEED_NAMES}
        error: str | None = None
        ledger: list[LedgerTrade] = []
        seen_ids: dict[str, int] = defaultdict(int)
        try:
            ledger = [LedgerTrade(
                trade_id=self._content_id(t, seen_ids), instrument=Instrument(t.symbol, t.exchange), isin=t.isin, side=t.side, quantity=t.quantity,
                price=t.price_per_unit, trade_timestamp=t.trade_timestamp, currency=t.currency,
                charges=ChargeValue(True, t.brokerage_fee, t.taxes) if t.charges_provided else ChargeValue.unknown())
                for t in rows]
        except (BiasInputError, ValueError, TypeError) as exc:
            error = f"trade input rejected: {exc}"

        series, series_unavailable, proxies = ({}, [], []) if error else self._series(ledger, as_of, boundary, now)
        why = error or ""
        bias_res = luck_res = regime_res = None
        trip_count: int | None = None
        luck_alt: dict = {"per_trip": [], "groups": [], "facts_group": None}
        known = cfg.corporate_action_listings
        reviewed = cfg.corporate_action_reviewed
        traded = {t.instrument for t in ledger}
        bias_known = known if reviewed is None else known | frozenset(traded - reviewed)
        bias_params = BiasParameters(chasing_lookback_sessions=20, window_start=BIAS_WINDOW_START, window_end=boundary,
                                     formula_version="bias-v1", rule_set_version=RULE_SET_VERSION)
        luck_p = {n: LuckParameters(seed=seeds[n], as_of=boundary, portfolio_count=cfg.luck_portfolio_count,
                                    bootstrap_replicates=cfg.luck_bootstrap_replicates) for n in SEED_NAMES}
        reasons = {"006": why, "007": why, "008": why}
        # Partial coverage (spec 012): a listing with no series, or unreviewed/known-action, is excluded from luck and regime
        # with a per-listing reason (never silently); the analyses run on what remains. 006 keeps its strict rule.
        outcomes = {(a, b): c for a, b, c in series_unavailable}
        excluded: dict[Instrument, str] = {}
        for inst in sorted(traded, key=lambda i: (i.symbol, i.exchange.value)):
            if inst not in series:
                excluded[inst] = f"no market-data series ({outcomes.get((inst.symbol, inst.exchange.value), 'not fetched')})"
            elif reviewed is not None and inst in known:
                excluded[inst] = "known corporate action inside the review window (prices unadjusted)"
            elif reviewed is not None and inst not in reviewed:
                excluded[inst] = "not covered by the corporate-action review register"
        part = [t for t in ledger if t.instrument not in excluded]
        by_listing: dict[Instrument, list] = defaultdict(list)
        for t in ledger:
            by_listing[t.instrument].append(t)
        trips_total = sum(count_round_trips(v) for v in by_listing.values())
        excluded_rows = [[i.symbol, i.exchange.value, r, count_round_trips(by_listing[i])] for i, r in excluded.items()]
        if ledger and not part and not error:
            reasons["007"] = reasons["008"] = "all traded listings are excluded (see provenance.excluded_listings)"
        if not error:
            try:
                bias_res = analyze_biases(ledger, series, bias_params, bias_known)
            except BiasInputError as exc:
                reasons["006"] = f"BiasInputError: {exc}"
            try:
                validated = validate_inputs(part, series, bias_params, known) if part else None
                if validated is None:
                    pass
                elif validated.missing_series:
                    names = ", ".join(f"{i.symbol}.{i.exchange.value}" for i in validated.missing_series)
                    reasons["007"] = f"NO_TRIP_SERIES: missing series for {names}"
                else:
                    mapped = map_round_trips(fold_positions(validated).round_trips) if validated.trades else ()
                    trips = [m.trip for m in mapped if m.unavailable is None]
                    trip_count = len(trips)
                    luck_res, luck_alt = self._luck(trips, series, known, luck_p["luck_test"], reviewed)
            except (BiasInputError, LuckInputError, RegimeInputError) as exc:
                reasons["007"] = f"{type(exc).__name__}: {exc}"
            try:
                regime_res = None if not part else analyze_regimes(part, series, cfg.universe, cfg.nifty50, known, bias_params,
                                             luck_p["regime_split"], cfg.regime_parameters, corporate_action_reviewed=reviewed)
            except (BiasInputError, LuckInputError, RegimeInputError) as exc:
                reasons["008"] = f"{type(exc).__name__}: {exc}"

        _emit_bias(out, "bias.", "006", bias_res, reasons["006"] or "not computed")
        _emit_luck(out, luck_res, trip_count, reasons["007"] or "not computed")
        _emit_regime(out, regime_res, reasons["008"] or "not computed")
        for prefix, source, analysed, why008 in (
                ("luck", "007", None if luck_res is None else _count(trip_count if trip_count is not None else 0), reasons["007"]),
                ("regime", "008", None if regime_res is None or regime_res.unavailable is not None else _count(regime_res.round_trip_count),
                 reasons["008"])):
            why_c = why008 or "not computed"
            out.opt(f"{prefix}.coverage.trips_total", f"{source}:coverage.trips_total", None if error else _count(trips_total), why_c)
            out.opt(f"{prefix}.coverage.trips_analysed", f"{source}:coverage.trips_analysed", analysed, why_c)
            out.opt(f"{prefix}.coverage.excluded_listing_count", f"{source}:coverage.excluded_listing_count",
                    None if error else _count(len(excluded)), why_c)

        profile = None if bias_res is None else bias_res.profile
        provenance = {
            "as_of": as_of.isoformat(), "boundary_utc": boundary.isoformat(), "user_trade_count": len(ledger), "late_recorded_row_count": late_rows,
            "latest_recorded_at": latest.isoformat() if latest else None,
            "seeds": seeds, "formula_versions": {"006": "bias-v1", "007": "luck-v1", "008": "regime-v1"},
            "series": sorted([i.symbol, i.exchange.value, s.fingerprint] for i, s in series.items()),
            "series_unavailable": sorted(series_unavailable),
            "universe": [[c.instrument.symbol, c.instrument.exchange.value, c.isin] for c in cfg.universe],
            "nifty_membership_count": len(cfg.nifty50),
            "trips_total": trips_total, "excluded_listings": excluded_rows, "price_proxies": proxies,
            "price_proxy_note": PROXY_NOTE if proxies else "",
            "universe_static": cfg.universe_static, "universe_note": cfg.universe_note,
            "luck_alternatives": luck_alt, "reference_data": list(cfg.reference_provenance),
            "corporate_action_coverage": "UNDECLARED" if reviewed is None else "DECLARED",
            "corporate_action_listings": sorted(f"{i.symbol}.{i.exchange.value}" for i in known),
            "corporate_action_reviewed": None if reviewed is None else sorted(f"{i.symbol}.{i.exchange.value}" for i in reviewed),
            "config": {"luck_portfolio_count": cfg.luck_portfolio_count, "luck_bootstrap_replicates": cfg.luck_bootstrap_replicates,
                       "regime": cfg.regime_parameters.to_dict()},
            "bias_profile": None if profile is None else (
                profile.archetype_id if hasattr(profile, "archetype_id") else f"Unavailable: {profile.reason}"),
            "analysis_errors": {k: v for k, v in reasons.items() if v},
            "input_fingerprints": {"006": None if bias_res is None else bias_res.input_fingerprint,
                                   "007": None if luck_res is None else luck_res.input_fingerprint,
                                   "008": None if regime_res is None else regime_res.input_fingerprint},
        }
        unavailable = tuple(out.unavailable) + tuple((k, v) for k, v in reasons.items() if v)
        return AnalysisFacts(as_of=as_of, facts=tuple(out.facts), provenance=provenance, unavailable=unavailable)

    def _luck(self, trips, series, known, params, reviewed):
        """007, once per distinct alternatives set (Feature 014; the quant call is unchanged). The luck FACTS come from the group
        holding the last trip; every trip's alternatives label and every group are recorded in the provenance."""
        cfg = self._config
        static_label = "alternatives: static universe"
        if not trips:
            return analyze_luck([], series, cfg.universe, cfg.nifty50, known, params, corporate_action_reviewed=reviewed),                 {"per_trip": [], "groups": [], "facts_group": None}
        chosen = [cfg.alternatives.get(t.isin or "", (cfg.universe, static_label)) for t in trips]
        order: list[tuple[tuple[Candidate, ...], str]] = []
        for c in chosen:
            if c not in order:
                order.append(c)
        results = {}
        for cands, label in order:
            members = [t for t, c in zip(trips, chosen) if c == (cands, label)]
            results[label, cands] = analyze_luck(members, series, cands, cfg.nifty50, known, params, corporate_action_reviewed=reviewed)
        last = chosen[-1] if chosen else None
        info = {"per_trip": [[t.trip_id, t.instrument.symbol, c[1]] for t, c in zip(trips, chosen)],
                "groups": [[label, len(cands), sum(1 for c in chosen if c == (cands, label))] for cands, label in order],
                "facts_group": None if last is None else last[1]}
        return (None if last is None else results[last[1], last[0]]), info

    @staticmethod
    def _content_id(t, seen: dict) -> str:
        base = content_trade_id(t, 0)
        n = seen[base]
        seen[base] += 1
        return base if n == 0 else content_trade_id(t, n)

    def _series(self, ledger: list[LedgerTrade], as_of: date, boundary: datetime, now: datetime):
        """One series per traded listing and per universe listing, truncated to the boundary. A BSE listing is priced by the
        NSE listing with the same ISIN (price proxy, recorded); every other listing uses its own exchange, no fallback."""
        if not ledger:
            return {}, [], []
        cfg = self._config
        nse_by_isin: dict[str, Instrument] = {}
        for t in ledger:
            if t.isin and t.instrument.exchange is Exchange.NSE:
                nse_by_isin.setdefault(t.isin, t.instrument)
        for c in cfg.universe:
            if c.instrument.exchange is Exchange.NSE:
                nse_by_isin.setdefault(c.isin, c.instrument)
        proxy: dict[Instrument, Instrument] = {}
        for t in ledger:
            if t.instrument.exchange is Exchange.BSE and t.isin in nse_by_isin:
                proxy[t.instrument] = nse_by_isin[t.isin]
        alt_listings = {c.instrument for cands, _ in cfg.alternatives.values() for c in cands}
        wanted = ({t.instrument for t in ledger} - set(proxy)) | {c.instrument for c in cfg.universe} | alt_listings | set(proxy.values())
        listings = sorted(wanted, key=lambda i: (i.symbol, i.exchange.value))
        start = min(t.trade_timestamp for t in ledger).date() - timedelta(days=HISTORY_DAYS)
        service = MarketSeriesService(provider=self._provider, clock=lambda: now)
        out: dict[Instrument, MarketSeries] = {}
        missing: list[list[str]] = []
        for listing in listings:
            r = service.resolve_series([listing], start, as_of)
            if isinstance(r, ResolvedSeries):
                s = r.series.truncated_to(boundary)
                if s.bar_count:
                    out[listing] = s
                    continue
                missing.append([listing.symbol, listing.exchange.value, "NO_BARS_BEFORE_BOUNDARY"])
            else:
                missing.append([listing.symbol, listing.exchange.value, ",".join(a.outcome.value for a in r.attempts)])
        proxies: list[list[str]] = []
        for bse, nse in sorted(proxy.items(), key=lambda kv: (kv[0].symbol, kv[0].exchange.value)):
            if nse in out:
                out[bse] = replace(out[nse], instrument=bse)  # NSE closes under the BSE listing's identity
                proxies.append([bse.symbol, bse.exchange.value, nse.symbol, nse.exchange.value])
            else:
                missing.append([bse.symbol, bse.exchange.value, f"price proxy {nse.symbol}.{nse.exchange.value} has no series"])
        return out, missing, proxies
