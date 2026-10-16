"""Feature 011: run the 006 bias-cost, 007 luck-test and 008 regime-split analyses on one user's real trades as of a day D.

Reads: the user's effective trades as the ledger stood at the end of D (IST), and daily bars truncated to D through the
history port. Never imports `app.analyst`; the analyst adapter lives in `app/api/analyst_wiring.py`. An analysis that lacks
an input answers Unavailable with a reason; nothing is invented, estimated or turned into 0 (spec 011).
"""

import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from app.domain.instrument import Instrument
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
IST = timezone(timedelta(hours=5, minutes=30))
HISTORY_DAYS = 300  # bars fetched before the first trade (chasing 21, luck 61, regime 181 sessions need history)
BIAS_WINDOW_START = datetime(2000, 1, 1, tzinfo=timezone.utc)
RULE_SET_VERSION = "archetype-v1"
SEED_NAMES = ("luck_test", "regime_split")


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


def _emit_summary(out: _Out, prefix: str, source: str, base: str, s, gate: str | None) -> None:
    mean_why = gate or (_why(s.mean_unavailable) if s.mean_unavailable else "")
    ci_why = gate or (_why(s.ci_unavailable) if s.ci_unavailable else "")
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
    _emit_summary(out, "luck.", "007", "ALT", res.alt_summary, gate)
    _emit_summary(out, "luck.", "007", "NIFTY", res.nifty_summary, gate)
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
        if as_of >= local_date(now, timedelta(hours=5, minutes=30)):
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
        try:
            ledger = [LedgerTrade(
                trade_id=str(t.id), instrument=Instrument(t.symbol, t.exchange), isin=t.isin, side=t.side, quantity=t.quantity,
                price=t.price_per_unit, trade_timestamp=t.trade_timestamp, currency=t.currency,
                charges=ChargeValue(True, t.brokerage_fee, t.taxes) if t.charges_provided else ChargeValue.unknown())
                for t in rows]
        except (BiasInputError, ValueError, TypeError) as exc:
            error = f"trade input rejected: {exc}"

        series, series_unavailable = ({}, []) if error else self._series(ledger, as_of, boundary, now)
        why = error or ""
        bias_res = luck_res = regime_res = None
        trip_count: int | None = None
        known = cfg.corporate_action_listings
        reviewed = cfg.corporate_action_reviewed
        traded = {t.instrument for t in ledger}
        bias_known = known if reviewed is None else known | frozenset(traded - reviewed)
        bias_params = BiasParameters(chasing_lookback_sessions=20, window_start=BIAS_WINDOW_START, window_end=boundary,
                                     formula_version="bias-v1", rule_set_version=RULE_SET_VERSION)
        luck_p = {n: LuckParameters(seed=seeds[n], as_of=boundary, portfolio_count=cfg.luck_portfolio_count,
                                    bootstrap_replicates=cfg.luck_bootstrap_replicates) for n in SEED_NAMES}
        reasons = {"006": why, "007": why, "008": why}
        if not error:
            try:
                bias_res = analyze_biases(ledger, series, bias_params, bias_known)
            except BiasInputError as exc:
                reasons["006"] = f"BiasInputError: {exc}"
            try:
                validated = validate_inputs(ledger, series, bias_params, bias_known)
                if validated.missing_series:
                    names = ", ".join(f"{i.symbol}.{i.exchange.value}" for i in validated.missing_series)
                    reasons["007"] = f"NO_TRIP_SERIES: missing series for {names}"
                else:
                    mapped = map_round_trips(fold_positions(validated).round_trips) if validated.trades else ()
                    trips = [m.trip for m in mapped if m.unavailable is None]
                    trip_count = len(trips)
                    luck_res = analyze_luck(trips, series, cfg.universe, cfg.nifty50, known, luck_p["luck_test"],
                                            corporate_action_reviewed=reviewed)
            except (BiasInputError, LuckInputError, RegimeInputError) as exc:
                reasons["007"] = f"{type(exc).__name__}: {exc}"
            try:
                regime_res = analyze_regimes(ledger, series, cfg.universe, cfg.nifty50, known, bias_params,
                                             luck_p["regime_split"], cfg.regime_parameters, corporate_action_reviewed=reviewed)
            except (BiasInputError, LuckInputError, RegimeInputError) as exc:
                reasons["008"] = f"{type(exc).__name__}: {exc}"

        _emit_bias(out, "bias.", "006", bias_res, reasons["006"] or "not computed")
        _emit_luck(out, luck_res, trip_count, reasons["007"] or "not computed")
        _emit_regime(out, regime_res, reasons["008"] or "not computed")

        profile = None if bias_res is None else bias_res.profile
        provenance = {
            "as_of": as_of.isoformat(), "boundary_utc": boundary.isoformat(), "user_trade_count": len(ledger), "late_recorded_row_count": late_rows,
            "latest_recorded_at": latest.isoformat() if latest else None,
            "seeds": seeds, "formula_versions": {"006": "bias-v1", "007": "luck-v1", "008": "regime-v1"},
            "series": sorted([i.symbol, i.exchange.value, s.fingerprint] for i, s in series.items()),
            "series_unavailable": sorted(series_unavailable),
            "universe": [[c.instrument.symbol, c.instrument.exchange.value, c.isin] for c in cfg.universe],
            "nifty_membership_count": len(cfg.nifty50),
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

    def _series(self, ledger: list[LedgerTrade], as_of: date, boundary: datetime, now: datetime):
        """One series per traded listing (own exchange, no fallback) and per universe listing, truncated to the boundary."""
        if not ledger:
            return {}, []
        listings = sorted({t.instrument for t in ledger} | {c.instrument for c in self._config.universe},
                          key=lambda i: (i.symbol, i.exchange.value))
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
        return out, missing
