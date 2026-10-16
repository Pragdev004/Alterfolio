"""Feature 009 step 1: retrieval domain types and limits (spec docs/specs/009-rag-date-cutoff.md sections 3, 4, 7, 8)."""
import math
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from app.domain import limits
from app.domain.retrieval import (
    SCHEMA_VERSION,
    ChunkConflictError,
    ChunkInput,
    CutoffAudit,
    CutoffViolationError,
    EmbeddingIncompatibleError,
    RetrievalError,
    RetrievalInputError,
    RetrievalProvenance,
    RetrievedChunk,
    SearchResult,
    Unavailable,
    UnavailableReason,
    is_eligible,
    to_utc,
    validate_k,
    validate_text,
)

UTC = timezone.utc
IST = timezone(timedelta(hours=5, minutes=30))
T0 = datetime(2026, 1, 15, 10, 30, 0, 123456, tzinfo=UTC)
HEX_A = "a" * 64
HEX_B = "0123456789abcdef" * 4


def chunk(**overrides) -> ChunkInput:
    fields = {"source_id": "doc-1", "chunk_index": 0, "text": "Quarterly results were published.", "published_at": T0}
    fields.update(overrides)
    return ChunkInput(**fields)


def retrieved(rank: int = 1, score: float = 0.9, published_at: datetime = T0, **overrides) -> RetrievedChunk:
    fields = {"chunk_id": uuid4(), "source_id": "doc-1", "chunk_index": 0, "text": "text",
              "published_at": published_at, "score": score, "rank": rank}
    fields.update(overrides)
    return RetrievedChunk(**fields)


def provenance(cutoff: datetime = T0, k: int = 5, **overrides) -> RetrievalProvenance:
    fields = {"embedding_config_id": HEX_A, "embedding_dimension": 768, "cutoff": cutoff, "k": k, "input_fingerprint": HEX_B}
    fields.update(overrides)
    return RetrievalProvenance(**fields)


# ---- limits ------------------------------------------------------------------------------------------------------------


def test_retrieval_limits_match_the_spec():
    assert limits.MAX_CHUNK_TEXT_LENGTH == 4000  # owner-confirmed, Python characters, before the role prefix
    assert (limits.MIN_SEARCH_K, limits.MAX_SEARCH_K) == (1, 50)
    assert limits.MAX_CHUNK_INDEX == 2**31 - 1  # fits a PostgreSQL INTEGER column
    assert limits.MAX_SOURCE_ID_LENGTH == 256
    assert not hasattr(limits, "MIN_PUBLISHED_AT") and not hasattr(limits, "MAX_PUBLISHED_AT")  # no window (spec section 3)


# ---- text: chunk text and query text share one rule ---------------------------------------------------------------------


def test_text_at_the_cap_is_accepted_and_one_over_is_rejected():
    assert validate_text("query_text", "x" * limits.MAX_CHUNK_TEXT_LENGTH) == "x" * 4000
    assert chunk(text="x" * 4000).text == "x" * 4000
    with pytest.raises(RetrievalInputError, match="longer than 4000"):
        validate_text("query_text", "x" * 4001)
    with pytest.raises(RetrievalInputError, match="longer than 4000"):
        chunk(text="x" * 4001)


def test_the_cap_counts_python_characters_not_bytes():
    rupees = "₹" * 4000  # 12,000 UTF-8 bytes, 4,000 characters
    assert len(rupees.encode("utf-8")) == 12000
    assert chunk(text=rupees).text == rupees
    assert validate_text("query_text", rupees) == rupees


@pytest.mark.parametrize("bad", ["", " ", "\n\t  ", "a\x00b", None, 42, b"bytes", "\ud800"])
def test_text_must_be_non_blank_text_without_nul_or_unencodable_characters(bad):
    with pytest.raises(RetrievalInputError):
        validate_text("query_text", bad)
    with pytest.raises(RetrievalInputError):
        chunk(text=bad)


def test_text_is_kept_verbatim_never_stripped_or_normalised():
    raw = "  Line one.\nLine two.  "
    assert chunk(text=raw).text == raw
    assert validate_text("query_text", raw) == raw


# ---- ChunkInput ----------------------------------------------------------------------------------------------------------


def test_chunk_input_accepts_a_valid_chunk_and_is_frozen():
    c = chunk()
    assert (c.source_id, c.chunk_index, c.published_at) == ("doc-1", 0, T0)
    with pytest.raises(AttributeError):
        c.text = "other"  # type: ignore[misc]


