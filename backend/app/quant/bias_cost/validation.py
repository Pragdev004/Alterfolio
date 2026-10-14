"""Input validation: one authority for trades, series, window and listing eligibility (spec sections 3, 5).

Defects raise `BiasInputError`. A listing that cannot be used safely is EXCLUDED with a recorded reason; a listing with
trades but no series is reported in `missing_series` (the metrics then become `Unavailable`). Nothing is repaired.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date

from app.domain.enums import Currency
from app.domain.instrument import Instrument
from app.quant.market_data.series import MarketSeries

from .errors import BiasInputError
from .market_context import SeriesIndex
from .types import FORMULA_VERSION, BiasExclusion, BiasParameters, LedgerTrade


def listing_name(instrument: Instrument) -> str:
    return f"{instrument.symbol}.{instrument.exchange.value}"


def _listing_key(instrument: Instrument) -> tuple[str, str]:
    return (instrument.symbol, instrument.exchange.value)


@dataclass(frozen=True)
class ValidatedBiasInputs:
    trades: tuple[LedgerTrade, ...]  # eligible trades only, sorted by (UTC time, trade id)
    indexes: tuple[tuple[Instrument, SeriesIndex], ...]  # one per eligible listing, sorted by (symbol, exchange)
    sessions: tuple[tuple[str, date], ...]  # (trade_id, session date in that listing's own series offset)
    missing_series: tuple[Instrument, ...]  # listings with trades but no series (sorted)
    exclusions: tuple[BiasExclusion, ...]
    excluded_listings: tuple[Instrument, ...]  # sorted; corporate actions or trade session without a bar
    parameters: BiasParameters

    def index_for(self, instrument: Instrument) -> SeriesIndex:
        for key, index in self.indexes:
            if key == instrument:
                return index
        raise KeyError(listing_name(instrument))

    def session_for(self, trade: LedgerTrade) -> date:
        for trade_id, session in self.sessions:
            if trade_id == trade.trade_id:
                return session
        raise KeyError(trade.trade_id)


def validate_inputs(
    trades: Iterable[LedgerTrade],
    series: Mapping[Instrument, MarketSeries],
    parameters: BiasParameters,
    corporate_action_listings: frozenset[Instrument] = frozenset(),
) -> ValidatedBiasInputs:
    if not isinstance(parameters, BiasParameters):
        raise BiasInputError("parameters must be BiasParameters")
    if parameters.formula_version != FORMULA_VERSION:
        raise BiasInputError(f"formula_version {parameters.formula_version!r} is not approved; only {FORMULA_VERSION!r}")
    if not isinstance(series, Mapping):
        raise BiasInputError("series must be a mapping of listing to MarketSeries")
    for key, value in series.items():
        if not isinstance(key, Instrument) or not isinstance(value, MarketSeries) or value.instrument != key:
            raise BiasInputError("each series must be keyed by its own listing (symbol, exchange)")
        if value.currency is not Currency.INR:
            raise BiasInputError("only INR series are supported")
    if not isinstance(corporate_action_listings, frozenset) or not all(
        isinstance(i, Instrument) for i in corporate_action_listings
    ):
        raise BiasInputError("corporate_action_listings must be a frozenset of Instrument")

    ordered = sorted(trades, key=lambda t: (t.trade_timestamp, t.trade_id))
    seen: set[str] = set()
    for trade in ordered:
        if not isinstance(trade, LedgerTrade):
            raise BiasInputError("trades must be LedgerTrade")
        if trade.trade_id in seen:
            raise BiasInputError(f"duplicate trade_id {trade.trade_id!r}")
        seen.add(trade.trade_id)
        if not (parameters.window_start <= trade.trade_timestamp <= parameters.window_end):
            raise BiasInputError(f"trade {trade.trade_id!r} is outside the ledger window")

    exclusions: list[BiasExclusion] = []
    excluded: dict[Instrument, str] = {}
    missing: set[Instrument] = set()
    indexes: dict[Instrument, SeriesIndex] = {}
    for instrument in sorted({t.instrument for t in ordered}, key=_listing_key):
        if instrument in corporate_action_listings:
            excluded[instrument] = "known corporate action: ledger and market price bases differ"
        elif instrument not in series:
            missing.add(instrument)
        else:
            index = SeriesIndex.build(series[instrument])
            for trade in ordered:
                if trade.instrument == instrument and index.index_of(index.session_of(trade.trade_timestamp)) is None:
                    excluded[instrument] = (
                        f"trade {trade.trade_id} session {index.session_of(trade.trade_timestamp)} has no bar "
                        "(after the series cutoff or a data gap)"
                    )
                    break
            else:
                indexes[instrument] = index
    for instrument, reason in sorted(excluded.items(), key=lambda kv: _listing_key(kv[0])):
        exclusions.append(BiasExclusion(listing_name(instrument), f"listing excluded: {reason}"))

    kept = tuple(t for t in ordered if t.instrument not in excluded)
    sessions = tuple(
        (t.trade_id, indexes[t.instrument].session_of(t.trade_timestamp)) for t in kept if t.instrument in indexes
    )
    return ValidatedBiasInputs(
        trades=kept,
        indexes=tuple(sorted(indexes.items(), key=lambda kv: _listing_key(kv[0]))),
        sessions=sessions,
        missing_series=tuple(sorted(missing, key=_listing_key)),
        exclusions=tuple(exclusions),
        excluded_listings=tuple(sorted(excluded, key=_listing_key)),
        parameters=parameters,
    )
