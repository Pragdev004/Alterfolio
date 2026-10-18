"""Feature 014 task 1: sector map, alternatives choice, provenance, loud failure on a missing column."""

import hashlib
from pathlib import Path

import pytest

from app.domain.enums import Exchange
from app.domain.instrument import Instrument
from app.quant.luck_test.types import Candidate
from app.services.reference_files import ReferenceDataError
from app.services.sector_map import build_alternatives, choose_alternatives, load_sector_map

HEADER = "Company Name,Industry,Symbol,Series,ISIN Code\n"
ISIN = {s: f"INE{n:03d}A01010" for n, s in enumerate("ABCDEFGHIJ", 1)}


def _write(tmp: Path, name: str, rows: list[tuple[str, str]]) -> Path:
    p = tmp / name
    p.write_text(HEADER + "".join(f"{s} Ltd,{ind},{s},EQ,{ISIN[s]}\n" for s, ind in rows), encoding="utf-8")
    return p


def _cand(sym: str) -> Candidate:
    return Candidate(Instrument(sym, Exchange.NSE), ISIN[sym])


@pytest.fixture
def smap(tmp_path):
    _write(tmp_path, "ind_nifty50list_2026-10-16.csv", [("A", "Fin"), ("B", "Fin"), ("C", "Fin"), ("D", "IT"), ("E", "IT")])
    _write(tmp_path, "ind_niftypsubanklist_2026-10-16.csv", [("A", "Fin"), ("F", "Fin"), ("G", "Fin")])
    _write(tmp_path, "ind_niftybanklist_2026-10-16.csv", [("A", "Fin"), ("B", "Fin"), ("C", "Fin"), ("H", "Fin")])
    return load_sector_map(tmp_path)


def test_grouping_industry_and_indices(smap):
    assert smap.entries[ISIN["A"]].indices == {"NIFTY 50", "NIFTY PSU BANK", "NIFTY BANK"}
    assert smap.entries[ISIN["D"]].industry == "IT"
    assert [e.symbol for e in smap.index_members("NIFTY PSU BANK")] == ["A", "F", "G"]


def test_prefers_the_most_specific_sectoral_index_with_three_reviewed(smap):
    reviewed = {ISIN[s]: _cand(s) for s in "BCHF"}
    static = (_cand("D"),)
    choice = choose_alternatives(ISIN["A"], smap, reviewed, static)
    assert choice.label == "alternatives: NIFTY BANK (3)" and not choice.fallback
    assert {c.instrument.symbol for c in choice.candidates} == {"B", "C", "H"}


def test_fewer_than_three_reviewed_falls_back_to_static_and_says_so(smap):
    reviewed = {ISIN[s]: _cand(s) for s in "BF"}
    static = (_cand("D"), _cand("E"))
    choice = choose_alternatives(ISIN["A"], smap, reviewed, static)
    assert choice.label == "alternatives: static universe (fallback)" and choice.fallback and choice.candidates == static


def test_industry_is_used_when_no_index_has_enough(smap):
    reviewed = {ISIN[s]: _cand(s) for s in "BCF"}  # NIFTY BANK has B,C only (2), PSU has F only; industry Fin has 3
    choice = choose_alternatives(ISIN["A"], smap, reviewed, ())
    assert choice.label == "alternatives: industry Fin (3)"


def test_unknown_isin_and_no_map_fall_back(smap):
    assert choose_alternatives("INE999Z01019", smap, {}, ()).fallback
    assert choose_alternatives(ISIN["A"], None, {}, ()).fallback
    assert build_alternatives(None, (), frozenset(), {ISIN["A"]}) == {}


def test_build_alternatives_uses_only_register_reviewed_listings(smap):
    listings = frozenset(Instrument(s, Exchange.NSE) for s in "BCH")
    out = build_alternatives(smap, (), listings, {ISIN["A"]})
    assert out[ISIN["A"]][1] == "alternatives: NIFTY BANK (3)"


def test_provenance_hash_date_and_label(tmp_path):
    p = _write(tmp_path, "ind_niftyitlist_2026-10-16.csv", [("D", "IT")])
    prov = load_sector_map(tmp_path).provenance[0]
    assert prov.sha256 == hashlib.sha256(p.read_bytes()).hexdigest()
    assert prov.download_date.isoformat() == "2026-10-16" and prov.file_name == p.name
    assert prov.source_label == "niftyindices NIFTY IT constituents"


def test_missing_column_fails_loudly_with_file_and_columns(tmp_path):
    (tmp_path / "ind_niftyitlist_2026-10-16.csv").write_text("Company Name,Symbol,ISIN Code\nX,X,INE001A01010\n", encoding="utf-8")
    with pytest.raises(ReferenceDataError) as exc:
        load_sector_map(tmp_path)
    msg = str(exc.value)
    assert "ind_niftyitlist_2026-10-16.csv" in msg and "Industry" in msg and "Company Name" in msg


def test_headers_are_case_insensitive_and_no_files_gives_none(tmp_path):
    assert load_sector_map(tmp_path) is None
    (tmp_path / "ind_niftyitlist_2026-10-16.csv").write_text(
        "company name,INDUSTRY,symbol,series,isin code\nD Ltd,IT,D,EQ,%s\n" % ISIN["D"], encoding="utf-8")
    assert load_sector_map(tmp_path).entries[ISIN["D"]].industry == "IT"


def test_file_name_without_a_date_is_rejected(tmp_path):
    from app.services.reference_files import read_reference_csv
    p = tmp_path / "x.csv"
    p.write_text(HEADER, encoding="utf-8")
    with pytest.raises(ReferenceDataError, match="download date"):
        read_reference_csv(p, ("Symbol",), "t")
