"""Point-in-time volatility regime of one listing (spec section 5).

For a trip opening on `d` with `B` bars strictly before it, `p = B-1` is the last of them. `v(q)` is the Feature 007 sample
volatility of the `window` returns of the `window + 1` closes ending at bar `q`; it is valid for `q >= window`. The calibration
pool is `v(q)` for `window <= q < p` of the SAME listing (so `B - window - 1` values; the trip's own `v(p)` is excluded).
Nothing at or after `d` is read: `v(q)` for `q <= p` uses closes up to `q` only, and the pool is built lazily up to `p`.
"""

import math
from bisect import bisect_left
from dataclasses import dataclass
from datetime import date

from app.quant.luck_test.features import ListingBars, PreTradeView, volatility

from .errors import RegimeInputError, Unavailable, UnavailableReason
from .types import Regime, RegimeParameters


@dataclass(frozen=True)
class Label:
    regime: Regime | None
    volatility: float | None
    low_threshold: float | None
    high_threshold: float | None
    calibration_count: int | None
    unavailable: Unavailable | None


def nearest_rank(sorted_values: list[float], percentile: int) -> float:
    """Value at 1-based rank `ceil(percentile * n / 100)`, in integer arithmetic; no interpolation."""
    n = len(sorted_values)
    rank = -((-percentile * n) // 100)
    if not 1 <= rank <= n:
        raise RegimeInputError("percentile rank is outside the pool")
    return sorted_values[rank - 1]


def _unavailable(reason: UnavailableReason, detail: str, current: float | None = None) -> Label:
    return Label(None, current, None, None, None, Unavailable(reason, detail))


class ListingClassifier:
    """Labels trips of one listing. `_vols[i]` is `v(window + i)`; it only ever grows up to the latest `p` asked for."""

    def __init__(self, bars: ListingBars, parameters: RegimeParameters) -> None:
        self._bars = bars
        self._parameters = parameters
        self._vols: list[float] = []

    def _extend_to(self, p: int) -> None:
        window = self._parameters.volatility_window
        for q in range(window + len(self._vols), p + 1):
            closes = self._bars.closes[q - window:q + 1]
            if any(c <= 0 for c in closes):
                raise RegimeInputError(f"{self._bars.instrument.symbol}: close must be positive")
            v = volatility(PreTradeView(closes, window + 1), window)
            if v is None or not math.isfinite(v):
                raise RegimeInputError(f"{self._bars.instrument.symbol}: volatility is not a finite number")
            self._vols.append(v)

    def label(self, d: date) -> Label:
        params = self._parameters
        window = params.volatility_window
        if self._bars.close_on(d) is None:
            return _unavailable(UnavailableReason.MISSING_BAR, f"no bar on {d.isoformat()}")
        before = bisect_left(self._bars.dates, d)
        if before < window + 1:
            return _unavailable(
                UnavailableReason.INSUFFICIENT_HISTORY, f"{before} closes before {d.isoformat()}, need {window + 1}")
        p = before - 1
        self._extend_to(p)
        current = self._vols[p - window]
        pool = self._vols[:p - window]
        if len(pool) < params.min_calibration:
            return _unavailable(
                UnavailableReason.INSUFFICIENT_CALIBRATION,
                f"{len(pool)} prior observations, need {params.min_calibration}", current)
        ordered = sorted(pool)
        low = nearest_rank(ordered, params.low_percentile)
        high = nearest_rank(ordered, params.high_percentile)
        if low == high:
            return Label(None, current, low, high, len(pool),
                         Unavailable(UnavailableReason.DEGENERATE_THRESHOLDS, "the two percentile thresholds are equal"))
        regime = Regime.LOW if current <= low else Regime.HIGH if current >= high else Regime.NORMAL
        return Label(regime, current, low, high, len(pool), None)
