"""Presentation boundary: the ONLY place a bias cost is rounded (owner decision 2026-10-14, spec section 3).

Internal values stay exact; callers that render INR amounts use `present_inr`, which returns a new value and never mutates
or replaces what a result stores.
"""

from decimal import ROUND_HALF_EVEN, Decimal

from app.domain.numeric import SCALE

from .context import CALC_CONTEXT
from .errors import BiasInputError

PRESENTATION_QUANTUM = Decimal(1).scaleb(-SCALE)  # 0.000001


def present_inr(value: Decimal) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal) or not value.is_finite():
        raise BiasInputError("present_inr needs a finite Decimal")
    return value.quantize(PRESENTATION_QUANTUM, rounding=ROUND_HALF_EVEN, context=CALC_CONTEXT)
