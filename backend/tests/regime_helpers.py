"""Synthetic builders for the Feature 008 tests (invented symbols, ISINs and prices only). Reuses the Feature 007 world."""

from datetime import date, datetime, timezone
from decimal import Decimal as D

from app.domain.enums import Currency, Exchange, TradeSide
from app.domain.instrument import Instrument
from app.quant.bias_cost.types import BiasParameters, ChargeValue, LedgerTrade
from app.quant.luck_test.features import ListingBars
from app.quant.regime_split.types import RegimeParameters
from luck_helpers import OWN, OWN_ISIN, params as luck_params, reviewed_all, session, world  # noqa: F401

BUY, SELL = TradeSide.BUY, TradeSide.SELL
WINDOW_START = datetime(2025, 9, 1, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 6, 1, tzinfo=timezone.utc)


def led(trade_id: str, side: TradeSide, qty, price, day: int, *, hour: int = 5, minute: int = 0,
        isin: str | None = None, instrument: Instrument = OWN) -> LedgerTrade:
    d = session(day)
    return LedgerTrade(trade_id=trade_id, instrument=instrument, isin=isin, side=side, quantity=D(str(qty)),
                       price=D(str(price)), trade_timestamp=datetime(d.year, d.month, d.day, hour, minute, tzinfo=timezone.utc),
                       charges=ChargeValue.unknown())


def bias_params(**kw) -> BiasParameters:
    base = dict(chasing_lookback_sessions=20, window_start=WINDOW_START, window_end=WINDOW_END,
                formula_version="bias-v1", rule_set_version="archetype-v1")
    base.update(kw)
    return BiasParameters(**base)


def small(**kw) -> RegimeParameters:
    """Window 5 and 10 calibration observations keep the fixtures short: a trip needs 5 + 1 + 10 = 16 bars before it opens."""
    base = dict(volatility_window=5, min_calibration=10, min_trips_per_regime=3)
    base.update(kw)
    return RegimeParameters(**base)


def ledger(days=range(10, 108, 3), *, hold: int = 2, instrument: Instrument = OWN) -> list[LedgerTrade]:
    """One buy and one sell (`hold` days later) per start day: every start day is a separate round trip."""
    out = []
    for d in days:
        out.append(led(f"B{d:03d}", BUY, 10, 100 + d % 7, d, instrument=instrument))
        out.append(led(f"S{d:03d}", SELL, 10, 101 + d % 5, d + hold, instrument=instrument))
    return out


def bars(closes, *, step: int = 1, start: date = date(2025, 1, 1)) -> ListingBars:
    """A listing straight from closes (Decimals); bar i is on `start + i * step` days. Bypasses MarketSeries on purpose."""
    from datetime import timedelta
    dates = tuple(start + timedelta(days=i * step) for i in range(len(closes)))
    return ListingBars(OWN, timedelta(hours=5, minutes=30), "fp", dates, tuple(D(str(c)) for c in closes))


def wiggle(n: int, amplitude=None) -> list[D]:
    """Alternating up/down closes; `amplitude(i)` (default constant) is the size of the i-th move in percent."""
    out, c = [], D(100)
    for i in range(n):
        a = D(amplitude(i)) if amplitude else D(1)
        c = c * (1 + (a if i % 2 == 0 else -a) / D(100))
        out.append(c)
    return out


__all__ = ["Currency", "Exchange"]


def long_series(instrument: Instrument, n: int = 200, *, k: int = 0, skip=()):
    """A real MarketSeries of `n` daily bars from the Feature 007 start date, long enough for the default 61 + 120 bars."""
    from datetime import timezone
    from luck_helpers import START, closes
    from app.domain.enums import Currency as Cur
    from app.quant.market_data.bar import MarketBar
    from app.quant.market_data.series import MarketSeries
    from market_helpers import IST_OFFSET, mk_provenance
    from datetime import timedelta
    values = closes(k, n)
    idx = [i for i in range(n) if i not in set(skip)]
    dates = [START + timedelta(days=i) for i in idx]
    out = tuple(MarketBar(timestamp=datetime(d.year, d.month, d.day, 3, 45, tzinfo=timezone.utc), session_date=d,
                          open=values[i], high=values[i], low=values[i], close=values[i], adjusted_close=values[i], volume=1000)
                for i, d in zip(idx, dates))
    retrieved = datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc)
    return MarketSeries.from_eligible_bars(instrument=instrument, currency=Cur.INR, bars=out, exchange_utc_offset=IST_OFFSET,
                                           provenance=mk_provenance(dates, retrieved))
