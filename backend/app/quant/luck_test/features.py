"""Pre-trade similarity features and ranking (spec sections 3-5; owner-approved definitions for `luck-v1`).

`PreTradeView` holds ONLY the last `keep` closes of sessions strictly BEFORE the decision date: the decision session and
anything later are not in the object at all (future-leakage guard by construction). Outcome prices (`ListingBars.close_on`)
are a separate accessor used only after selection.

Features at the last bar `p` before `d`: momentum = close[p] / close[p-20] - 1; volatility = SAMPLE standard deviation (n-1)
of the 60 daily simple returns ending at `p`. Each feature is z-scored over the ELIGIBLE CANDIDATE POOL (population standard
deviation, n); the traded stock is standardised with the pool's mean and deviation and does not enter them. A zero-spread
feature has no information: its z is 0 for everyone, and it is reported (`zero_variance_features`), never divided by.
"""

import math
from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.domain.instrument import Instrument
from app.quant.market_data.series import MarketSeries

from .numeric_boundary import CALC, ONE, ZERO_FLOAT, to_float
from .types import Candidate

Vector = tuple[float, float]  # (momentum, volatility), both statistics
FEATURE_NAMES = ("momentum", "volatility")


@dataclass(frozen=True)
class PreTradeView:
    """The last `count` closes before the decision date (`count` <= the history asked for). `tail(n)` needs n <= count."""

    _closes: tuple[Decimal, ...]
    count: int

    def tail(self, n: int) -> tuple[Decimal, ...] | None:
        if n < 1 or self.count < n:
            return None
        return self._closes[self.count - n:self.count]


@dataclass(frozen=True)
class ListingBars:
    instrument: Instrument
    offset: timedelta
    fingerprint: str
    dates: tuple[date, ...]
    closes: tuple[Decimal, ...]

    @classmethod
    def build(cls, series: MarketSeries) -> "ListingBars":
        return cls(series.instrument, series.exchange_utc_offset, series.fingerprint,
                   tuple(b.session_date for b in series.bars), tuple(b.close for b in series.bars))

    def before(self, d: date, keep: int) -> PreTradeView:
        """The last `keep` closes with `session_date < d` (fewer when the series starts later)."""
        end = bisect_left(self.dates, d)
        window = self.closes[max(0, end - keep):end]
        return PreTradeView(window, len(window))

    def close_on(self, d: date) -> Decimal | None:
        """The close of the bar on exactly `d` (outcome/entry price), or None. Nothing is filled or carried."""
        i = bisect_left(self.dates, d)
        return self.closes[i] if i < len(self.dates) and self.dates[i] == d else None


def momentum(view: PreTradeView, lookback: int) -> Decimal | None:
    window = view.tail(lookback + 1)
    return None if window is None else CALC.subtract(CALC.divide(window[-1], window[0]), ONE)


def volatility(view: PreTradeView, lookback: int) -> float | None:
    """Sample standard deviation of the last `lookback` simple daily returns (closes before the decision date only)."""
    window = view.tail(lookback + 1)
    if window is None:
        return None
    returns = [to_float(CALC.subtract(CALC.divide(window[i + 1], window[i]), ONE)) for i in range(lookback)]
    mean = math.fsum(returns) / lookback
    return math.sqrt(math.fsum((r - mean) ** 2 for r in returns) / (lookback - 1))


def feature_vector(view: PreTradeView, momentum_lookback: int, volatility_lookback: int) -> Vector | None:
    m = momentum(view, momentum_lookback)
    v = volatility(view, volatility_lookback)
    return None if m is None or v is None else (to_float(m), v)


@dataclass(frozen=True)
class PoolStats:
    """Mean and population standard deviation of each feature over the candidate pool."""

    means: Vector
    sds: Vector

    @property
    def zero_variance(self) -> tuple[str, ...]:
        return tuple(name for name, sd in zip(FEATURE_NAMES, self.sds) if sd == 0)

    def standardise(self, vector: Vector) -> Vector:
        z = [ZERO_FLOAT if sd == 0 else (x - mean) / sd for x, mean, sd in zip(vector, self.means, self.sds)]
        return (z[0], z[1])


def pool_stats(vectors: Sequence[Vector]) -> PoolStats:
    n = len(vectors)
    if n < 1:
        raise ValueError("the candidate pool must not be empty")
    means, sds = [], []
    for k in range(2):
        values = [v[k] for v in vectors]
        mean = math.fsum(values) / n
        means.append(mean)
        sds.append(math.sqrt(math.fsum((x - mean) ** 2 for x in values) / n))
    return PoolStats((means[0], means[1]), (sds[0], sds[1]))


def squared_distance(a: Vector, b: Vector) -> float:
    return math.fsum([(a[0] - b[0]) ** 2, (a[1] - b[1]) ** 2])


def rank_candidates(target: Vector, scored: Sequence[tuple[Candidate, Vector]]) -> list[tuple[Candidate, float]]:
    """Ascending by (squared distance, symbol, exchange, ISIN): ties go to the canonical instrument identifier, and the
    input order is ignored."""
    ranked = [(c, squared_distance(target, z)) for c, z in scored]
    ranked.sort(key=lambda row: (row[1], row[0].instrument.symbol, row[0].instrument.exchange.value, row[0].isin))
    return ranked
