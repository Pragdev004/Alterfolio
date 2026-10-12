"""Series fingerprint: SHA-256 over a canonical JSON of the provider values. Drift detection, not prevention (lineage P5)."""

import hashlib
import json
from collections.abc import Sequence
from datetime import datetime, timezone
from decimal import Decimal

from app.domain.enums import Currency
from app.domain.instrument import Instrument
from .bar import MarketBar

FINGERPRINT_VERSION = 1
FREQUENCY = "1d"


def canonical_decimal(value: Decimal) -> str:
    """Exact plain fixed-point text without trailing zeros, computed from the digits (never from a Decimal context)."""
    if not isinstance(value, Decimal):
        raise TypeError("value must be a Decimal")
    if not value.is_finite():
        raise ValueError("value must be finite")
    sign, digits, exponent = value.as_tuple()
    number = "".join(map(str, digits)).lstrip("0")
    if not number:
        return "0"
    if exponent >= 0:
        text = number + "0" * exponent
    else:
        scale = -exponent
        number = number.rjust(scale + 1, "0")
        integer, fraction = number[:-scale], number[-scale:].rstrip("0")
        text = integer + ("." + fraction if fraction else "")
    return ("-" if sign else "") + text


def iso_utc(instant: datetime) -> str:
    return instant.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def compute_fingerprint(
    *, source: str, instrument: Instrument, currency: Currency, bars: Sequence[MarketBar]
) -> str:
    """Hash of identity + provider values. Excludes retrieval time, counts and the requested range on purpose."""
    payload = {
        "fingerprint_version": FINGERPRINT_VERSION,
        "source": source,
        "instrument": {"symbol": instrument.symbol, "exchange": instrument.exchange.value},
        "currency": currency.value,
        "frequency": FREQUENCY,
        "bars": [
            [
                iso_utc(b.timestamp),
                b.session_date.isoformat(),
                canonical_decimal(b.open),
                canonical_decimal(b.high),
                canonical_decimal(b.low),
                canonical_decimal(b.close),
                canonical_decimal(b.adjusted_close),
                b.volume,
            ]
            for b in bars
        ],
    }
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
