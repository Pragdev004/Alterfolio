"""Feature 013a: response models of the analysis endpoints (they document the contract in OpenAPI and validate every body).

Every number is a NumberOut: the exact `value` (or null), the server-formatted `display`, and a reason when it is missing.
Imports pydantic only; the bodies are built by `api/analysis_presenter.py`.
"""

from pydantic import BaseModel


class NumberOut(BaseModel):
    value: str | None
    display: str
    unavailable_reason: str | None  # the code or short text from the analysis
    reason_text: str | None  # the same reason as a plain-English sentence, for display


class DateOut(BaseModel):
    iso: str
    display: str


class SampleOut(BaseModel):
    have: int | None
    needed: int
    enough: bool
    text: str


class ReasonOut(BaseModel):
    subject: str
    reason: str
    reason_text: str


class NameValueOut(BaseModel):
    name: str
    value: str


class ErrorOut(BaseModel):
    analysis: str
    reason: str
    reason_text: str


class BaselineSummaryOut(BaseModel):
    trips_used: int | None
    trips_evaluated: int | None
    mean_excess: NumberOut
    mean_percentile: NumberOut
    ci_lower: NumberOut
    ci_upper: NumberOut
    position: str | None
    sample: SampleOut
    mean_excess_direction: str | None  # "ahead" | "behind" | "level" | "inconclusive" (interval touches zero); null when unavailable
    mean_excess_direction_text: str | None  # "not distinguishable from zero" for inconclusive, else the direction word


class LuckSummariesOut(BaseModel):
    ALT: BaselineSummaryOut
    NIFTY: BaselineSummaryOut


class OutcomeOut(BaseModel):
    portfolios_text: str | None  # "500 portfolios built from 9 other Nifty Bank stocks"; null when unavailable
    percentile: NumberOut
    excess: NumberOut
    mean_return: NumberOut
    portfolio_count: int | None  # null when the outcome is unavailable (never 0)
    pool_size: int | None
    lost_count: int | None
    unavailable_reason: str | None
    reason_text: str | None
    excess_direction: str | None  # "ahead" | "behind" | "level"; null when unavailable


class BinOut(BaseModel):
    lower: NumberOut
    upper: NumberOut
    count: int


class HistogramOut(BaseModel):
    """The drawn portfolios' returns in equal-width bins; `marker_bin` holds the trip's own return."""

    bins: list[BinOut]
    marker_bin: int
    actual_return: NumberOut
    lower: NumberOut
    upper: NumberOut
    portfolio_count: int
    text: str  # a text equivalent of the chart


class HistogramsOut(BaseModel):
    ALT: HistogramOut | None
    NIFTY: HistogramOut | None


class RegimeTagOut(BaseModel):
    regime: str | None
    volatility: NumberOut
    low_threshold: NumberOut
    high_threshold: NumberOut
    calibration_count: int | None
    reason: str | None
    reason_text: str | None


class PickOut(BaseModel):
    rank: int
    symbol: str
    exchange: str
    isin: str
    return_ratio: NumberOut


class PickExclusionOut(BaseModel):
    baseline: str
    isin: str
    symbol: str | None  # the listing's ticker when known
    exchange: str | None
    reason: str
    reason_text: str


class TripRowOut(BaseModel):
    trip_id: str
    symbol: str
    exchange: str
    open_session: DateOut
    close_session: DateOut
    evaluated: bool
    actual_return: NumberOut
    actual_return_basis: str
    alternatives_kind: str | None
    alternatives_label: str | None
    alt: OutcomeOut | None
    nifty: OutcomeOut | None
    survivorship_flag: bool | None
    regime: RegimeTagOut
    unavailable_reason: str | None
    reason_text: str | None


class TripDetailRowOut(TripRowOut):
    histograms: HistogramsOut
    picks: list[PickOut]
    exclusions: list[PickExclusionOut]
    zero_variance_features: list[str]


class TripsSummaryOut(LuckSummariesOut):
    trip_count: int | None
    trip_count_unavailable_reason: str | None
    trip_count_reason_text: str | None
    trips_evaluated: int | None
    alternatives_kind: str | None
    alternatives_label: str | None


class GroupOut(LuckSummariesOut):
    label: str
    alternatives_kind: str | None
    alternatives_label: str | None
    trip_count: int


class ExcludedListingOut(BaseModel):
    symbol: str
    exchange: str
    reason: str
    reason_text: str
    trips: int


class TripsOut(BaseModel):
    as_of: DateOut
    as_of_defaulted: bool
    summary: TripsSummaryOut
    groups: list[GroupOut]
    trips: list[TripRowOut]
    excluded_listings: list[ExcludedListingOut]
    caveats: list[str]
    analysis_errors: list[ErrorOut]
    luck_limitations: list[str]
    alternatives_note: str


class TripDetailOut(BaseModel):
    as_of: DateOut
    as_of_defaulted: bool
    trip: TripDetailRowOut
    caveats: list[str]
    alternatives_note: str


class BiasOut(BaseModel):
    kind: str
    cost_inr: NumberOut
    gross_cost_inr: NumberOut
    fees_known: NumberOut
    fee_status: str | None
    unknown_fee_trade_count: int | None
    exclusions: list[ReasonOut]
    details: list[NameValueOut]


class MetricOut(BaseModel):
    name: str
    value: str
    display: str
    unit: str  # always "unitless": the quant does not declare units for archetype metrics


class ProfileOut(BaseModel):
    archetype_id: str | None
    unavailable_reason: str | None
    reason_text: str | None
    supporting_metrics: list[MetricOut]


class BiasesOut(BaseModel):
    as_of: DateOut
    as_of_defaulted: bool
    biases: list[BiasOut]
    profile: ProfileOut
    sample: SampleOut
    caveats: list[str]
    analysis_errors: list[ErrorOut]


class BlockOut(BaseModel):
    regime: str
    trip_ids: list[str]
    trip_count: int | None
    sample: SampleOut
    luck: LuckSummariesOut | None
    luck_unavailable_reason: str | None
    luck_reason_text: str | None
    bias: list[BiasOut] | None
    bias_unavailable_reason: str | None
    bias_reason_text: str | None


class RegimesOut(BaseModel):
    as_of: DateOut
    as_of_defaulted: bool
    round_trip_count: int | None
    unclassified_count: int | None
    blocks: list[BlockOut]
    exclusions: list[ReasonOut]
    unavailable_reason: str | None
    reason_text: str | None
    none_ready_text: str | None  # one sentence when no regime has enough trips yet
    limitations: list[str]
    caveats: list[str]
    analysis_errors: list[ErrorOut]


class ThresholdsOut(BaseModel):
    luck_min_trips: NumberOut
    regime_min_trips_per_regime: NumberOut
    bias_min_round_trips: NumberOut


class LimitationsOut(BaseModel):
    luck: list[str]
    regime: list[str]


class MetaOut(BaseModel):
    latest_sealed_as_of: DateOut
    today_ist: DateOut
    last_bar_date: DateOut | None
    last_bar_date_unavailable_reason: str | None
    last_bar_date_reason_text: str | None
    thresholds: ThresholdsOut
    alternatives_note: str
    limitations: LimitationsOut
