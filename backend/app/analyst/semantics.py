"""Feature 015 semantic guard (pure, deterministic). Numbers can be exact and the sentence still wrong; this catches the
cheap, rule-shaped cases: a value compared with itself, comparison or sign words the values contradict, and an answer
that asserts a claim and its negation. A hit is a repair error like any number error; it is not a full meaning check.
"""

import re
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation

from app.analyst.harness import FACT_PLACEHOLDER
from app.analyst.numbers import canonical
from app.analyst.types import UNAVAILABLE, Fact

_SENTENCE = re.compile(r"(?<=[.!?;])\s+|\n+")
_NUMBER = re.compile(r"[+-]?₹?\d[\d,]*(?:\.\d+)?%?")
_SELF = re.compile(r"\b(?:not|than|versus|vs|compared|unlike|instead|differs?|different)\b", re.IGNORECASE)
_NEG = re.compile(r"\b(?:not|no|never|isn't|wasn't|aren't|weren't|doesn't|didn't|cannot|can't|neither|nor|without|"
                  r"lacks?)\b", re.IGNORECASE)
_UP = re.compile(r"\b(?:higher|greater|larger|bigger|more|above|exceed(?:s|ed)?|outperform(?:s|ed)?|beat|better)\b",
                 re.IGNORECASE)
_DOWN = re.compile(r"\b(?:lower|less|smaller|fewer|below|under|underperform(?:s|ed)?|worse|trail(?:s|ed)?)\b",
                   re.IGNORECASE)
_SIGN_AFTER = re.compile(r"[\s,]*(?:which\s+)?(?:is|was)\s+(not\s+)?(positive|negative)\b", re.IGNORECASE)
_SIGN_BEFORE = re.compile(r"\b(positive|negative)\s+(?:[a-z-]+\s+){0,3}$", re.IGNORECASE)
_CONCEPTS = (  # (concept, polarity, pattern); a negation in the 4 words before a match flips its polarity
    ("statistical significance", 1, r"\b(?:statistically\s+)?significant\b"),
    ("statistical significance", -1, r"\binsignificant\b"),
    ("skill", 1, r"\bskill\s+rather\s+than\s+(?:luck|chance)\b"),
    ("skill", -1, r"\b(?:luck|chance)\s+rather\s+than\s+skill\b"),
    ("skill", 1, r"\b(?:shows?|suggests?|indicates?|reflects?|evidence\s+of|due\s+to|points?\s+to)\s+"
                 r"(?:genuine\s+|real\s+)?skill\b"),
    ("skill", -1, r"\b(?:shows?|suggests?|indicates?|reflects?|due\s+to|consistent\s+with|points?\s+to)\s+"
                  r"(?:pure\s+|random\s+)?(?:luck|chance)\b"),
    ("skill", -1, r"\bindistinguishable\s+from\s+(?:random\s+)?chance\b"),
    ("skill", 1, r"\bbetter\s+than\s+(?:random\s+)?chance\b"),
)
_CONCEPT_RES = tuple((c, p, re.compile(rx, re.IGNORECASE)) for c, p, rx in _CONCEPTS)
_NEGATORS = {"not", "no", "never"}


def _sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE.split(text) if s.strip()]


def _number(fact: Fact | None) -> Decimal | None:
    if fact is None or fact.value == UNAVAILABLE:
        return None
    try:
        return Decimal(fact.value)
    except InvalidOperation:
        return None


def _self_comparisons(raw: str, filled: str) -> list[str]:
    errors = []
    for sentence in _sentences(raw):
        names = [m.group(1) for m in FACT_PLACEHOLDER.finditer(sentence)]
        errors += [f"{{fact:{n}}} is compared with itself in one sentence; state it once"
                   for n in dict.fromkeys(n for n in names if names.count(n) > 1)]
    if errors:
        return errors
    for sentence in _sentences(filled):
        seen: dict[str, int] = {}
        for m in _NUMBER.finditer(sentence):
            value = canonical(m.group(0))
            if value in seen and _SELF.search(sentence[seen[value]:m.start()]):
                errors.append(f"the same value {m.group(0)} is compared with itself; state it once")
            seen.setdefault(value, m.end())
    return errors


def _value_contradictions(raw: str, facts: Sequence[Fact]) -> list[str]:
    by_name = {f.name: f for f in facts}
    errors = []
    for sentence in _sentences(raw):
        marks = list(FACT_PLACEHOLDER.finditer(sentence))
        for a, b in zip(marks, marks[1:]):
            between = sentence[a.end():b.start()]
            up, down = _UP.search(between), _DOWN.search(between)
            fa, fb = by_name.get(a.group(1)), by_name.get(b.group(1))
            va, vb = _number(fa), _number(fb)
            if va is None or vb is None or fa.unit != fb.unit or bool(up) == bool(down) or _NEG.search(between):
                continue
            if (up and not va > vb) or (down and not va < vb):
                word = (up or down).group(0)
                errors.append(f"'{word}' contradicts the values of {{fact:{a.group(1)}}} and {{fact:{b.group(1)}}}")
        for m in marks:
            value = _number(by_name.get(m.group(1)))
            if value is None:
                continue
            after = _SIGN_AFTER.match(sentence[m.end():])
            before = _SIGN_BEFORE.search(sentence[:m.start()])
            for word, negated in ([(after.group(2), bool(after.group(1)))] if after else []) + \
                                 ([(before.group(1), False)] if before else []):
                claims_positive = (word.lower() == "positive") != negated
                if value == 0 or (value > 0) != claims_positive:
                    errors.append(f"'{word}' contradicts the value of {{fact:{m.group(1)}}}")
    return errors


def _polarities(text: str) -> dict[str, set[int]]:
    found: dict[str, set[int]] = {}
    for sentence in _sentences(text):
        for concept, polarity, pattern in _CONCEPT_RES:
            for m in pattern.finditer(sentence):
                before = sentence[:m.start()].split()[-4:]
                flipped = any(_NEG.fullmatch(w.strip(",;:")) for w in before)
                found.setdefault(concept, set()).add(-polarity if flipped else polarity)
    return found


def _negation_contradictions(text: str) -> list[str]:
    errors = []
    found = _polarities(text)
    for concept, polarities in found.items():
        if polarities == {1, -1}:
            errors.append(f"the answer both asserts and denies {concept}; keep the one the facts support")
    if 1 in found.get("skill", set()) and -1 in found.get("statistical significance", set()):
        errors.append("claiming skill contradicts saying the result is not statistically significant")
    variants: dict[tuple[str, ...], set[bool]] = {}
    for sentence in _sentences(text):
        words = re.findall(r"[a-z']+", sentence.lower().replace("n't", " not"))
        core = tuple(w for w in words if w not in _NEGATORS)
        if len(core) >= 3:
            variants.setdefault(core, set()).add(len(core) != len(words))
    if any(v == {True, False} for v in variants.values()):
        errors.append("the answer contradicts itself (a statement and its negation); keep the one the facts support")
    return errors


def semantic_errors(raw: str, filled: str, facts: Sequence[Fact]) -> list[str]:
    """Errors in a draft: `raw` is the model text with placeholders, `filled` the text after substitution."""
    errors = _self_comparisons(raw, filled) + _value_contradictions(raw, facts) + _negation_contradictions(filled)
    return list(dict.fromkeys(errors))
