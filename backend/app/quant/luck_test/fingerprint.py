"""Input fingerprint: SHA-256 over canonical JSON of exactly the inputs a run depends on (spec section 9).

Order-independent: trips, universe, membership and the corporate-action set are sorted before hashing. Only the series of
listings the run can read (traded listings and universe listings) contribute, each by its own fingerprint.
"""

import hashlib
import json
from collections.abc import Iterable

from app.domain.instrument import Instrument
from app.quant.market_data.fingerprint import canonical_decimal, iso_utc

from .rng import RNG_VERSION
from .types import (
    ACTUAL_RETURN_BASIS, ALTERNATIVE_RETURN_BASIS, FORMULA_VERSION, SCHEMA_VERSION, Candidate, LuckParameters, Membership,
    TripInput,
)

FINGERPRINT_VERSION = 1


def _listing(i: Instrument) -> list[str]:
    return [i.symbol, i.exchange.value]


def input_fingerprint(
    trips: Iterable[TripInput],
    series_fingerprints: Iterable[tuple[str, str, str]],
    universe: Iterable[Candidate],
    nifty50: Iterable[Membership],
    corporate_action_listings: Iterable[Instrument],
    parameters: LuckParameters,
    corporate_action_reviewed: Iterable[Instrument] | None = None,
) -> str:
    p = parameters
    payload = {
        "v": FINGERPRINT_VERSION, "schema": SCHEMA_VERSION, "formula": FORMULA_VERSION, "rng": RNG_VERSION,
        "trips": sorted(
            [t.trip_id, *_listing(t.instrument), t.isin or "", t.open_session.isoformat(), t.close_session.isoformat(),
             canonical_decimal(t.cost_inr), canonical_decimal(t.proceeds_inr)]
            for t in trips
        ),
        "series": sorted(list(row) for row in series_fingerprints),
        "universe": sorted([c.isin, *_listing(c.instrument)] for c in universe),
        "nifty50": sorted([m.isin, m.from_date.isoformat(), "" if m.to_date is None else m.to_date.isoformat()]
                          for m in nifty50),
        "corporate_actions": sorted(_listing(i) for i in corporate_action_listings),
        "corporate_action_reviewed": None if corporate_action_reviewed is None
        else sorted(_listing(i) for i in corporate_action_reviewed),
        "bases": [ACTUAL_RETURN_BASIS, ALTERNATIVE_RETURN_BASIS],
        "params": {
            "seed": p.seed, "as_of": iso_utc(p.as_of), "portfolio_count": p.portfolio_count,
            "max_alternatives": p.max_alternatives, "min_alternatives": p.min_alternatives,
            "nifty_portfolio_size": p.nifty_portfolio_size, "bootstrap_replicates": p.bootstrap_replicates,
            "confidence_level": canonical_decimal(p.confidence_level), "min_trips": p.min_trips,
            "momentum_lookback": p.momentum_lookback, "volatility_lookback": p.volatility_lookback,
        },
    }
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("ascii")).hexdigest()
