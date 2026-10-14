"""Per-trip statistics and the trip-level bootstrap (spec section 7).

The sampling unit is a trip: each replicate draws n trips with replacement and takes the mean excess return. Means are
`math.fsum` (exactly rounded, order-free). Replicates are sorted and the interval is read at the positions from
`numeric_boundary.interval_indexes`. Floats here are statistics only.
"""

import math
from collections.abc import Sequence
from decimal import Decimal

from .numeric_boundary import CALC, interval_indexes, to_float
from .rng import SplitMix64
from .types import IntervalPosition


def excess_and_percentile(
    actual: Decimal, mean_return: Decimal, beaten: int, ties: int, count: int
) -> tuple[float, float]:
    """`actual - mean` and `(beaten + ties / 2) / count`, each converted from an exact Decimal once."""
    excess = to_float(CALC.subtract(actual, mean_return))
    percentile = to_float(CALC.divide(Decimal(2 * beaten + ties), Decimal(2 * count)))
    return excess, percentile


def bootstrap_mean_interval(
    values: Sequence[float], rng: SplitMix64, replicates: int, level: Decimal
) -> tuple[float, float]:
    n = len(values)
    if n < 1:
        raise ValueError("at least one value is needed")
    low, high = interval_indexes(replicates, level)
    means = sorted(math.fsum(values[rng.randbelow(n)] for _ in range(n)) / n for _ in range(replicates))
    return means[low], means[high]


def position(lower: float, upper: float) -> IntervalPosition:
    if lower > 0:
        return IntervalPosition.ABOVE_ZERO
    if upper < 0:
        return IntervalPosition.BELOW_ZERO
    return IntervalPosition.CONTAINS_ZERO


def mean(values: Sequence[float]) -> float:
    return math.fsum(values) / len(values)
