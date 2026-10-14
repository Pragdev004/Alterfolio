"""Deterministic archetype rules (spec section 4). First matching rule wins; an unavailable metric is never treated as 0.

If a rule cannot be evaluated and no earlier rule matched, the profile is `Unavailable`: a later rule or the default could
only be reached by guessing what the missing metric would have said.
"""

from decimal import Decimal

from app.quant.market_data.fingerprint import canonical_decimal

from .calculations import ChasingFacts, DispositionFacts, OvertradingFacts
from .context import CALC_CONTEXT as C
from .errors import Unavailable
from .types import BehaviourProfile, BiasParameters

CHURNER = "CHURNER"
CHASER = "CHASER"
DISPOSITION_PRONE = "DISPOSITION_PRONE"
DISCIPLINED = "DISCIPLINED"


def classify_behaviour(
    over: OvertradingFacts, chase: ChasingFacts, disposition: DispositionFacts, parameters: BiasParameters,
    input_fingerprint: str,
) -> BehaviourProfile | Unavailable:
    if over.closed_round_trips < parameters.min_round_trips:
        return Unavailable("insufficient history")
    short_share = C.multiply(parameters.churner_share, Decimal(over.closed_round_trips))
    rules: list[tuple[str, str, bool | None]] = [
        (CHURNER, "churn", Decimal(over.short_term_round_trips) >= short_share),
        (CHASER, "chasing",
         None if chase.eligible_buys == 0
         else Decimal(chase.chase_buys) >= C.multiply(parameters.chaser_share, Decimal(chase.eligible_buys))),
        (DISPOSITION_PRONE, "disposition",
         None if disposition.pgr_minus_plr is None else disposition.pgr_minus_plr >= parameters.disposition_threshold),
    ]
    archetype = DISCIPLINED
    for rule_id, metric, matched in rules:
        if matched is None:
            return Unavailable(f"cannot classify: the {metric} metric is unavailable")
        if matched:
            archetype = rule_id
            break
    metrics = (
        ("chase_buys", str(chase.chase_buys)),
        ("closed_round_trips", str(over.closed_round_trips)),
        ("eligible_buys", str(chase.eligible_buys)),
        ("pgr_minus_plr", canonical_decimal(disposition.pgr_minus_plr) if disposition.pgr_minus_plr is not None
         else "unavailable"),
        ("short_term_round_trips", str(over.short_term_round_trips)),
    )
    return BehaviourProfile(archetype, parameters.rule_set_version, metrics, input_fingerprint)
