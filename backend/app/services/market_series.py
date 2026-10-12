"""Market-series service (Feature 004, plan sections 5 and 9): historical-bar port -> eligible MarketSeries.

Calls only the provider-neutral `HistoricalBarProvider` port. A raw batch is reduced to the bars whose session date is
strictly before the exchange-local date of the retrieval instant (a conservative eligibility rule, not a market-close
claim); the rest are excluded and counted. Values are never repaired, filled or estimated, and a series is never spliced
from two listings. Provider problems are returned as data (`SeriesUnavailable.attempts`), never raised.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum

from app.domain.instrument import Instrument
from app.providers.market.history_port import (
    BarFailure,
    BarFailureKind,
    HistoricalBarProvider,
    RawBar,
    RawBarBatch,
)
from app.quant.market_data.bar import MarketBar
from app.quant.market_data.exchange_time import local_date
from app.quant.market_data.provenance import DataProvenance
from app.quant.market_data.series import MarketSeries
from app.services.holdings import Holding
from app.services.portfolio_summary import quote_candidates


class AttemptOutcome(str, Enum):
    USED = "USED"
    NOT_FOUND = "NOT_FOUND"
    PROVIDER_ERROR = "PROVIDER_ERROR"  # includes a provider that raised; never falls back to another listing
    INVALID_RESPONSE = "INVALID_RESPONSE"
    NO_ELIGIBLE_BARS = "NO_ELIGIBLE_BARS"  # a valid answer, but no bar before the retrieval-local date
    INVALID_BARS = "INVALID_BARS"  # the bars failed MarketBar/MarketSeries validation, or the answer did not fit the request


@dataclass(frozen=True)
class SeriesAttempt:
    listing: Instrument
    outcome: AttemptOutcome
    detail: str = ""


@dataclass(frozen=True)
class ResolvedSeries:
    series: MarketSeries
    attempts: tuple[SeriesAttempt, ...]
    legacy: bool  # a NULL-ISIN holding resolved through its single listing


@dataclass(frozen=True)
class SeriesUnavailable:
    attempts: tuple[SeriesAttempt, ...]
    legacy: bool = False


_FAILURE_OUTCOME = {
    BarFailureKind.NOT_FOUND: AttemptOutcome.NOT_FOUND,
    BarFailureKind.PROVIDER_ERROR: AttemptOutcome.PROVIDER_ERROR,
    BarFailureKind.INVALID_RESPONSE: AttemptOutcome.INVALID_RESPONSE,
}


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def build_series(
    batch: RawBarBatch, requested: Instrument, start: date, end: date, retrieved_at: datetime
) -> MarketSeries:
    """The series of ELIGIBLE bars in `batch`. Raises ValueError/TypeError when the batch cannot form a valid series.

    `retrieved_at` is the instant the service supplied to the provider; the batch must echo exactly that instant.
    """
    if not isinstance(batch, RawBarBatch):
        raise TypeError("the provider did not return a RawBarBatch")
    if batch.instrument != requested:
        raise ValueError("the provider answered for a different listing than requested")
    if batch.retrieved_at != retrieved_at:
        # Eligibility is judged against the instant the SERVICE took; a provider-reported time is never trusted.
        raise ValueError("the provider's retrieved_at differs from the retrieval time the service supplied")
    if not isinstance(batch.bars, tuple) or not all(isinstance(b, RawBar) for b in batch.bars):
        raise TypeError("bars must be a tuple of RawBar")
    today = local_date(batch.retrieved_at, batch.exchange_utc_offset)
    eligible = tuple(b for b in batch.bars if b.session_date < today)
    bars = tuple(
        MarketBar(
            timestamp=b.timestamp, session_date=b.session_date, open=b.open, high=b.high, low=b.low, close=b.close,
            adjusted_close=b.adjusted_close, volume=b.volume,
        )
        for b in eligible
    )
    provenance = DataProvenance(
        source=batch.source,
        request_start=start,
        request_end=end,
        retrieved_at=batch.retrieved_at,
        rows_returned=batch.rows_returned,
        empty_rows_excluded=batch.empty_rows_excluded,
        ineligible_bars_excluded=len(batch.bars) - len(eligible),
        eligible_bars_at_fetch=len(bars),
        first_eligible_session_date_at_fetch=bars[0].session_date if bars else None,
        last_eligible_session_date_at_fetch=bars[-1].session_date if bars else None,
    )
    return MarketSeries.from_eligible_bars(
        instrument=batch.instrument,
        currency=batch.currency,
        bars=bars,
        exchange_utc_offset=batch.exchange_utc_offset,
        provenance=provenance,
    )


class MarketSeriesService:
    def __init__(self, *, provider: HistoricalBarProvider, clock: Callable[[], datetime]) -> None:
        self._provider = provider
        self._clock = clock

    def resolve_for_holding(
        self, holding: Holding, start: date, end: date
    ) -> ResolvedSeries | SeriesUnavailable:
        """NSE then BSE for an ISIN holding; a legacy NULL-ISIN holding uses its single listing only (flagged)."""
        candidates = quote_candidates(holding)
        legacy = holding.key.isin is None
        return self._resolve(candidates[:1] if legacy else candidates, start, end, legacy)

    def resolve_series(
        self, listings: Sequence[Instrument], start: date, end: date
    ) -> ResolvedSeries | SeriesUnavailable:
        """Try `listings` in the order given (callers pass NSE first). The first usable series wins; never spliced."""
        return self._resolve(listings, start, end, False)

    def _resolve(
        self, listings: Sequence[Instrument], start: date, end: date, legacy: bool
    ) -> ResolvedSeries | SeriesUnavailable:
        for name, value in (("start", start), ("end", end)):
            if isinstance(value, datetime) or not isinstance(value, date):
                raise ValueError(f"{name} must be a date")
        if start > end:
            raise ValueError("start must not be after end")
        retrieved_at = self._clock()  # one reading per call, shared by every attempt
        if not _aware(retrieved_at):
            raise ValueError("the clock must return a timezone-aware datetime")

        attempts: list[SeriesAttempt] = []
        for listing in dict.fromkeys(listings):
            try:
                answer = self._provider.get_daily_bars(listing, start, end, retrieved_at)
            except Exception as exc:  # a provider must not raise; contain it, and do not try another listing
                attempts.append(SeriesAttempt(listing, AttemptOutcome.PROVIDER_ERROR, f"provider raised {type(exc).__name__}"))
                return SeriesUnavailable(tuple(attempts), legacy)
            if isinstance(answer, BarFailure):
                outcome = _FAILURE_OUTCOME[answer.kind]
                attempts.append(SeriesAttempt(listing, outcome, answer.detail))
                if outcome is AttemptOutcome.PROVIDER_ERROR:
                    return SeriesUnavailable(tuple(attempts), legacy)  # a transient failure must not swap the listing
                continue
            try:
                series = build_series(answer, listing, start, end, retrieved_at)
            except (ValueError, TypeError) as exc:
                attempts.append(SeriesAttempt(listing, AttemptOutcome.INVALID_BARS, str(exc)))
                continue
            if series.bar_count == 0:
                attempts.append(SeriesAttempt(listing, AttemptOutcome.NO_ELIGIBLE_BARS, "no bar before the retrieval-local date"))
                continue
            attempts.append(SeriesAttempt(listing, AttemptOutcome.USED))
            return ResolvedSeries(series, tuple(attempts), legacy)
        return SeriesUnavailable(tuple(attempts), legacy)
