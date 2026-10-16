"""Synthetic world for Feature 011 tests: invented symbols/ISINs, a fake bar provider, trades in a real (SQLite) ledger."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
from uuid import UUID, uuid4

from app.domain.enums import AssetType, Currency, Exchange, MarketSession, TradeSide, TradeSource, TradeStatus
from app.domain.instrument import Instrument
from app.providers.market.history_port import BarFailure, BarFailureKind, RawBar, RawBarBatch
from app.quant.luck_test.types import Candidate, Membership
from app.quant.regime_split.types import RegimeParameters
from app.repositories.trade_repository import TradeRepository
from app.services.portfolio_analysis import AnalysisConfig

IST = timedelta(hours=5, minutes=30)
NOW = datetime(2026, 12, 1, 10, 0, tzinfo=timezone.utc)  # the injected clock: bars up to 2026-11-30 are eligible
BARS_FROM = date(2025, 1, 1)
D_ASOF = date(2026, 9, 30)
TRADED = Instrument("TEST1", Exchange.NSE)
TRADED_ISIN = "INE000T01011"
UNIVERSE = tuple(Candidate(Instrument(f"UNIV{i:02d}", Exchange.NSE), f"INE{i:03d}U01011") for i in range(12))
KNOWN = {TRADED: 0, **{c.instrument: i + 1 for i, c in enumerate(UNIVERSE)}}


def close_on(k: int, d: date) -> D:
    """Deterministic positive close; volatility changes in 45-day blocks so regimes differ."""
    i = (d - BARS_FROM).days
    amp = (D("0.2"), D("0.8"), D("1.5"))[(i // 45) % 3]
    return (D(100) + D(i) * D("0.02") + amp * D(((i * 7 + k * 5) % 11) - 5)).quantize(D("0.01"))


class FakeBars:
    """HistoricalBarProvider. `leaky` ignores `end` (returns every day before the clock's date); `perturb_after` scales
    closes after that date by 3, so any leak of a later bar changes a result."""

    def __init__(self, *, leaky: bool = False, perturb_after: date | None = None, missing: frozenset = frozenset()):
        self.leaky, self.perturb_after, self.missing = leaky, perturb_after, missing
        self.calls: list[tuple[Instrument, date, date, datetime]] = []

    def get_daily_bars(self, instrument, start, end, retrieved_at):
        self.calls.append((instrument, start, end, retrieved_at))
        if instrument not in KNOWN or instrument in self.missing:
            return BarFailure(BarFailureKind.NOT_FOUND, "unknown listing")
        last = (retrieved_at.date() - timedelta(days=1)) if self.leaky else end
        bars = []
        d = max(start, BARS_FROM)
        while d <= last:
            c = close_on(KNOWN[instrument], d)
            if self.perturb_after is not None and d > self.perturb_after:
                c = (c * 3).quantize(D("0.01"))
            bars.append(RawBar(timestamp=datetime(d.year, d.month, d.day, 3, 45, tzinfo=timezone.utc), session_date=d,
                               open=c, high=c, low=c, close=c, adjusted_close=c, volume=1000))
            d += timedelta(days=1)
        return RawBarBatch(instrument=instrument, bars=tuple(bars), currency=Currency.INR, source="fake", retrieved_at=retrieved_at,
                           exchange_utc_offset=IST, rows_returned=len(bars), empty_rows_excluded=0)


def config(**kw) -> AnalysisConfig:
    reviewed = frozenset(KNOWN)
    base = dict(universe=UNIVERSE, nifty50=tuple(Membership(c.isin, date(2020, 1, 1)) for c in UNIVERSE),
                corporate_action_listings=frozenset(), corporate_action_reviewed=reviewed, luck_portfolio_count=20,
                luck_bootstrap_replicates=200, regime_parameters=RegimeParameters(min_trips_per_regime=3))
    base.update(kw)
    return AnalysisConfig(**base)


def add_trade(session, user_id: UUID, side: TradeSide, day: date, *, qty="10", instrument=TRADED, isin=TRADED_ISIN,
              recorded_at: datetime | None = None, supersedes: UUID | None = None, status=TradeStatus.EXECUTED,
              price=None, charges_provided=True):
    ts = datetime(day.year, day.month, day.day, 5, 0, tzinfo=timezone.utc)  # 10:30 IST
    px = price if price is not None else close_on(KNOWN[instrument], day)
    return TradeRepository(session).add(
        user_id=user_id, id=uuid4(), symbol=instrument.symbol, name=None, asset_type=AssetType.STOCK, exchange=instrument.exchange,
        currency=Currency.INR, side=side, quantity=D(qty), price_per_unit=D(px), brokerage_fee=D(0), taxes=D(0),
        trade_timestamp=ts, recorded_at=recorded_at or ts + timedelta(hours=1), broker=None, broker_trade_id=None, order_id=None,
        supersedes_trade_id=supersedes, source=TradeSource.MANUAL, market_session=MarketSession.REGULAR, status=status,
        notes=None, isin=isin, charges_provided=charges_provided)


def seed_round_trips(session, user_id: UUID, n: int = 14, *, first: date = date(2026, 3, 2), step: int = 8, hold: int = 3, **kw):
    """n closed round trips on TRADED, a buy then a sell `hold` days later, every `step` days from `first`."""
    out = []
    for k in range(n):
        d = first + timedelta(days=k * step)
        out.append((add_trade(session, user_id, TradeSide.BUY, d, **kw), add_trade(session, user_id, TradeSide.SELL, d + timedelta(days=hold), **kw)))
    session.commit()
    return out


def walk_floats(obj, path="root"):
    """Yield the path of every float found in a nested JSON-like structure."""
    if isinstance(obj, float):
        yield path
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk_floats(v, f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            yield from walk_floats(v, f"{path}[{i}]")
