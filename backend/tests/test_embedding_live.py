"""Feature 009 step 6: the Ollama adapter against the real local model (plan step 6; spec sections 6, 7, 10).

Skipped unless ALTERFOLIO_TEST_OLLAMA_URL names a running Ollama server (for example http://localhost:11434). A skipped run is
not verification. Inputs are synthetic; nothing is stored.
"""
import hashlib
import math
import os
from pathlib import Path

import httpx
import pytest

from app.domain.retrieval import RetrievalInputError
from app.providers.embedding.ollama import (
    CONFIG_ID,
    DIMENSION,
    DOCUMENT_PREFIX,
    MODEL_TAG,
    QUERY_PREFIX,
    VERIFIED_MANIFEST_DIGEST,
    OllamaEmbedder,
)
from app.providers.embedding.port import EmbeddingBatch, EmbeddingRole

OLLAMA_URL = os.environ.get("ALTERFOLIO_TEST_OLLAMA_URL")
live_ollama = pytest.mark.skipif(not OLLAMA_URL, reason="no live Ollama configured (ALTERFOLIO_TEST_OLLAMA_URL)")
pytestmark = live_ollama

DOC, QUERY = EmbeddingRole.DOCUMENT, EmbeddingRole.QUERY
TEXT = "The company published its quarterly results on Tuesday."
ENGLISH_16000 = ("The board reviewed the quarterly filing and the auditors' notes. " * 300)[:16000]
DIGITS_4000 = "0123456789" * 400  # in the product cap, but rejected by the model context in the 2026-10-15 probe


def manifest_path() -> Path:
    models = Path(os.environ.get("OLLAMA_MODELS") or Path.home() / ".ollama" / "models")
    return models / "manifests" / "registry.ollama.ai" / "library" / "nomic-embed-text" / "latest"


def raw_embed(text: str) -> tuple[float, ...]:
    """One direct /api/embed call with exactly the given input (no adapter), `truncate: false`."""
    response = httpx.post(OLLAMA_URL.rstrip("/") + "/api/embed", json={"model": MODEL_TAG, "input": [text], "truncate": False},
                          timeout=60)
    response.raise_for_status()
    return tuple(float(x) for x in response.json()["embeddings"][0])


def cosine(a, b) -> float:
    return math.fsum(x * y for x, y in zip(a, b)) / (math.hypot(*a) * math.hypot(*b))


@pytest.fixture(scope="module")
def embedder():
    return OllamaEmbedder(base_url=OLLAMA_URL)


def test_the_server_digest_equals_the_local_manifest_and_the_verified_digest():
    listing = httpx.get(OLLAMA_URL.rstrip("/") + "/api/tags", timeout=30).json()["models"]
    (entry,) = [m for m in listing if m["name"] == MODEL_TAG]
    local = hashlib.sha256(manifest_path().read_bytes()).hexdigest()
    assert "sha256:" + entry["digest"].removeprefix("sha256:") == "sha256:" + local == VERIFIED_MANIFEST_DIGEST


@pytest.mark.parametrize("role", [DOC, QUERY])
def test_an_in_cap_input_returns_768_finite_values_with_the_adapter_identity(embedder, role):
    out = embedder.embed([TEXT, "A second, different sentence."], role)
    assert isinstance(out, EmbeddingBatch)
    assert (out.dimension, out.config_id, out.model, len(out.vectors)) == (DIMENSION, CONFIG_ID, MODEL_TAG, 2)
    for vector in out.vectors:
        assert len(vector) == 768 and all(isinstance(x, float) and math.isfinite(x) for x in vector)
        assert math.hypot(*vector) > 0


@pytest.mark.parametrize("role,prefix", [(DOC, DOCUMENT_PREFIX), (QUERY, QUERY_PREFIX)])
def test_the_role_prefix_is_applied_with_exactly_one_space(embedder, role, prefix):
    (vector,) = embedder.embed([TEXT], role).vectors
    prefixed, bare = raw_embed(f"{prefix} {TEXT}"), raw_embed(TEXT)
    assert cosine(vector, prefixed) >= 0.99999
    assert cosine(vector, prefixed) > cosine(vector, bare)


@pytest.mark.parametrize("role", [DOC, QUERY])
def test_an_oversized_input_is_the_context_length_input_error(embedder, role):
    with pytest.raises(RetrievalInputError, match="context length"):
        embedder.embed([ENGLISH_16000], role)


@pytest.mark.parametrize("role", [DOC, QUERY])
def test_a_digit_heavy_in_cap_input_is_rejected_not_assumed_to_succeed(embedder, role):
    assert len(DIGITS_4000) == 4000
    with pytest.raises(RetrievalInputError, match="context length"):
        embedder.embed([DIGITS_4000], role)