@pytest.mark.parametrize("bad", ["", "   ", "a\x00", "s" * 257, None, 7])
def test_chunk_input_rejects_a_bad_source_id(bad):
    with pytest.raises(RetrievalInputError, match="source_id"):
        chunk(source_id=bad)


def test_source_id_at_its_limit_is_accepted():
    assert chunk(source_id="s" * 256).source_id == "s" * 256


@pytest.mark.parametrize("bad", [-1, 2**31, True, 1.0, "0", None])
def test_chunk_input_rejects_a_bad_chunk_index(bad):
    with pytest.raises(RetrievalInputError, match="chunk_index"):
        chunk(chunk_index=bad)


def test_chunk_index_bounds_are_inclusive():
    assert chunk(chunk_index=0).chunk_index == 0
    assert chunk(chunk_index=2**31 - 1).chunk_index == 2**31 - 1


@pytest.mark.parametrize("bad", [datetime(2026, 1, 15, 10, 30), None, "2026-01-15T10:30:00+00:00", 1768473000])
def test_published_at_must_be_an_aware_datetime(bad):
    with pytest.raises(RetrievalInputError, match="published_at"):
        chunk(published_at=bad)


def test_published_at_is_normalised_to_utc_keeping_the_instant_and_microseconds():
    local = datetime(2026, 1, 15, 16, 0, 0, 123456, tzinfo=IST)
    c = chunk(published_at=local)
    assert c.published_at == datetime(2026, 1, 15, 10, 30, 0, 123456, tzinfo=UTC)
    assert c.published_at.tzinfo == UTC and c.published_at.utcoffset() == timedelta(0)


def test_every_representable_utc_instant_is_accepted_including_the_edges():
    """No published_at window (spec section 3). Read-back of the edges is verified only on live PostgreSQL (plan step 6)."""
    first = datetime(1, 1, 1, 0, 0, 0, 0, tzinfo=UTC)
    last = datetime(9999, 12, 31, 23, 59, 59, 999999, tzinfo=UTC)
    assert chunk(published_at=first).published_at == first
    assert chunk(published_at=last).published_at == last
    assert chunk(published_at=datetime(1, 1, 1, 5, 30, tzinfo=IST)).published_at == first  # same instant, other offset


@pytest.mark.parametrize("unrepresentable", [
    datetime(1, 1, 1, 0, 0, tzinfo=IST),  # UTC instant falls before year 1
    datetime(9999, 12, 31, 23, 0, tzinfo=timezone(timedelta(hours=-5))),  # UTC instant falls after year 9999
])
def test_an_offset_that_overflows_utc_is_an_input_error_not_an_overflow(unrepresentable):
    with pytest.raises(RetrievalInputError, match="published_at"):
        chunk(published_at=unrepresentable)


# ---- cutoff semantics ------------------------------------------------------------------------------------------------------


def test_eligibility_is_inclusive_at_the_cutoff_and_excludes_one_microsecond_later():
    assert is_eligible(T0, T0)
    assert is_eligible(T0 - timedelta(microseconds=1), T0)
    assert not is_eligible(T0 + timedelta(microseconds=1), T0)


def test_eligibility_compares_instants_across_timezones():
    same_instant_ist = T0.astimezone(IST)
    assert is_eligible(same_instant_ist, T0) and is_eligible(T0, same_instant_ist)
    assert not is_eligible(T0 + timedelta(microseconds=1), same_instant_ist)


@pytest.mark.parametrize("args", [(datetime(2026, 1, 1), T0), (T0, datetime(2026, 1, 1)), (None, T0), (T0, None)])
def test_eligibility_rejects_naive_or_missing_dates(args):
    with pytest.raises(RetrievalInputError):
        is_eligible(*args)


def test_to_utc_rejects_naive_values_and_keeps_microseconds():
    with pytest.raises(RetrievalInputError, match="cutoff"):
        to_utc("cutoff", datetime(2026, 1, 1))
    assert to_utc("cutoff", T0.astimezone(IST)) == T0
    assert to_utc("cutoff", T0.astimezone(IST)).tzinfo == UTC


# ---- k -------------------------------------------------------------------------------------------------------------------


def test_k_bounds():
    assert validate_k(1) == 1 and validate_k(50) == 50
    for bad in (0, 51, -1, True, 5.0, "5", None):
        with pytest.raises(RetrievalInputError, match="k"):
            validate_k(bad)


# ---- errors and Unavailable ----------------------------------------------------------------------------------------------


