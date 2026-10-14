"""Synthetic builders for the Feature 007 tests (invented symbols, ISINs and prices only). Session i = START + i days."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D

from app.domain.enums import Currency, Exchange
from app.domain.instrument import Instrument
from app.quant.luck_test.types import Candidate, LuckParameters, Membership, TripInput
from app.quant.market_data.bar import MarketBar
from app.quant.market_data.series import MarketSeries
from market_helpers import IST_OFFSET, RETRIEVED, mk_provenance

START = date(2025, 10, 1)
OWN = Instrument("TRDTEST", Exchange.NSE)
OWN_ISIN = "INE000000000"
N_BARS = 120


def session(i: int) -> date:
    return START + timedelta(days=i)


def isin(k: int) -> str:
    return f"INE{k:09d}"


def candidate(k: int) -> Candidate:
    return Candidate(Instrument(f"C{k:02d}TEST", Exchange.NSE), isin(k))


def closes(k: int, n: int = N_BARS, override=None, post=None) -> list[D]:
    """Deterministic, strictly positive closes whose drift and wiggle both depend on `k`."""
    out = []
    for i in range(n):
        c = D(100) + D(k) * D(i) / D(10) + D((i * 7 + k * 13) % 11) * D(k % 5 + 1) / D(4)
        if override and i in override:
            c = D(override[i])
        if post is not None:
            c = post(i, c)
        out.append(c)
    return out


def series(instrument: Instrument, k: int, *, n: int = N_BARS, override=None, post=None, skip=(), length=None) -> MarketSeries:
    values = closes(k, n, override, post)
    idx = [i for i in range(length if length is not None else n) if i not in set(skip)]
    dates = [session(i) for i in idx]
    bars = tuple(
        MarketBar(timestamp=datetime(d.year, d.month, d.day, 3, 45, tzinfo=timezone.utc), session_date=d, open=values[i],
                  high=values[i], low=values[i], close=values[i], adjusted_close=values[i], volume=1000)
        for i, d in zip(idx, dates)
    )
    return MarketSeries.from_eligible_bars(instrument=instrument, currency=Currency.INR, bars=bars,
                                           exchange_utc_offset=IST_OFFSET, provenance=mk_provenance(dates, RETRIEVED))


def world(n_universe: int = 14, *, per=None, own_kwargs=None):
    """(series mapping incl. the traded listing, universe, memberships for every candidate). `per[k]` = series kwargs."""
    per = per or {}
    universe = tuple(candidate(k) for k in range(1, n_universe + 1))
    mapping = {OWN: series(OWN, 0, **(own_kwargs or {}))}
    for c in universe:
        k = int(c.isin[3:])
        mapping[c.instrument] = series(c.instrument, k, **per.get(k, {}))
    members = tuple(Membership(c.isin, session(0)) for c in universe[:12])
    return mapping, universe, members


def trip(trip_id: str = "T1", d: int = 70, j: int = 80, cost: str = "1000", proceeds: str = "1100",
         instrument: Instrument = OWN, trip_isin: str | None = OWN_ISIN) -> TripInput:
    return TripInput(trip_id, instrument, trip_isin, session(d), session(j), D(cost), D(proceeds))


def reviewed_all(trips, universe) -> frozenset:
    """A coverage declaration listing every traded and universe listing (the tests' default 'fully reviewed' caller)."""
    return frozenset({t.instrument for t in trips} | {c.instrument for c in universe})


def params(**kw) -> LuckParameters:
    base = dict(seed=7, as_of=RETRIEVED, portfolio_count=50, bootstrap_replicates=200)
    base.update(kw)
    return LuckParameters(**base)
