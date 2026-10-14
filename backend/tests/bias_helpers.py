"""Synthetic builders for the Feature 006 tests (invented symbols and prices only). Session i = START + i days."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D

from app.domain.enums import Currency, Exchange, TradeSide
from app.domain.instrument import Instrument
from app.quant.bias_cost.types import BiasParameters, ChargeValue, LedgerTrade
from app.quant.bias_cost.validation import validate_inputs
from app.quant.market_data.bar import MarketBar
from app.quant.market_data.series import MarketSeries
from market_helpers import IST_OFFSET, RETRIEVED, mk_provenance

START = date(2026, 1, 5)
WINDOW_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 3, 9, tzinfo=timezone.utc)
NSE_A = Instrument("AAATEST", Exchange.NSE)
NSE_B = Instrument("BBBTEST", Exchange.NSE)
NSE_C = Instrument("CCCTEST", Exchange.NSE)
BSE_A = Instrument("AAATEST", Exchange.BSE)
BUY, SELL = TradeSide.BUY, TradeSide.SELL


def session(i: int) -> date:
    return START + timedelta(days=i)


def params(**kw) -> BiasParameters:
    base = dict(chasing_lookback_sessions=20, window_start=WINDOW_START, window_end=WINDOW_END,
                formula_version="bias-v1", rule_set_version="archetype-v1")
    base.update(kw)
    return BiasParameters(**base)


def series(instrument: Instrument, closes, offset=IST_OFFSET) -> MarketSeries:
    """One bar per session; `closes` is a list of Decimals (or a dict {index: close} over a flat 100 baseline of 60)."""
    if isinstance(closes, dict):
        values = [closes.get(i, D("100")) for i in range(60)]
    else:
        values = list(closes)
    dates = [session(i) for i in range(len(values))]
    bars = tuple(
        MarketBar(timestamp=datetime(d.year, d.month, d.day, 3, 45, tzinfo=timezone.utc), session_date=d, open=c, high=c,
                  low=c, close=c, adjusted_close=c, volume=1000)
        for d, c in zip(dates, values)
    )
    return MarketSeries.from_eligible_bars(instrument=instrument, currency=Currency.INR, bars=bars,
                                           exchange_utc_offset=offset, provenance=mk_provenance(dates, RETRIEVED))


def trade(trade_id: str, instrument: Instrument, side: TradeSide, qty, price, i: int, charges=None,
          hour: int = 5, minute: int = 0) -> LedgerTrade:
    d = session(i)
    return LedgerTrade(trade_id=trade_id, instrument=instrument, isin=None, side=side, quantity=D(str(qty)),
                       price=D(str(price)), trade_timestamp=datetime(d.year, d.month, d.day, hour, minute, tzinfo=timezone.utc),
                       charges=charges or ChargeValue.unknown())


def known(fees="1", taxes="0.5") -> ChargeValue:
    return ChargeValue(known=True, fees=D(fees), taxes=D(taxes))


def validated(trades, serieses, **param_kw):
    return validate_inputs(trades, {s.instrument: s for s in serieses}, params(**param_kw))
