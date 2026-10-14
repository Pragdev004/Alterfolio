"""Input fingerprints: SHA-256 over canonical JSON of exactly the inputs a metric depends on (spec sections 5, 6).

Per-metric fingerprints differ because each covers only its relevant trades, series and parameters: charges are hashed only
for overtrading, sells and buys for disposition, buys only for chasing. Order of the input never matters (trades are sorted).
"""

import hashlib
import json
from collections.abc import Iterable
from decimal import Decimal

from app.quant.market_data.fingerprint import canonical_decimal, iso_utc

from .types import FORMULA_VERSION, SCHEMA_VERSION, BiasKind, LedgerTrade
from .validation import ValidatedBiasInputs

FINGERPRINT_VERSION = 1


def _hash(payload: object) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def _trade(trade: LedgerTrade, *, charges: bool) -> list[object]:
    row: list[object] = [
        trade.trade_id, trade.instrument.symbol, trade.instrument.exchange.value, trade.isin, trade.side.value,
        canonical_decimal(trade.quantity), canonical_decimal(trade.price), iso_utc(trade.trade_timestamp),
    ]
    if charges:
        c = trade.charges
        row.append([c.known, canonical_decimal(c.fees) if c.fees is not None else None,
                    canonical_decimal(c.taxes) if c.taxes is not None else None])
    return row


def _listings(inputs: ValidatedBiasInputs) -> list[list[str]]:
    return [[i.symbol, i.exchange.value, idx.series.fingerprint] for i, idx in inputs.indexes]


def _unit(value: Decimal) -> str:
    return canonical_decimal(value)


def metric_fingerprint(kind: BiasKind, inputs: ValidatedBiasInputs, trades: Iterable[LedgerTrade] | None = None) -> str:
    p = inputs.parameters
    if kind is BiasKind.DISPOSITION:
        rows, params = [_trade(t, charges=False) for t in inputs.trades], {}
    elif kind is BiasKind.CHASING:
        rows = [_trade(t, charges=False) for t in inputs.trades if t.side.value == "BUY"]
        params = {"lookback": p.chasing_lookback_sessions, "forward": p.forward_sessions,
                  "threshold": _unit(p.chase_threshold)}
    else:
        rows, params = [_trade(t, charges=True) for t in inputs.trades], {"short_term_sessions": p.short_term_sessions}
    return _hash({
        "v": FINGERPRINT_VERSION, "schema": SCHEMA_VERSION, "formula": FORMULA_VERSION, "bias": kind.value,
        "trades": rows, "listings": _listings(inputs), "params": params,
        "excluded": [[i.symbol, i.exchange.value] for i in inputs.excluded_listings],
        "missing": [[i.symbol, i.exchange.value] for i in inputs.missing_series],
    })


def profile_fingerprint(metric_fingerprints: Iterable[str], inputs: ValidatedBiasInputs) -> str:
    p = inputs.parameters
    return _hash({
        "v": FINGERPRINT_VERSION, "formula": FORMULA_VERSION, "rule_set": p.rule_set_version,
        "metrics": sorted(metric_fingerprints), "min_round_trips": p.min_round_trips,
        "shares": [_unit(p.churner_share), _unit(p.chaser_share), _unit(p.disposition_threshold)],
    })


def analysis_fingerprint(parts: Iterable[str], inputs: ValidatedBiasInputs) -> str:
    p = inputs.parameters
    return _hash({
        "v": FINGERPRINT_VERSION, "parts": sorted(parts), "window": [iso_utc(p.window_start), iso_utc(p.window_end)],
        "rule_set": p.rule_set_version,
    })
