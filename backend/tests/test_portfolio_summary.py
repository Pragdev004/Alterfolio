"""Pure valuation (FR-8/FR-9): holdings from the unchanged fold + provider outcomes -> summary."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from uuid import UUID

import pytest

from app.domain.enums import Currency, Exchange, TradeSide
from app.domain.instrument import Instrument
from app.providers.market.port import MarketQuote, QuoteFailure, QuoteFailureKind
from app.services.holdings import LedgerEntry, fold_holdings
from app.services.portfolio_summary import (
    FUTURE_TOLERANCE,
    PortfolioSummaryService,
    QuoteStatus,
    ValuationStatus,
    quote_candidates,
    value_holdings,
)

NOW = datetime(2026, 3, 2, 10, 0, tzinfo=timezone.utc)
STALE = timedelta(days=7)
ISIN_A, ISIN_B = "ZZ0AAAAAAAA1", "ZZ0BBBBBBBB2"
A_NSE, A_BSE = Instrument("AAA", Exchange.NSE), Instrument("AAA", Exchange.BSE)
B_NSE = Instrument("BBB", Exchange.NSE)
LEG = Instrument("LEG", Exchange.NSE)
_n = 0


def entry(inst, qty="10", price="100", isin=ISIN_A, side="BUY", minutes=0, fee="0"):
    global _n
    _n += 1
    return LedgerEntry(
        id=UUID(int=_n), instrument=inst, side=TradeSide(side), quantity=D(qty), price_per_unit=D(price),
        brokerage_fee=D(fee), taxes=D(0), trade_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=minutes),
        recorded_at=datetime(2026, 1, 2, tzinfo=timezone.utc) + timedelta(seconds=_n), isin=isin,
    )


def quote(inst, price="120.5", age=timedelta(hours=1), **kw):
    fields = dict(
        instrument=inst, price=D(price), currency=Currency.INR, price_timestamp=NOW - age, retrieved_at=NOW, source="fake",
    )
    fields.update(kw)
    return MarketQuote(**fields)


def fail(kind=QuoteFailureKind.NOT_FOUND):
    return QuoteFailure(kind, "x")


def value(entries, outcomes, trades=None):
    return value_holdings(
        fold_holdings(entries), outcomes, valuation_time=NOW, stale_after=STALE,
        total_trades=len(entries) if trades is None else trades,
    )


def test_single_holding_valued_with_exact_decimals():
    s = value([entry(A_NSE, "10", "100")], {A_NSE: quote(A_NSE, "120.5")})
    (h,) = s.holdings
    assert (h.quote_status, h.market_value, h.unrealized_pnl) == (QuoteStatus.VALUED, D("1205.0"), D("205.0"))
    assert h.quote.instrument == A_NSE
    assert s.valuation_status is ValuationStatus.COMPLETE
    assert (s.total_invested, s.total_market_value, s.total_unrealized_pnl) == (D(1000), D("1205.0"), D("205.0"))
    assert s.total_trades == 1 and s.cost_basis_complete


def test_decimal_arithmetic_has_no_float_error():
    s = value([entry(A_NSE, "3", "0.1")], {A_NSE: quote(A_NSE, "0.2")})
    assert s.holdings[0].market_value == D("0.6") and s.total_unrealized_pnl == D("0.3")


def test_fees_are_part_of_cost_so_pnl_uses_invested_amount():
    s = value([entry(A_NSE, "10", "100", fee="20")], {A_NSE: quote(A_NSE, "100")})
    assert s.holdings[0].unrealized_pnl == D("-20")


def test_multiple_holdings_complete_and_ordered_like_holdings():
    es = [entry(B_NSE, isin=ISIN_B), entry(A_NSE)]
    s = value(es, {A_NSE: quote(A_NSE, "110"), B_NSE: quote(B_NSE, "90")})
    assert [h.holding.key.isin for h in s.holdings] == [ISIN_A, ISIN_B]
    assert s.valuation_status is ValuationStatus.COMPLETE
    assert s.total_market_value == D(2000) and s.total_unrealized_pnl == D(0)


def test_missing_quote_is_unvalued_never_estimated():
    s = value([entry(A_NSE)], {})
    (h,) = s.holdings
    assert h.quote_status is QuoteStatus.PROVIDER_ERROR  # provider omitted it: not silently "not found"
    assert (h.quote, h.market_value, h.unrealized_pnl) == (None, None, None)
    assert s.valuation_status is ValuationStatus.UNAVAILABLE
    assert s.total_market_value is None and s.total_unrealized_pnl is None and s.total_invested == D(1000)


def test_mixed_valued_and_unvalued_is_partial_and_totals_cover_valued_only():
    es = [entry(A_NSE), entry(B_NSE, isin=ISIN_B)]
    s = value(es, {A_NSE: quote(A_NSE, "110"), B_NSE: fail()})
    assert s.valuation_status is ValuationStatus.PARTIAL
    assert [h.quote_status for h in s.holdings] == [QuoteStatus.VALUED, QuoteStatus.NOT_FOUND]
    assert s.total_market_value == D(1100) and s.total_invested == D(2000)


@pytest.mark.parametrize(
    "kind,status",
    [
        (QuoteFailureKind.NOT_FOUND, QuoteStatus.NOT_FOUND),
        (QuoteFailureKind.PROVIDER_ERROR, QuoteStatus.PROVIDER_ERROR),
        (QuoteFailureKind.INVALID_RESPONSE, QuoteStatus.INVALID),
    ],
)
def test_provider_failure_stays_distinguishable_from_a_missing_quote(kind, status):
    s = value([entry(A_NSE)], {A_NSE: fail(kind)})
    assert s.holdings[0].quote_status is status and s.valuation_status is ValuationStatus.UNAVAILABLE


def test_stale_quote_is_not_valued_and_boundary_is_inclusive_of_the_threshold():
    stale = value([entry(A_NSE)], {A_NSE: quote(A_NSE, age=STALE + timedelta(seconds=1))})
    assert stale.holdings[0].quote_status is QuoteStatus.STALE and stale.valuation_status is ValuationStatus.UNAVAILABLE
    edge = value([entry(A_NSE)], {A_NSE: quote(A_NSE, age=STALE)})
    assert edge.holdings[0].quote_status is QuoteStatus.VALUED


@pytest.mark.parametrize(
    "bad",
    [
        dict(price=D(0)), dict(price=D(-1)), dict(price=D("NaN")), dict(price=D(10**15)),
        dict(price_timestamp=datetime(2026, 3, 2, 9, 0)),
        dict(price_timestamp=NOW + FUTURE_TOLERANCE + timedelta(seconds=1)),
    ],
)
def test_defensively_rejects_bad_quotes_even_from_a_buggy_provider(bad):
    s = value([entry(A_NSE)], {A_NSE: quote(A_NSE, **bad)})
    assert s.holdings[0].quote_status is QuoteStatus.INVALID


def test_market_value_at_or_above_the_amount_limit_is_invalid_not_capped():
    s = value([entry(A_NSE, "1000000", "1")], {A_NSE: quote(A_NSE, "1000000000")})  # 10^6 x 10^9 = MAX_AMOUNT
    assert s.holdings[0].quote_status is QuoteStatus.INVALID and s.holdings[0].market_value is None


def test_empty_portfolio_is_complete_with_zeros():
    s = value([], {})
    assert s.valuation_status is ValuationStatus.COMPLETE and s.holdings == ()
    assert (s.total_invested, s.total_market_value, s.total_unrealized_pnl, s.total_trades) == (D(0), D(0), D(0), 0)


def test_fully_exited_holding_is_not_a_position_to_value():
    es = [entry(A_NSE, "10"), entry(A_NSE, "10", side="SELL", minutes=5)]
    s = value(es, {}, trades=2)
    assert s.holdings == () and s.valuation_status is ValuationStatus.COMPLETE and s.total_trades == 2


def test_isin_holding_quotes_nse_first_and_falls_back_to_bse_reporting_the_listing_used():
    es = [entry(A_BSE), entry(A_NSE, minutes=1)]
    assert [i.exchange for i in quote_candidates(fold_holdings(es)[0])] == [Exchange.NSE, Exchange.BSE]
    both = value(es, {A_NSE: quote(A_NSE, "100"), A_BSE: quote(A_BSE, "999")})
    assert both.holdings[0].quote.instrument == A_NSE and both.holdings[0].market_value == D(2000)
    fb = value(es, {A_NSE: fail(QuoteFailureKind.PROVIDER_ERROR), A_BSE: quote(A_BSE, "99")})
    h = fb.holdings[0]
    assert h.quote_status is QuoteStatus.VALUED and h.quote.instrument == A_BSE and h.market_value == D(1980)
    none = value(es, {A_NSE: fail(QuoteFailureKind.PROVIDER_ERROR), A_BSE: fail()})
    assert none.holdings[0].quote_status is QuoteStatus.PROVIDER_ERROR  # status of the first candidate (NSE)


def test_stale_nse_falls_back_to_a_fresh_bse_quote_of_the_same_isin():
    es = [entry(A_NSE), entry(A_BSE, minutes=1)]
    s = value(es, {A_NSE: quote(A_NSE, age=timedelta(days=30)), A_BSE: quote(A_BSE, "50")})
    assert s.holdings[0].quote.instrument == A_BSE


def test_null_isin_legacy_holding_uses_only_its_own_listing():
    es = [entry(LEG, isin=None), entry(A_NSE)]
    outcomes = {LEG: fail(), A_NSE: quote(A_NSE, "200"), Instrument("LEG", Exchange.BSE): quote(Instrument("LEG", Exchange.BSE))}
    s = value(es, outcomes)
    by = {h.holding.key.isin: h for h in s.holdings}
    assert by[None].quote_status is QuoteStatus.NOT_FOUND and by[ISIN_A].quote_status is QuoteStatus.VALUED
    assert [i for i in quote_candidates(by[None].holding)] == [LEG]


def test_same_symbol_on_different_exchanges_under_different_isins_is_not_merged():
    es = [entry(A_NSE, isin=ISIN_A), entry(A_BSE, isin=ISIN_B)]
    s = value(es, {A_NSE: quote(A_NSE, "10"), A_BSE: quote(A_BSE, "20")})
    assert [(h.quote.instrument, h.market_value) for h in s.holdings] == [(A_NSE, D(100)), (A_BSE, D(200))]


def test_cost_basis_complete_is_carried_from_holdings():
    imported = entry(A_NSE)
    object.__setattr__(imported, "charges_provided", False)
    s = value([imported], {A_NSE: quote(A_NSE)})
    assert s.cost_basis_complete is False and s.holdings[0].holding.cost_basis_complete is False


def test_naive_valuation_time_is_rejected():
    with pytest.raises(ValueError):
        value_holdings([], {}, valuation_time=datetime(2026, 1, 1), stale_after=STALE, total_trades=0)


def test_result_does_not_depend_on_future_dated_quote_inputs_beyond_tolerance():
    s = value([entry(A_NSE)], {A_NSE: quote(A_NSE, price_timestamp=NOW + timedelta(days=1))})
    assert s.holdings[0].quote_status is QuoteStatus.INVALID


class _Ledger:
    def __init__(self, holdings, count):
        self._h, self._c = holdings, count

    def holdings(self, *, user_id):
        return self._h

    def effective_trade_count(self, *, user_id):
        return self._c


def test_service_turns_a_raising_provider_into_provider_errors_not_prices():
    class Boom:
        def get_quotes(self, instruments, retrieved_at):
            raise RuntimeError("adapter bug")

    svc = PortfolioSummaryService(_Ledger(fold_holdings([entry(A_NSE)]), 1), Boom(), clock=lambda: NOW, stale_after=STALE)
    s = svc.summary(user_id=UUID(int=1))
    assert s.holdings[0].quote_status is QuoteStatus.PROVIDER_ERROR and s.valuation_status is ValuationStatus.UNAVAILABLE


def test_service_does_not_call_the_provider_for_an_empty_portfolio():
    class Never:
        def get_quotes(self, instruments, retrieved_at):
            raise AssertionError("no instruments to quote")

    svc = PortfolioSummaryService(_Ledger([], 0), Never(), clock=lambda: NOW, stale_after=STALE)
    assert svc.summary(user_id=UUID(int=1)).valuation_status is ValuationStatus.COMPLETE


def test_service_requests_each_listing_once_with_the_injected_clock():
    calls = []

    class Spy:
        def get_quotes(self, instruments, retrieved_at):
            calls.append((list(instruments), retrieved_at))
            return {i: quote(i) for i in instruments}

    es = [entry(A_NSE), entry(A_BSE, minutes=1), entry(B_NSE, isin=ISIN_B)]
    svc = PortfolioSummaryService(_Ledger(fold_holdings(es), 3), Spy(), clock=lambda: NOW, stale_after=STALE)
    svc.summary(user_id=UUID(int=1))
    assert calls == [([A_NSE, A_BSE, B_NSE], NOW)]
