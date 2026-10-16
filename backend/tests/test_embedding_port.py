"""Feature 009 step 2: the provider-neutral embedding port (spec docs/specs/009-rag-date-cutoff.md sections 5 and 7)."""
import math

import pytest

from app.domain.retrieval import RetrievalInputError, Unavailable, UnavailableReason as R
from app.providers.embedding.port import (
    Embedder,
    EmbeddingBatch,
    EmbeddingRole,
    check_vectors,
    require_role,
    require_texts,
)
from embedding_helpers import FAKE_CONFIG_ID, FakeEmbedder, fake_vector

V = (0.5, -0.25, 1.0)


def reason(outcome) -> R:
    assert isinstance(outcome, Unavailable), outcome
    return outcome.reason


def test_roles_are_document_and_query_only():
    assert {r.value for r in EmbeddingRole} == {"DOCUMENT", "QUERY"}
    assert require_role(EmbeddingRole.QUERY) is EmbeddingRole.QUERY
    for bad in ("QUERY", "DOCUMENT", None, 1):
        with pytest.raises(RetrievalInputError, match="role"):
            require_role(bad)


# ---- vector classification (spec section 7, fail-closed; values, never exceptions) -------------------------------------


def test_valid_vectors_pass_through_unchanged_and_in_order():
    out = check_vectors([list(V), [1.0, 2.0, 3.0]], 2, 3)
    assert out == (V, (1.0, 2.0, 3.0))
    assert all(isinstance(v, tuple) for v in out)


@pytest.mark.parametrize("raw", [None, [], (), "vectors", 3, {"embeddings": [V]}])
def test_no_determinable_dimension_is_dimension_unresolved(raw):
    assert reason(check_vectors(raw, 1, 3)) is R.DIMENSION_UNRESOLVED


@pytest.mark.parametrize("raw", [[[0.5, "x", 1.0]], [[0.5, None, 1.0]], [[0.5, True, 1.0]], [[1, 0, 1]], ["abc"], [None]])
def test_non_numeric_elements_are_dimension_unresolved(raw):
    """Only floats cross the port; an adapter converts its own JSON integers before classifying."""
    assert reason(check_vectors(raw, 1, 3)) is R.DIMENSION_UNRESOLVED


def test_a_vector_count_different_from_the_input_count_is_provider_unavailable():
    assert reason(check_vectors([list(V)], 2, 3)) is R.EMBEDDING_PROVIDER_UNAVAILABLE
    assert reason(check_vectors([list(V), list(V)], 1, 3)) is R.EMBEDDING_PROVIDER_UNAVAILABLE


@pytest.mark.parametrize("raw", [[[]], [[0.5, 1.0]], [[0.5, 1.0, 2.0, 3.0]], [list(V), [0.5, 1.0]]])
def test_empty_wrong_or_mixed_lengths_are_dimension_mismatch(raw):
    assert reason(check_vectors(raw, len(raw), 3)) is R.DIMENSION_MISMATCH


@pytest.mark.parametrize("bad", [[math.nan, 1.0, 1.0], [math.inf, 1.0, 1.0], [-math.inf, 1.0, 1.0], [0.0, 0.0, 0.0],
                                 [-0.0, 0.0, 0.0]])
def test_nan_infinite_or_zero_norm_vectors_are_non_finite(bad):
    assert reason(check_vectors([list(V), bad], 2, 3)) is R.NON_FINITE_EMBEDDING


@pytest.mark.parametrize("bad", [
    [1e39, 1.0, 1.0],  # finite in float64, overflows float32
    [-3.5e38, 1.0, 1.0],
    [1e-46, 1e-46, 1e-46],  # every value underflows to zero in float32: zero norm
    [1e-30, 1e-30, 1e-30],  # float32 values survive, but their squared norm underflows to zero
    [2e19, 2e19, 2e19],  # float32 values survive, but their squared norm overflows float32
])
def test_vectors_that_float32_cannot_store_faithfully_are_non_finite(bad):
    """pgvector stores float32: overflow, underflow to zero or an unrepresentable norm is never clamped or repaired."""
    assert reason(check_vectors([bad], 1, 3)) is R.NON_FINITE_EMBEDDING


