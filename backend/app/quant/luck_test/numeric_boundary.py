"""The Decimal/float boundary (spec section 7). Money, returns and weights stay `Decimal`; this is the ONLY place a Decimal
becomes a float, and only for statistics (excess return, percentile, features, bootstrap).

`CALC` is a fixed 60-digit half-even context: sums and products of the inputs here are exact within it, divisions are
rounded once at 60 digits. `float(Decimal)` is correctly rounded, so a given Decimal always maps to the same float.
"""

from decimal import ROUND_CEILING, ROUND_HALF_EVEN, Context, Decimal, DivisionByZero, InvalidOperation, Overflow

CALC = Context(prec=60, rounding=ROUND_HALF_EVEN, traps=[InvalidOperation, DivisionByZero, Overflow])
ONE = Decimal(1)
TWO = Decimal(2)


def to_float(value: Decimal) -> float:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("value must be a finite Decimal")
    return float(value)


ZERO_FLOAT = to_float(Decimal(0))


def interval_indexes(replicates: int, level: Decimal) -> tuple[int, int]:
    """0-based sorted-replicate positions of the two-sided percentile interval: `ceil(B*a/2)-1` and `ceil(B*(1-a/2))-1`,
    a = 1 - level, in exact Decimal arithmetic. ValueError when they do not fall inside [0, B-1] in order."""
    alpha = CALC.subtract(ONE, level)
    low = int(CALC.divide(CALC.multiply(Decimal(replicates), alpha), TWO).to_integral_value(rounding=ROUND_CEILING)) - 1
    upper = CALC.multiply(Decimal(replicates), CALC.subtract(ONE, CALC.divide(alpha, TWO)))
    high = int(upper.to_integral_value(rounding=ROUND_CEILING)) - 1
    if not (0 <= low <= high <= replicates - 1):
        raise ValueError("bootstrap_replicates is too small for the confidence level")
    return low, high