def test_error_hierarchy():
    assert issubclass(RetrievalInputError, ValueError)
    for cls in (RetrievalInputError, ChunkConflictError, EmbeddingIncompatibleError, CutoffViolationError):
        assert issubclass(cls, RetrievalError)
    assert not issubclass(CutoffViolationError, RetrievalInputError)  # a broken filter is never an input defect


def test_unavailable_reasons_are_exactly_the_spec_list():
    assert {r.value for r in UnavailableReason} == {
        "EMBEDDING_PROVIDER_UNAVAILABLE", "EMBEDDING_MODEL_MISSING", "DIMENSION_UNRESOLVED", "DIMENSION_MISMATCH",
        "NON_FINITE_EMBEDDING", "EMBEDDING_INCOMPATIBLE", "VECTOR_EXTENSION_MISSING", "EMPTY_INDEX", "NO_ELIGIBLE_CHUNKS",
    }


def test_unavailable_states_a_reason_and_validates_detail():
    u = Unavailable(UnavailableReason.EMPTY_INDEX, "no chunks for this user")
    assert u.to_dict() == {"reason": "EMPTY_INDEX", "detail": "no chunks for this user"}
    with pytest.raises(RetrievalInputError):
        Unavailable("EMPTY_INDEX")  # type: ignore[arg-type]
    with pytest.raises(RetrievalInputError):
        Unavailable(UnavailableReason.EMPTY_INDEX, "x" * 513)
    with pytest.raises(RetrievalInputError):
        Unavailable(UnavailableReason.EMPTY_INDEX, "a\x00")


# ---- RetrievedChunk --------------------------------------------------------------------------------------------------------


def test_retrieved_chunk_normalises_published_at_and_serialises():
    cid = UUID("12345678-1234-5678-1234-567812345678")
    r = retrieved(chunk_id=cid, published_at=T0.astimezone(IST), score=0.25)
    assert r.published_at == T0 and r.published_at.tzinfo == UTC
    assert r.to_dict() == {
        "chunk_id": "12345678-1234-5678-1234-567812345678", "source_id": "doc-1", "chunk_index": 0, "text": "text",
        "published_at": "2026-01-15T10:30:00.123456+00:00", "score": 0.25, "rank": 1,
    }


def test_retrieved_chunk_does_not_reapply_the_ingest_text_cap():
    """Stored chunks stay valid if the cap is lowered later (append-only storage, no re-validation)."""
    assert len(retrieved(text="y" * 5000).text) == 5000


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, 1, True, None, "0.5"])
def test_retrieved_chunk_score_must_be_a_finite_float(bad):
    with pytest.raises(RetrievalInputError, match="score"):
        retrieved(score=bad)


@pytest.mark.parametrize("field,bad", [("rank", 0), ("rank", True), ("chunk_id", "not-a-uuid"), ("chunk_index", -1),
                                       ("published_at", datetime(2026, 1, 1)), ("text", ""), ("source_id", "")])
def test_retrieved_chunk_rejects_bad_fields(field, bad):
    with pytest.raises(RetrievalInputError, match=field):
        retrieved(**{field: bad})


# ---- provenance and SearchResult -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("field,bad", [
    ("embedding_config_id", "A" * 64), ("embedding_config_id", "a" * 63), ("input_fingerprint", "g" * 64),
    ("embedding_dimension", 0), ("embedding_dimension", True), ("k", 51), ("k", 0), ("cutoff", datetime(2026, 1, 1)),
])
def test_provenance_rejects_bad_fields(field, bad):
    with pytest.raises(RetrievalInputError, match=field):
        provenance(**{field: bad})


def test_search_result_accepts_ranked_eligible_chunks_and_serialises():
    p = provenance(cutoff=T0.astimezone(IST), k=3)
    chunks = (retrieved(1, 0.9, T0), retrieved(2, 0.9, T0 - timedelta(days=1)), retrieved(3, 0.1, T0))
    result = SearchResult(p, chunks)
    assert result.schema_version == SCHEMA_VERSION == 1
    assert result.provenance.cutoff == T0 and result.provenance.cutoff.tzinfo == UTC
    out = result.to_dict()
    assert out["schema_version"] == 1
    assert out["provenance"] == {"embedding_config_id": HEX_A, "embedding_dimension": 768,
                                 "cutoff": "2026-01-15T10:30:00.123456+00:00", "k": 3, "input_fingerprint": HEX_B}
    assert [c["rank"] for c in out["chunks"]] == [1, 2, 3]