def test_float32_rounding_alone_is_not_a_failure_and_values_are_returned_unchanged():
    values = [0.1, 1e-20, 3.0]  # 0.1 and 1e-20 round in float32 but stay finite and non-zero
    assert check_vectors([values], 1, 3) == (tuple(values),)


def test_classification_never_raises_for_provider_data():
    for raw, dimension in ((None, 3), ([[math.nan] * 3], 3), ([[object()]], 1), ([[1e308] * 4], 4)):
        assert isinstance(check_vectors(raw, 1, dimension), Unavailable)
    assert reason(check_vectors([[1e308] * 4], 1, 4)) is R.NON_FINITE_EMBEDDING  # finite values, but the norm overflows


# ---- EmbeddingBatch: an invalid batch cannot exist --------------------------------------------------------------------


def test_a_valid_batch():
    b = EmbeddingBatch(FAKE_CONFIG_ID, 3, (V,))
    assert (b.config_id, b.dimension, b.vectors) == (FAKE_CONFIG_ID, 3, (V,))


@pytest.mark.parametrize("args", [
    ("A" * 64, 3, (V,)), ("a" * 63, 3, (V,)), (FAKE_CONFIG_ID, 0, (V,)), (FAKE_CONFIG_ID, True, (V,)),
    (FAKE_CONFIG_ID, 3, [V]), (FAKE_CONFIG_ID, 3, ()), (FAKE_CONFIG_ID, 3, ((0.0, 0.0, 0.0),)),
    (FAKE_CONFIG_ID, 3, ((math.nan, 1.0, 1.0),)), (FAKE_CONFIG_ID, 4, (V,)), (FAKE_CONFIG_ID, 3, ([0.5, 1.0, 2.0],)),
])
def test_an_invalid_batch_raises(args):
    with pytest.raises(RetrievalInputError):
        EmbeddingBatch(*args)


# ---- arguments: the port checks shape, never the product cap ---------------------------------------------------------


@pytest.mark.parametrize("bad", ["one text", [], (), None, ["ok", 3], ["ok", ""], ["  "], ["a\x00b"], ["\ud800"]])
def test_texts_must_be_a_non_empty_sequence_of_valid_strings(bad):
    with pytest.raises(RetrievalInputError, match="text"):
        require_texts(bad)


def test_texts_are_returned_verbatim_and_the_product_cap_is_not_applied_here():
    raw = ["  leading and trailing  ", "x" * 5000]
    assert require_texts(raw) == ("  leading and trailing  ", "x" * 5000)


# ---- fake embedder (used by later steps) -------------------------------------------------------------------------------


def test_the_fake_embedder_satisfies_the_port_and_records_calls():
    fake = FakeEmbedder()
    assert isinstance(fake, Embedder)
    out = fake.embed(["a", "b"], EmbeddingRole.DOCUMENT)
    assert isinstance(out, EmbeddingBatch) and len(out.vectors) == 2 and out.dimension == 8
    assert out.vectors[0] == fake_vector(EmbeddingRole.DOCUMENT, "a", 8)
    assert fake.embed(["a"], EmbeddingRole.QUERY).vectors[0] != out.vectors[0]  # the role changes the vector
    assert fake.calls == [(("a", "b"), EmbeddingRole.DOCUMENT), (("a",), EmbeddingRole.QUERY)]


def test_the_fake_embedder_returns_failures_as_values_and_raises_only_what_it_is_given():
    missing = Unavailable(R.EMBEDDING_MODEL_MISSING, "fake")
    assert FakeEmbedder(outcome=missing).embed(["a"], EmbeddingRole.QUERY) is missing
    with pytest.raises(RetrievalInputError):
        FakeEmbedder(outcome=RetrievalInputError("too long")).embed(["a"], EmbeddingRole.QUERY)
