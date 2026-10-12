"""MarketSeries: an immutable run of eligible daily bars for ONE listing, with provenance and point-in-time truncation.

Rules (Feature 004 plan, sections 5, 6, 8):
- Eligibility: a bar belongs to a series only if its session date is strictly before the exchange-local calendar date of
  the series cutoff. This is a conservative historical-bar eligibility rule, not a market-close-time assertion.
- `truncated_to(T)` only NARROWS. It is not an "as-known-at-T" query: values are as fetched, and T may never exceed the
  current cutoff, so a series cannot be widened or made to look like it covers more than it was built from.
- Gaps are never filled, resampled or aligned. Coverage is exposed as facts (count, first/last session date); whether it
  is sufficient is a decision for the caller.
"""

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from functools import cached_property

from app.domain.enums import Currency
from app.domain.instrument import Instrument
from .bar import MarketBar
from .exchange_time import local_date
from .fingerprint import FREQUENCY, canonical_decimal, compute_fingerprint, iso_utc
from .provenance import DataProvenance

SCHEMA_VERSION = 1
MAX_BARS = 6000
MAX_OFFSET = timedelta(hours=14)
_ONE_DAY = timedelta(days=1)


@dataclass(frozen=True)
class MarketSeries:
    instrument: Instrument
    currency: Currency
    bars: tuple[MarketBar, ...]
    exchange_utc_offset: timedelta
    cutoff: datetime  # no bar on or after local_date(cutoff) is present; equals retrieved_at until truncated
    observed_through: date  # last local date the series speaks for (no claim about dates after it)
    provenance: DataProvenance

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, Instrument):
            raise TypeError("instrument must be an Instrument")
        if not isinstance(self.currency, Currency):
            raise TypeError("currency must be a Currency")
        if not isinstance(self.exchange_utc_offset, timedelta):
            raise TypeError("exchange_utc_offset must be a timedelta")
        if abs(self.exchange_utc_offset) > MAX_OFFSET:
            raise ValueError("exchange_utc_offset must be within 14 hours of UTC")
        if self.cutoff.tzinfo is None or self.cutoff.utcoffset() is None:
            raise ValueError("cutoff must be timezone-aware")
        if not isinstance(self.provenance, DataProvenance):
            raise TypeError("provenance must be a DataProvenance")
        if self.cutoff > self.provenance.retrieved_at:
            raise ValueError("cutoff must not be later than retrieved_at")
        if not isinstance(self.bars, tuple) or not all(isinstance(b, MarketBar) for b in self.bars):
            raise TypeError("bars must be a tuple of MarketBar")
        if len(self.bars) > MAX_BARS:
            raise ValueError(f"a series holds at most {MAX_BARS} bars")
        if self.observed_through > local_date(self.cutoff, self.exchange_utc_offset) - _ONE_DAY:
            raise ValueError("observed_through must be before the local date of the cutoff")
        previous: MarketBar | None = None
        for bar in self.bars:
            if local_date(bar.timestamp, self.exchange_utc_offset) != bar.session_date:
                raise ValueError(f"session_date {bar.session_date} does not match its timestamp in the exchange offset")
            if bar.session_date > self.observed_through:
                raise ValueError(f"bar {bar.session_date} is not eligible: it is not before the cutoff's local date")
            if previous is not None and not (
                previous.timestamp < bar.timestamp and previous.session_date < bar.session_date
            ):
                raise ValueError("bars must be strictly increasing in time with one bar per session date")
            previous = bar

    @classmethod
    def from_eligible_bars(
        cls,
        *,
        instrument: Instrument,
        currency: Currency,
        bars: tuple[MarketBar, ...],
        exchange_utc_offset: timedelta,
        provenance: DataProvenance,
    ) -> "MarketSeries":
        """A fresh series: cutoff = retrieved_at; the caller has already excluded ineligible bars (the constructor
        rejects any that remain)."""
        cutoff = provenance.retrieved_at
        return cls(
            instrument=instrument,
            currency=currency,
            bars=bars,
            exchange_utc_offset=exchange_utc_offset,
            cutoff=cutoff,
            observed_through=local_date(cutoff, exchange_utc_offset) - _ONE_DAY,
            provenance=provenance,
        )

    # ---- coverage facts (never a verdict) ----------------------------------------------------------------------

    @property
    def bar_count(self) -> int:
        return len(self.bars)

    @property
    def first_session_date(self) -> date | None:
        return self.bars[0].session_date if self.bars else None

    @property
    def last_session_date(self) -> date | None:
        return self.bars[-1].session_date if self.bars else None

    @cached_property
    def fingerprint(self) -> str:
        return compute_fingerprint(
            source=self.provenance.source, instrument=self.instrument, currency=self.currency, bars=self.bars
        )

    # ---- point-in-time ------------------------------------------------------------------------------------------

    def truncated_to(self, t: datetime) -> "MarketSeries":
        """Keep the bars whose session date is strictly before the local date of `t`. Narrowing only.

        ValueError for a naive `t` or any `t` later than the current cutoff (so never later than retrieved_at, and a
        truncated series cannot be widened). `t == cutoff` is allowed and changes nothing.
        """
        if t.tzinfo is None or t.utcoffset() is None:
            raise ValueError("t must be timezone-aware")
        if t > self.cutoff:
            raise ValueError(
                "t is later than the series cutoff: truncated_to narrows a series, it is not an as-known-at query"
            )
        t_date = local_date(t, self.exchange_utc_offset)
        return replace(
            self,
            bars=tuple(b for b in self.bars if b.session_date < t_date),
            cutoff=t,
            observed_through=min(self.observed_through, t_date - _ONE_DAY),
        )

    # ---- JSON form (design: output contract) --------------------------------------------------------------------

    def to_dict(self) -> dict:
        p = self.provenance
        return {
            "schema_version": SCHEMA_VERSION,
            "as_of": iso_utc(self.cutoff),
            "provenance": {
                "source": p.source,
                "retrieved_at": iso_utc(p.retrieved_at),
                "request_start": p.request_start.isoformat(),
                "request_end": p.request_end.isoformat(),
                "rows_returned": p.rows_returned,
                "empty_rows_excluded": p.empty_rows_excluded,
                "ineligible_bars_excluded": p.ineligible_bars_excluded,
                "eligible_bars_at_fetch": p.eligible_bars_at_fetch,
                "first_eligible_session_date_at_fetch": _iso(p.first_eligible_session_date_at_fetch),
                "last_eligible_session_date_at_fetch": _iso(p.last_eligible_session_date_at_fetch),
                "numeric_policy": p.numeric_policy,
                "close_semantics": p.close_semantics,
                "knowledge_basis": p.knowledge_basis,
                "fingerprint_version": p.fingerprint_version,
                "fingerprint": self.fingerprint,
            },
            "inputs": {
                "instrument": {"symbol": self.instrument.symbol, "exchange": self.instrument.exchange.value},
                "currency": self.currency.value,
                "frequency": FREQUENCY,
                "exchange_utc_offset_seconds": int(self.exchange_utc_offset.total_seconds()),
                "request": {"start": p.request_start.isoformat(), "end": p.request_end.isoformat()},
            },
            "values": {
                "bar_count": self.bar_count,
                "first_session_date": _iso(self.first_session_date),
                "last_session_date": _iso(self.last_session_date),
                "bars": [
                    {
                        "timestamp": iso_utc(b.timestamp),
                        "session_date": b.session_date.isoformat(),
                        "open": canonical_decimal(b.open),
                        "high": canonical_decimal(b.high),
                        "low": canonical_decimal(b.low),
                        "close": canonical_decimal(b.close),
                        "adjusted_close": canonical_decimal(b.adjusted_close),
                        "volume": b.volume,
                    }
                    for b in self.bars
                ],
            },
        }


def _iso(value: date | None) -> str | None:
    return None if value is None else value.isoformat()