def test_search_result_at_the_cutoff_is_eligible_but_one_microsecond_later_raises():
    assert SearchResult(provenance(), (retrieved(1, 0.5, T0),))
    leak = retrieved(1, 0.5, T0 + timedelta(microseconds=1), source_id="late-doc", chunk_index=7)
    with pytest.raises(CutoffViolationError, match="late-doc"):
        SearchResult(provenance(), (leak,))


def test_search_result_never_drops_a_violating_row():
    ok, leak = retrieved(1, 0.9, T0), retrieved(2, 0.8, T0 + timedelta(seconds=1))
    with pytest.raises(CutoffViolationError):
        SearchResult(provenance(), (ok, leak))


def test_display_scores_are_not_used_to_check_or_reorder_the_ranking():
    """The order is the exact SQL distance order; rounded display scores never validate or re-derive it (spec section 4)."""
    first, second = retrieved(1, 0.1), retrieved(2, 0.9)
    result = SearchResult(provenance(), (first, second))
    assert result.chunks == (first, second)
    assert [c["score"] for c in result.to_dict()["chunks"]] == [0.1, 0.9]


def test_an_empty_result_is_not_a_search_result():
    with pytest.raises(RetrievalInputError, match="Unavailable"):
        SearchResult(provenance(), ())


def test_search_result_structure_is_checked():
    with pytest.raises(RetrievalInputError, match="more than k"):
        SearchResult(provenance(k=1), (retrieved(1, 0.9), retrieved(2, 0.8)))
    with pytest.raises(RetrievalInputError, match="rank"):
        SearchResult(provenance(), (retrieved(2, 0.9),))
    same = uuid4()
    with pytest.raises(RetrievalInputError, match="duplicate"):
        SearchResult(provenance(), (retrieved(1, 0.9, chunk_id=same), retrieved(2, 0.8, chunk_id=same)))
    with pytest.raises(RetrievalInputError, match="chunks"):
        SearchResult(provenance(), [retrieved(1, 0.9)])  # type: ignore[arg-type]


# ---- CutoffAudit -----------------------------------------------------------------------------------------------------------


def audit(**overrides) -> CutoffAudit:
    fields = {"cutoff": T0, "total": 10, "eligible": 7, "excluded_after_cutoff": 3, "returned": 5, "violations": 0,
              "unfiltered_top_k_after_cutoff": 2}
    fields.update(overrides)
    return CutoffAudit(**fields)


def test_cutoff_audit_serialises_with_schema_version_first():
    out = audit(cutoff=T0.astimezone(IST)).to_dict()
    assert list(out)[0] == "schema_version" and out["schema_version"] == 1
    assert out == {"schema_version": 1, "cutoff": "2026-01-15T10:30:00.123456+00:00", "total": 10, "eligible": 7,
                   "excluded_after_cutoff": 3, "returned": 5, "violations": 0, "unfiltered_top_k_after_cutoff": 2}


@pytest.mark.parametrize("overrides", [
    {"total": 11},  # total != eligible + excluded
    {"returned": 8},  # returned - violations > eligible
    {"returned": 9, "violations": 1},  # returned - violations > eligible
    {"returned": 1, "violations": 2},  # violations > returned
    {"unfiltered_top_k_after_cutoff": 4},  # more after-cutoff hits than after-cutoff chunks
    {"eligible": -1, "total": 2},
    {"violations": -1},
    {"returned": True},
    {"cutoff": datetime(2026, 1, 1)},
])
def test_cutoff_audit_counts_are_consistent(overrides):
    with pytest.raises(RetrievalInputError):
        audit(**overrides)


def test_a_cutoff_audit_can_represent_violations():
    """The audit records violations; the service (step 4) raises on them and never returns a result."""
    a = audit(returned=8, violations=1)  # 7 eligible returned plus 1 after the cutoff
    assert (a.returned, a.violations) == (8, 1)
    assert a.to_dict()["violations"] == 1
    assert audit(returned=2, violations=2).violations == 2  # every returned chunk violating is representable


def test_cutoff_violation_error_carries_the_audit_that_detected_it():
    a = audit(returned=8, violations=1)
    err = CutoffViolationError("1 returned chunk is after the cutoff", audit=a)
    assert err.audit is a and isinstance(err, RetrievalError)
    assert str(err) == "1 returned chunk is after the cutoff"
    with pytest.raises(CutoffViolationError) as raised:
        SearchResult(provenance(), (retrieved(1, 0.5, T0 + timedelta(microseconds=1)),))
    assert raised.value.audit is None  # the SearchResult backstop has no audit
