"""Portfolio summary (FR-8): holdings (from the ledger fold, unchanged) valued with provider quotes (FR-9).

`value_holdings` is pure. Arithmetic is Decimal under MONEY_CONTEXT, never rounded here (the API quantizes once).
A holding without a usable quote is reported as unvalued; no price is ever estimated, defaulted, or carried over.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from uuid import UUID

from app.domain.enums import Currency, Exchange
from app.domain.instrument import Instrument
from app.domain.numeric import MAX_AMOUNT, MONEY_CONTEXT
from app.providers.market.port import MarketDataProvider, MarketQuote, QuoteFailure, QuoteFailureKind, QuoteOutcome
from app.services.holdings import Holding
from app.services.ledger import LedgerService

# A quote stamped later than the request by more than this is not an observation we can trust.
FUTURE_TOLERANCE = timedelta(minutes=5)


class ValuationStatus(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"


class QuoteStatus(str, Enum):
    VALUED = "VALUED"
    STALE = "STALE"
    NOT_FOUND = "NOT_FOUND"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    INVALID = "INVALID"


@dataclass(frozen=True)
class ValuedHolding:
    holding: Holding
    quote_status: QuoteStatus
    quote: MarketQuote | None  # set only when quote_status is VALUED
    market_value: Decimal | None
    unrealized_pnl: Decimal | None


@dataclass(frozen=True)
class PortfolioSummary:
    valuation_time: datetime
    valuation_status: ValuationStatus
    total_trades: int
    total_invested: Decimal
    total_market_value: Decimal | None  # valued holdings only; None when UNAVAILABLE
    total_unrealized_pnl: Decimal | None  # valued holdings only; None when UNAVAILABLE
    cost_basis_complete: bool
    holdings: tuple[ValuedHolding, ...]


_FAILURE_STATUS = {
    QuoteFailureKind.NOT_FOUND: QuoteStatus.NOT_FOUND,
    QuoteFailureKind.PROVIDER_ERROR: QuoteStatus.PROVIDER_ERROR,
    QuoteFailureKind.INVALID_RESPONSE: QuoteStatus.INVALID,
}


def quote_candidates(holding: Holding) -> tuple[Instrument, ...]:
    """Listings of one holding in quoting order: NSE first, then BSE. Never any other symbol."""
    return tuple(sorted(holding.listings, key=lambda i: (i.exchange is not Exchange.NSE, i.symbol)))


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _judge(
    outcome: QuoteOutcome | None, retrieved_at: datetime, stale_after: timedelta
) -> tuple[QuoteStatus, MarketQuote | None]:
    if outcome is None:
        return QuoteStatus.PROVIDER_ERROR, None  # the provider did not answer for this listing
    if isinstance(outcome, QuoteFailure):
        return _FAILURE_STATUS[outcome.kind], None
    q = outcome
    if (
        not q.price.is_finite()
        or q.price <= 0
        or q.price >= MAX_AMOUNT
        or q.currency is not Currency.INR
        or not _aware(q.price_timestamp)
        or q.price_timestamp > retrieved_at + FUTURE_TOLERANCE
    ):
        return QuoteStatus.INVALID, None
    if retrieved_at - q.price_timestamp > stale_after:
        return QuoteStatus.STALE, None
    return QuoteStatus.VALUED, q


def value_holdings(
    holdings: Sequence[Holding],
    outcomes: dict[Instrument, QuoteOutcome],
    *,
    valuation_time: datetime,
    stale_after: timedelta,
    total_trades: int,
) -> PortfolioSummary:
    if not _aware(valuation_time):
        raise ValueError("valuation_time must be timezone-aware")
    valued_rows: list[ValuedHolding] = []
    for holding in holdings:
        row: ValuedHolding | None = None
        first_status: QuoteStatus | None = None
        for listing in quote_candidates(holding):
            status, quote = _judge(outcomes.get(listing), valuation_time, stale_after)
            market_value = None
            if quote is not None:
                market_value = MONEY_CONTEXT.multiply(holding.quantity, quote.price)
                if market_value >= MAX_AMOUNT:  # reject, never cap or round
                    status, quote = QuoteStatus.INVALID, None
            first_status = first_status or status
            if quote is None:
                continue
            pnl = MONEY_CONTEXT.subtract(market_value, holding.invested_amount)
            row = ValuedHolding(holding, QuoteStatus.VALUED, quote, market_value, pnl)
            break
        if row is None:
            row = ValuedHolding(holding, first_status or QuoteStatus.NOT_FOUND, None, None, None)
        valued_rows.append(row)

    valued = [r for r in valued_rows if r.quote_status is QuoteStatus.VALUED]
    total_invested = Decimal(0)
    for h in holdings:
        total_invested = MONEY_CONTEXT.add(total_invested, h.invested_amount)
    if not valued_rows:
        status = ValuationStatus.COMPLETE
    elif len(valued) == len(valued_rows):
        status = ValuationStatus.COMPLETE
    elif valued:
        status = ValuationStatus.PARTIAL
    else:
        status = ValuationStatus.UNAVAILABLE
    if valued_rows and not valued:
        total_mv = total_pnl = None
    else:
        total_mv = total_pnl = Decimal(0)
        for r in valued:
            total_mv = MONEY_CONTEXT.add(total_mv, r.market_value)
            total_pnl = MONEY_CONTEXT.add(total_pnl, r.unrealized_pnl)
    return PortfolioSummary(
        valuation_time=valuation_time,
        valuation_status=status,
        total_trades=total_trades,
        total_invested=total_invested,
        total_market_value=total_mv,
        total_unrealized_pnl=total_pnl,
        cost_basis_complete=all(h.cost_basis_complete for h in holdings),
        holdings=tuple(valued_rows),
    )


class PortfolioSummaryService:
    def __init__(
        self,
        ledger: LedgerService,
        provider: MarketDataProvider,
        *,
        clock: Callable[[], datetime],
        stale_after: timedelta,
    ) -> None:
        self._ledger = ledger
        self._provider = provider
        self._clock = clock
        self._stale_after = stale_after

    def summary(self, *, user_id: UUID) -> PortfolioSummary:
        now = self._clock()
        holdings = self._ledger.holdings(user_id=user_id)
        total_trades = self._ledger.effective_trade_count(user_id=user_id)
        instruments = list(dict.fromkeys(i for h in holdings for i in quote_candidates(h)))
        outcomes: dict[Instrument, QuoteOutcome] = {}
        if instruments:
            try:
                outcomes = self._provider.get_quotes(instruments, now)
            except Exception:  # a faulty adapter must read as a provider failure, never as a price or a crash
                outcomes = {
                    i: QuoteFailure(QuoteFailureKind.PROVIDER_ERROR, "provider raised unexpectedly")
                    for i in instruments
                }
        return value_holdings(
            holdings, outcomes, valuation_time=now, stale_after=self._stale_after, total_trades=total_trades
        )
