"""Loaders for the Feature 012 config files (static universe, corporate-action review register). Pure parsing, no network."""

import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from app.domain.enums import Exchange
from app.domain.instrument import Instrument
from app.quant.luck_test.types import Candidate


@dataclass(frozen=True)
class UniverseFile:
    candidates: tuple[Candidate, ...]
    static: bool
    note: str


@dataclass(frozen=True)
class ReviewedWindow:
    instrument: Instrument
    from_date: date
    to_date: date
    actions: tuple[tuple[date, str], ...]


def load_universe(path: Path) -> UniverseFile:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    static, note = data.get("static_universe", False), data.get("note", "")
    if static is not True or not isinstance(note, str) or not note.strip():
        raise ValueError("the universe file must set static_universe = true and a non-empty note (survivorship flag)")
    rows = data.get("instrument", [])
    if not rows:
        raise ValueError("the universe file lists no instruments")
    cands = tuple(Candidate(Instrument(r["symbol"], Exchange(r.get("exchange", "NSE"))), r["isin"]) for r in rows)
    return UniverseFile(cands, True, note)


def load_reviewed(path: Path) -> tuple[ReviewedWindow, ...]:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    out = []
    for r in data.get("reviewed", []):
        start, end = date.fromisoformat(str(r["from"])), date.fromisoformat(str(r["to"]))
        if end < start:
            raise ValueError(f"reviewed window for {r['symbol']} ends before it starts")
        actions = tuple((date.fromisoformat(str(a["date"])), str(a.get("kind", ""))) for a in r.get("actions", []))
        out.append(ReviewedWindow(Instrument(r["symbol"], Exchange(r.get("exchange", "NSE"))), start, end, actions))
    return tuple(out)


def resolve_corporate_actions(windows, listings, start: date, end: date, isin_of=None):
    """(reviewed, known) for `listings`, keyed by ISIN: a register entry covers every listing (NSE and BSE) of the ISIN
    of the entry's own listing (looked up in `isin_of`, a mapping Instrument -> ISIN). Without an ISIN the entry covers only
    its exact listing. Reviewed iff one window covers [start, end]; known iff a declared action of that window falls in it.
    Anything else is left out of `reviewed`, so the analyses answer Unavailable (or the service excludes it, spec 012)."""
    isin_of = isin_of or {}
    reviewed_isins, known_isins, reviewed_direct, known_direct = set(), set(), set(), set()
    for w in windows:
        if not (w.from_date <= start and w.to_date >= end):
            continue
        has_action = any(start <= d <= end for d, _ in w.actions)
        isin = isin_of.get(w.instrument)
        if isin:
            reviewed_isins.add(isin)
            if has_action:
                known_isins.add(isin)
        reviewed_direct.add(w.instrument)
        if has_action:
            known_direct.add(w.instrument)
    reviewed = {i for i in listings if i in reviewed_direct or isin_of.get(i) in reviewed_isins}
    known = {i for i in listings if i in known_direct or isin_of.get(i) in known_isins}
    return frozenset(reviewed), frozenset(known)


def load_aliases(path: Path) -> dict[str, str]:
    """LEDGER_SYMBOL -> DATA_SYMBOL, for market-data lookup only."""
    raw = tomllib.loads(Path(path).read_text(encoding="utf-8")).get("aliases", {})
    if not all(isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip() for k, v in raw.items()):
        raise ValueError("aliases must map non-blank symbols to non-blank symbols")
    return dict(raw)
