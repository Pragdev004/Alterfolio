"""Deterministic keyword intent rules. No LLM, no clock."""

import re

INTENTS = ("bias_cost", "luck_test", "regime_split", "backtest")
DOCS_ONLY = "docs_only"
_RULES = {
    "bias_cost": re.compile(r"\b(bias(es)?|disposition|behaviou?r(al)?|cost of|holding too long)\b", re.IGNORECASE),
    "luck_test": re.compile(r"\b(luck|lucky|unlucky|random|chance|skill)\b", re.IGNORECASE),
    "regime_split": re.compile(r"\b(regimes?|bull|bear|market phase)\b", re.IGNORECASE),
    "backtest": re.compile(r"\b(back-?tests?|back-?tested|strateg(y|ies)|simulat\w*)\b", re.IGNORECASE),
}


def classify(question: str) -> tuple[str, ...]:
    """Matching quant intents in fixed order, or ("docs_only",) when none match."""
    found = tuple(intent for intent in INTENTS if _RULES[intent].search(question))
    return found or (DOCS_ONLY,)
