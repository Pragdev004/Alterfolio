"""Numeric policy constants (design: Numeric policy). Constants only, no behaviour."""
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    Inexact,
    InvalidOperation,
    Overflow,
)

SCALE = 6
PRECISION = 20  # stored as NUMERIC(PRECISION, SCALE)

# Accepted range for the exponent of a Decimal exactly as supplied (zero included): at most PRECISION fractional digits
# as written and at most the integer digits a column holds. Out-of-range input is rejected, never normalized.
MIN_INPUT_EXPONENT = -PRECISION
MAX_INPUT_EXPONENT = PRECISION - SCALE - 1
MONEY_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)

# Every single-trade amount (quantity x price + fees + taxes) and every running total in the holdings fold must stay
# strictly below this. Inputs have at most 6 decimals, so products carry 12; 15 integer + 12 decimal digits fit the
# 28-digit MONEY_CONTEXT, so additions are exact and quantizing results to SCALE can never overflow.
MAX_AMOUNT = Decimal(10) ** 15

# Wide, trapping context for validating inputs: 20-digit x 20-digit products are computed exactly, never rounded.
EXACT_CONTEXT = Context(
    prec=100,
    rounding=ROUND_HALF_EVEN,
    traps=[InvalidOperation, DivisionByZero, Overflow, Inexact],
)
