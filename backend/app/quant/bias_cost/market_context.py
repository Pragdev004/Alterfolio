"""Session lookups over ONE listing's `MarketSeries`. Sessions are bar indexes; no calendar, no gap filling.

Every close read names the last index it may see (`through`), so a calculation cannot touch a bar after the point it is
allowed to know (future-leakage guard, spec section 5).
"""

from bisect import bisect_left
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from app.quant.market_data.exchange_time import local_date
from app.quant.market_data.series import MarketSeries


@dataclass(frozen=True)
class SeriesIndex:
    series: MarketSeries
    dates: tuple[date, ...]

    @classmethod
    def build(cls, series: MarketSeries) -> "SeriesIndex":
        return cls(series=series, dates=tuple(bar.session_date for bar in series.bars))

    @property
    def session_count(self) -> int:
        return len(self.dates)

    def session_of(self, instant: datetime) -> date:
        """The exchange-local session date of a UTC instant, using THIS listing's offset."""
        return local_date(instant, self.series.exchange_utc_offset)

    def index_of(self, session: date) -> int | None:
        i = bisect_left(self.dates, session)
        return i if i < len(self.dates) and self.dates[i] == session else None

    def close(self, index: int, *, through: int) -> Decimal:
        """Close of bar `index`; refuses any bar after `through` (the caller's knowledge limit) or outside the series."""
        if index > through:
            raise ValueError(f"bar {index} is after the allowed limit {through}")
        if not (0 <= index < len(self.dates)):
            raise ValueError(f"bar {index} is outside the series")
        return self.series.bars[index].close
