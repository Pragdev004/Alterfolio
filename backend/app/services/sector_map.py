"""Feature 014 task 1: ISIN -> industry and index memberships from niftyindices constituent CSVs, and the per-instrument
luck-test alternatives chosen from it. Pure file parsing and selection; the quant contracts are untouched.

Alternatives for a traded ISIN: reviewed universe members of the SAME sectoral index (preferred, smallest index first), else
of the same industry; fewer than `MIN_ALTERNATIVES` reviewed -> the static universe, labelled as a fallback.
"""

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from app.domain.enums import Exchange
from app.domain.instrument import Instrument
from app.quant.luck_test.types import Candidate
from app.services.reference_files import FileProvenance, ReferenceDataError, read_reference_csv

MIN_ALTERNATIVES = 3
BROAD_INDICES = frozenset({"NIFTY 50"})  # not sectoral: never a peer group
_REQUIRED = ("Company Name", "Industry", "Symbol", "Series", "ISIN Code")
_FILE = re.compile(r"^ind_(.+)list_\d{4}-\d{2}-\d{2}\.csv$", re.IGNORECASE)
_INDEX_NAMES = {"nifty50": "NIFTY 50", "niftybank": "NIFTY BANK", "niftypsubank": "NIFTY PSU BANK", "niftyit": "NIFTY IT",
                "niftyenergy": "NIFTY ENERGY", "niftyfmcg": "NIFTY FMCG"}


def index_label(file_name: str) -> str:
    m = _FILE.match(file_name)
    if not m:
        raise ReferenceDataError(f"{file_name}: not an ind_<index>list_<date>.csv file")
    key = m.group(1).lower()
    return _INDEX_NAMES.get(key, key.upper())


@dataclass(frozen=True)
class SectorEntry:
    isin: str
    symbol: str
    industry: str
    indices: frozenset[str]


@dataclass(frozen=True)
class SectorMap:
    entries: dict[str, SectorEntry]  # ISIN -> entry
    provenance: tuple[FileProvenance, ...]

    def index_members(self, index: str) -> list[SectorEntry]:
        return sorted((e for e in self.entries.values() if index in e.indices), key=lambda e: e.isin)

    def industry_members(self, industry: str) -> list[SectorEntry]:
        return sorted((e for e in self.entries.values() if e.industry == industry), key=lambda e: e.isin)


def load_sector_map(directory: Path) -> SectorMap | None:
    """None when no ind_*list_*.csv file is present (the caller skips and says so)."""
    files = sorted(p for p in Path(directory).glob("ind_*list_*.csv") if _FILE.match(p.name))
    if not files:
        return None
    industry: dict[str, str] = {}
    symbol: dict[str, str] = {}
    member: dict[str, set[str]] = defaultdict(set)
    provs = []
    for path in files:
        label = index_label(path.name)
        rows, prov = read_reference_csv(path, _REQUIRED, f"niftyindices {label} constituents")
        provs.append(prov)
        for r in rows:
            isin = r["ISIN Code"]
            industry.setdefault(isin, r["Industry"])
            symbol.setdefault(isin, r["Symbol"])
            member[isin].add(label)
    entries = {i: SectorEntry(i, symbol[i], industry[i], frozenset(member[i])) for i in industry}
    return SectorMap(entries, tuple(provs))


@dataclass(frozen=True)
class AlternativesChoice:
    candidates: tuple[Candidate, ...]
    label: str
    fallback: bool


def choose_alternatives(isin: str, sector_map: SectorMap | None, reviewed: dict[str, Candidate],
                        static: tuple[Candidate, ...]) -> AlternativesChoice:
    """`reviewed`: ISIN -> candidate for universe listings that are reviewed and available. The traded ISIN itself is never an
    alternative to itself."""
    entry = None if sector_map is None else sector_map.entries.get(isin)
    if entry is not None:
        peers = [(idx, sector_map.index_members(idx)) for idx in sorted(entry.indices - BROAD_INDICES)]
        peers.sort(key=lambda p: (len(p[1]), p[0]))  # most specific index first
        groups = [(f"{idx}", m) for idx, m in peers] + [(f"industry {entry.industry}", sector_map.industry_members(entry.industry))]
        for name, members in groups:
            picked = tuple(reviewed[m.isin] for m in members if m.isin in reviewed and m.isin != isin)
            if len(picked) >= MIN_ALTERNATIVES:
                return AlternativesChoice(picked, f"alternatives: {name} ({len(picked)})", False)
    return AlternativesChoice(static, "alternatives: static universe (fallback)", True)


def candidate_for(entry: SectorEntry) -> Candidate:
    return Candidate(Instrument(entry.symbol, Exchange.NSE), entry.isin)


def build_alternatives(sector_map: SectorMap | None, universe: tuple[Candidate, ...], reviewed_listings: frozenset[Instrument],
                       traded_isins: set[str]) -> dict[str, tuple[tuple[Candidate, ...], str]]:
    """ISIN -> (alternatives, label) for each traded ISIN. Reviewed candidates are universe members, plus sector-file members,
    whose NSE listing the corporate-action register covers; the static universe is the fallback."""
    if sector_map is None:
        return {}
    reviewed = {c.isin: c for c in universe if c.instrument in reviewed_listings}
    for e in sector_map.entries.values():
        cand = candidate_for(e)
        if e.isin not in reviewed and cand.instrument in reviewed_listings:
            reviewed[e.isin] = cand
    out = {}
    for isin in sorted(traded_isins):
        choice = choose_alternatives(isin, sector_map, reviewed, universe)
        out[isin] = (choice.candidates, choice.label)
    return out
