"""Immutable backtest result, JSON form and fingerprint (Feature 005, step 6).

`as_of = min(series.cutoff)` of the inputs: it comes only from input provenance, so identical inputs give identical
`as_of` and fingerprint. There is no run timestamp and no clock. Every collection is a tuple; `to_dict()` builds fresh
containers on each call, so mutating its output cannot change the result. Money is canonical Decimal text.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from functools import cached_property

from app.domain.instrument import Instrument
from app.quant.market_data.fingerprint import canonical_decimal, iso_utc
from app.quant.market_data.series import MarketSeries
from .config import BacktestConfig, StrategyIdentity
from .execution import Fill, Order, Rejection

SCHEMA_VERSION = 1
ASSUMPTIONS = (
    ("costs", "NONE"),
    ("dividends", "EXCLUDED"),
    ("fill", "NEXT_SESSION_OPEN"),
    ("mark", "CLOSE"),
    ("share_units", "SPLIT_ADJUSTED"),
    ("shares", "WHOLE"),
    ("slippage", "NONE"),
    ("taxes", "NONE"),
)


@dataclass(frozen=True)
class EquityPoint:
    date: date
    cash: Decimal
    positions_value: Decimal
    equity: Decimal


@dataclass(frozen=True)
class SeriesRecord:
    """Provenance of one input series, copied verbatim (the restatement caveat lives in `knowledge_basis`)."""

    instrument: Instrument
    source: str
    fingerprint: str
    retrieved_at: datetime
    cutoff: datetime
    knowledge_basis: str
    bar_count: int

    @classmethod
    def of(cls, series: MarketSeries) -> "SeriesRecord":
        p = series.provenance
        return cls(series.instrument, p.source, series.fingerprint, p.retrieved_at, series.cutoff, p.knowledge_basis,
                   series.bar_count)


@dataclass(frozen=True)
class BacktestResult:
    config: BacktestConfig
    strategy: StrategyIdentity
    series: tuple[SeriesRecord, ...]
    calendar_dates: tuple[date, ...]
    dropped_dates: tuple[date, ...]
    equity_curve: tuple[EquityPoint, ...]
    orders: tuple[Order, ...]
    fills: tuple[Fill, ...]
    rejections: tuple[Rejection, ...]
    decisions_unavailable: tuple[tuple[date, str], ...]
    final_cash: Decimal
    final_positions: tuple[tuple[Instrument, Decimal], ...]
    schema_version: int = SCHEMA_VERSION

    @property
    def as_of(self) -> datetime:
        return min(record.cutoff for record in self.series)

    def _body(self) -> dict:
        c = self.config
        return {
            "schema_version": self.schema_version,
            "as_of": iso_utc(self.as_of),
            "provenance": {
                "series": [
                    {"instrument": _inst(r.instrument), "source": r.source, "fingerprint": r.fingerprint,
                     "retrieved_at": iso_utc(r.retrieved_at), "cutoff": iso_utc(r.cutoff),
                     "knowledge_basis": r.knowledge_basis, "bar_count": r.bar_count}
                    for r in self.series
                ],
                "assumptions": dict(ASSUMPTIONS),
            },
            "inputs": {
                "config": {"start_date": c.start_date.isoformat(), "end_date": c.end_date.isoformat(),
                           "initial_cash": canonical_decimal(c.initial_cash), "currency": c.currency.value,
                           "price_basis": c.price_basis, "trial_count": c.trial_count},
                "strategy": {"strategy_id": self.strategy.strategy_id, "version": self.strategy.version,
                             "parameters": [[k, v] for k, v in self.strategy.parameters]},
            },
            "values": {
                "calendar": {
                    "first_date": self.calendar_dates[0].isoformat(), "last_date": self.calendar_dates[-1].isoformat(),
                    "session_count": len(self.calendar_dates),
                    "dropped_dates": [d.isoformat() for d in self.dropped_dates],
                },
                "equity_curve": [
                    {"date": p.date.isoformat(), "cash": canonical_decimal(p.cash),
                     "positions_value": canonical_decimal(p.positions_value), "equity": canonical_decimal(p.equity)}
                    for p in self.equity_curve
                ],
                "orders": [
                    {"order_id": o.order_id, "decided_on": o.decided_on.isoformat(), "instrument": _inst(o.instrument),
                     "side": o.side.value, "quantity": canonical_decimal(o.quantity)}
                    for o in self.orders
                ],
                "fills": [
                    {"order_id": f.order_id, "date": f.date.isoformat(), "instrument": _inst(f.instrument),
                     "side": f.side.value, "quantity": canonical_decimal(f.quantity),
                     "price": canonical_decimal(f.price), "notional": canonical_decimal(f.notional)}
                    for f in self.fills
                ],
                "rejections": [
                    {"order_id": r.order_id, "date": r.date.isoformat(), "reason": r.reason} for r in self.rejections
                ],
                "decisions_unavailable": [{"date": d.isoformat(), "reason": why} for d, why in self.decisions_unavailable],
                "final_cash": canonical_decimal(self.final_cash),
                "final_positions": [
                    {"instrument": _inst(i), "quantity": canonical_decimal(q)} for i, q in self.final_positions
                ],
            },
        }

    @cached_property
    def fingerprint(self) -> str:
        """SHA-256 of the canonical sorted JSON of everything in `to_dict()` except the fingerprint itself."""
        text = json.dumps(self._body(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        body = self._body()
        body["provenance"]["result_fingerprint"] = self.fingerprint
        return body


def _inst(instrument: Instrument) -> dict:
    return {"symbol": instrument.symbol, "exchange": instrument.exchange.value}
