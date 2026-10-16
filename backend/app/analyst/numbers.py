"""Deterministic number check: every numeric token in a draft must equal a claim, every claim must match its source."""

import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation

from app.analyst.types import UNAVAILABLE, Draft, Fact, Passage

_TOKEN = re.compile(r"[+-]?(?:\d[\d,]*(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?%?")
_SCALE = re.compile(r"\d\s*(?:lakhs?|crores?|thousand|million|billion|trillion|mn|bn|bps|k|m|x)\b", re.IGNORECASE)
_WORDS = re.compile(
    r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|"
    r"seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|"
    r"billion|half|third|quarter|double|triple|twice|dozen)\b", re.IGNORECASE)
_MAX_EXPONENT = 40


def numeric_tokens(text: str) -> list[str]:
    return _TOKEN.findall(unicodedata.normalize("NFKC", text))


def canonical(token: str) -> str | None:
    """Plain decimal text of a numeric token (commas and % sign dropped, exponent expanded), or None if not a number."""
    raw = unicodedata.normalize("NFKC", token).strip().replace(",", "")
    if raw.endswith("%"):
        raw = raw[:-1]
    try:
        d = Decimal(raw)
    except InvalidOperation:
        return None
    if not d.is_finite() or abs(d.adjusted()) > _MAX_EXPONENT:
        return None
    if d == 0:
        return "0"
    return format(d.normalize(), "f")


def _strip(text: str, names: list[str]) -> str:
    for name in sorted(set(names), key=len, reverse=True):
        text = text.replace(name, " ")
    return text


def check(draft: Draft, facts: list[Fact] | tuple[Fact, ...], passages: list[Passage] | tuple[Passage, ...],
          as_of: date) -> list[str]:
    """Errors found in a draft; an empty list means every number is traceable. Order is deterministic."""
    by_name = {f.name: f for f in facts}
    by_chunk = {p.chunk_id: p for p in passages}
    errors: list[str] = []
    allowed: set[str] = set()
    for claim in draft.claims:
        value = canonical(claim.value)
        if value is None:
            errors.append(f"claim value {claim.value!r} is not a number")
        elif claim.source in by_name:
            fact = by_name[claim.source]
            if fact.value == UNAVAILABLE:
                errors.append(f"claim {claim.value!r} cites {claim.source}, which is Unavailable")
            elif value != canonical(fact.value):
                errors.append(f"claim {claim.value!r} does not equal {claim.source} = {fact.value}")
            else:
                allowed.add(value)
        elif claim.source in by_chunk:
            if value in {canonical(t) for t in numeric_tokens(by_chunk[claim.source].text)}:
                allowed.add(value)
            else:
                errors.append(f"claim {claim.value!r} does not appear in cited passage {claim.source}")
        else:
            errors.append(f"claim {claim.value!r} cites unknown source {claim.source!r}")
    text = unicodedata.normalize("NFKC", draft.text)
    text = _strip(text, [as_of.isoformat(), *by_name, *by_chunk])
    if _SCALE.search(text):
        errors.append("scaled numbers (lakh, crore, k, bn, bps, ...) are not allowed; state the exact value")
    if _WORDS.search(text):
        errors.append("numbers written as words are not allowed; state the exact value")
    for token in numeric_tokens(text):
        value = canonical(token)
        if value is None or value not in allowed:
            errors.append(f"number {token!r} in the text is not backed by a verified claim")
    return errors
