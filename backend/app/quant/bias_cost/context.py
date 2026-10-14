"""Decimal context for divisions only (means, ratios, average cost). Sums and products stay exact.

Division of exact Decimals is not always representable, so it is done at a fixed 60 significant digits, half-even, with no
Inexact trap. Results are exact internal values; nothing is quantized to 6 places until presentation (owner decision).
"""

from decimal import ROUND_HALF_EVEN, Context, DivisionByZero, InvalidOperation, Overflow

CALC_CONTEXT = Context(prec=60, rounding=ROUND_HALF_EVEN, traps=[InvalidOperation, DivisionByZero, Overflow])
