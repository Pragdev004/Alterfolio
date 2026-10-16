"""Feature 009 step 2: Ollama embedding adapter (spec sections 6-7). Mocked HTTP only; no network, no real model."""
import json

import httpx
import pytest

from app.domain.retrieval import RetrievalInputError, Unavailable, UnavailableReason as R
from app.providers.embedding.ollama import (
    CONTEXT_LENGTH_ERROR,
    DIMENSION,
    DOCUMENT_PREFIX,
    JOIN,
    MODEL_TAG,
    PROVIDER,
    QUERY_PREFIX,
    VERIFIED_MANIFEST_DIGEST,
    OllamaEmbedder,
    embedding_config_id,
)
from app.providers.embedding.port import Embedder, EmbeddingBatch, EmbeddingRole

DOC, QUERY = EmbeddingRole.DOCUMENT, EmbeddingRole.QUERY
DIGEST_HEX = "0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f"
# SHA-256 of the canonical identity JSON, computed independently of the adapter (spec section 6).
EXPECTED_CONFIG_ID = "5386b946aa9b7fe26f3f3f959ffb1349a2f1c630f48aa9f231f073271109f3f1"
BASE = "http://localhost:11434"


def vec(seed: int = 1) -> list[float]:
    return [((i * 7 + seed) % 13 - 6) / 8 + 0.01 for i in range(DIMENSION)]


def tags(digest: str = DIGEST_HEX, name: str = MODEL_TAG, extra: list | None = None) -> httpx.Response:
    models = [{"name": name, "model": name, "digest": digest}] + (extra or [])
    return httpx.Response(200, json={"models": models})


def embedded(*vectors) -> httpx.Response:
    return httpx.Response(200, json={"model": MODEL_TAG, "embeddings": [list(v) for v in vectors]})


class Server:
    """Answers /api/tags and /api/embed with the given responses (or raises), recording every request."""

    def __init__(self, embed=None, tag=None):
        self.requests: list[httpx.Request] = []
        self._embed = embed if embed is not None else (lambda request: embedded(*[vec(i) for i in range(len(body(request)["input"]))]))
        self._tag = tag if tag is not None else (lambda request: tags())

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        handler = self._tag if request.url.path == "/api/tags" else self._embed
        result = handler(request)
        if isinstance(result, Exception):
            raise result
        return result

    def embeds(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == "/api/embed"]


def body(request: httpx.Request) -> dict:
    return json.loads(request.content)


def adapter(server: Server) -> OllamaEmbedder:
    return OllamaEmbedder(client=httpx.Client(transport=httpx.MockTransport(server)))


def reason(outcome) -> R:
    assert isinstance(outcome, Unavailable), outcome
    return outcome.reason


# ---- request contract ----------------------------------------------------------------------------------------------------


def test_constructing_the_adapter_touches_no_network():
    server = Server()
    adapter(server)
    OllamaEmbedder()  # builds its own client lazily
    assert server.requests == []


@pytest.mark.parametrize("role,prefix", [(DOC, "search_document:"), (QUERY, "search_query:")])
def test_exact_urls_and_body_with_role_prefix_and_truncate_false(role, prefix):
    server = Server()
    out = adapter(server).embed(["Quarterly results.", "  kept verbatim "], role)
    assert isinstance(out, EmbeddingBatch)
    tag_request, embed_request = server.requests
    assert (tag_request.method, str(tag_request.url)) == ("GET", f"{BASE}/api/tags")
    assert (embed_request.method, str(embed_request.url)) == ("POST", f"{BASE}/api/embed")
    assert body(embed_request) == {
        "model": "nomic-embed-text:latest",
        "input": [f"{prefix} Quarterly results.", f"{prefix}   kept verbatim "],
        "truncate": False,
    }
    assert body(embed_request)["truncate"] is False  # present and false, never omitted or true


def test_prefix_constants_and_one_space_join():
    assert (DOCUMENT_PREFIX, QUERY_PREFIX, JOIN) == ("search_document:", "search_query:", "<prefix> <text>")


def test_a_successful_batch_has_one_768_vector_per_input_in_order():
    server = Server(embed=lambda request: embedded(vec(1), vec(2)))
    out = adapter(server).embed(["a", "b"], DOC)
    assert isinstance(out, EmbeddingBatch)
    assert out.dimension == DIMENSION == 768
    assert out.vectors == (tuple(vec(1)), tuple(vec(2)))
    assert out.config_id == EXPECTED_CONFIG_ID


def test_json_integers_are_read_as_exact_floats():
    values = [1] + [0] * (DIMENSION - 1)
    out = adapter(Server(embed=lambda request: embedded(values))).embed(["a"], DOC)
    assert isinstance(out, EmbeddingBatch) and out.vectors[0][:2] == (1.0, 0.0)
    assert all(type(x) is float for x in out.vectors[0])


def test_the_adapter_satisfies_the_port():
    assert isinstance(adapter(Server()), Embedder)


def test_the_adapter_never_applies_the_product_cap_or_shortens_text():
    """Oversized inputs must reach the model so its context-length rejection can be observed (plan step 6)."""
    server = Server()
    adapter(server).embed(["x" * 5000], QUERY)
    assert body(server.embeds()[0])["input"] == ["search_query: " + "x" * 5000]


@pytest.mark.parametrize("bad_texts,bad_role", [("one text", DOC), ([], DOC), (["ok", 3], DOC), (["a\x00"], DOC),
                                                (["ok"], "QUERY"), (["ok"], None)])
def test_invalid_arguments_raise_before_any_request(bad_texts, bad_role):
    server = Server()
    with pytest.raises(RetrievalInputError):
        adapter(server).embed(bad_texts, bad_role)
    assert server.requests == []


# ---- embedding identity (spec section 6) ----------------------------------------------------------------------------------


IDENTITY = {
    "provider": "ollama", "model_tag": "nomic-embed-text:latest", "manifest_digest": "sha256:" + DIGEST_HEX,
    "dimension": 768, "document_prefix": "search_document:", "query_prefix": "search_query:", "join": "<prefix> <text>",
    "truncate": False,
}


def test_the_config_id_is_the_sha256_of_the_canonical_identity_and_is_stable():
    assert embedding_config_id(**IDENTITY) == EXPECTED_CONFIG_ID
    assert embedding_config_id(**IDENTITY) == embedding_config_id(**dict(reversed(list(IDENTITY.items()))))
    assert (PROVIDER, MODEL_TAG, VERIFIED_MANIFEST_DIGEST) == ("ollama", "nomic-embed-text:latest", "sha256:" + DIGEST_HEX)


@pytest.mark.parametrize("field,other", [
    ("provider", "other"), ("model_tag", "nomic-embed-text:v1.5"), ("manifest_digest", "sha256:" + "b" * 64),
    ("dimension", 384), ("document_prefix", "search_document"), ("query_prefix", "query:"), ("join", "<prefix>\n<text>"),
    ("truncate", True),
])
def test_every_identity_field_changes_the_config_id(field, other):
    assert embedding_config_id(**{**IDENTITY, field: other}) != EXPECTED_CONFIG_ID


def test_a_prefixed_digest_from_the_server_gives_the_same_config_id():
    out = adapter(Server(tag=lambda request: tags(digest="sha256:" + DIGEST_HEX))).embed(["a"], DOC)
    assert isinstance(out, EmbeddingBatch) and out.config_id == EXPECTED_CONFIG_ID


# ---- model presence and digest (checked on every call, before any text is sent) ---------------------------------------------


def test_a_model_absent_from_the_listing_is_model_missing_and_no_text_is_sent():
    server = Server(tag=lambda request: tags(name="other-model:latest"))
    assert reason(adapter(server).embed(["a"], DOC)) is R.EMBEDDING_MODEL_MISSING
    assert server.embeds() == []


def test_a_server_digest_other_than_the_verified_one_is_incompatible_and_no_text_is_sent():
    server = Server(tag=lambda request: tags(digest="b" * 64))
    out = adapter(server).embed(["a"], DOC)
    assert reason(out) is R.EMBEDDING_INCOMPATIBLE
    assert server.embeds() == []


@pytest.mark.parametrize("tag", [
    lambda request: httpx.Response(500, json={"error": "boom"}),
    lambda request: httpx.Response(200, content=b"not json"),
    lambda request: httpx.Response(200, json={"models": "nope"}),
    lambda request: tags(digest="not-a-digest"),
    lambda request: tags(digest=None),
    lambda request: tags(extra=[{"name": MODEL_TAG, "digest": DIGEST_HEX}]),  # ambiguous listing
    lambda request: httpx.ReadTimeout("slow"),
    lambda request: httpx.ConnectError("refused"),
])
def test_an_unusable_model_listing_is_provider_unavailable_and_no_text_is_sent(tag):
    server = Server(tag=tag)
    assert reason(adapter(server).embed(["a"], DOC)) is R.EMBEDDING_PROVIDER_UNAVAILABLE
    assert server.embeds() == []


def test_the_listing_is_checked_on_every_call_never_cached():
    server = Server()
    a = adapter(server)
    a.embed(["a"], DOC)
    a.embed(["b"], QUERY)
    assert [r.url.path for r in server.requests] == ["/api/tags", "/api/embed", "/api/tags", "/api/embed"]


# ---- provider failures (spec section 7, most specific first; exactly one embed request, no retry) ----------------------------


@pytest.mark.parametrize("role", [DOC, QUERY])
def test_the_context_length_rejection_is_an_input_error_for_each_role(role):
    server = Server(embed=lambda request: httpx.Response(400, json={"error": CONTEXT_LENGTH_ERROR}))
    with pytest.raises(RetrievalInputError, match="context length"):
        adapter(server).embed(["x" * 16000], role)
    assert len(server.embeds()) == 1  # no retry, no shortening


def test_the_context_length_text_is_the_one_observed_on_ollama():
    assert CONTEXT_LENGTH_ERROR == "the input length exceeds the context length"


def test_a_model_reported_missing_by_the_server_is_model_missing():
    server = Server(embed=lambda request: httpx.Response(404, json={"error": 'model "nomic-embed-text" not found, try pulling it first'}))
    assert reason(adapter(server).embed(["a"], DOC)) is R.EMBEDDING_MODEL_MISSING


@pytest.mark.parametrize("response", [
    lambda request: httpx.Response(400, json={"error": "invalid input type"}),  # another 400 is not a context rejection
    lambda request: httpx.Response(400, content=b"the input length exceeds the context length"),  # not the JSON error
    lambda request: httpx.Response(404, content=b"no route"),
    lambda request: httpx.Response(500, json={"error": "boom"}),
    lambda request: httpx.Response(503, content=b""),
    lambda request: httpx.ReadTimeout("slow"),
    lambda request: httpx.ConnectError("refused"),
    lambda request: httpx.Response(200, content=b"not json"),
    lambda request: httpx.Response(200, json=["not", "an", "object"]),
])
def test_other_failures_are_provider_unavailable_with_exactly_one_embed_request(response):
    server = Server(embed=response)
    assert reason(adapter(server).embed(["a"], DOC)) is R.EMBEDDING_PROVIDER_UNAVAILABLE
    assert len(server.embeds()) == 1


# ---- invalid vectors (fail-closed; returned as values, never repaired) --------------------------------------------------------


def raw_embed(text: str):
    return lambda request: httpx.Response(200, content=text.encode("utf-8"))


ZEROS = "[" + ",".join(["0.0"] * DIMENSION) + "]"
GOOD = json.dumps(vec(1))


@pytest.mark.parametrize("payload,expected", [
    ('{"embeddings":[[NaN' + ",0.5" * (DIMENSION - 1) + "]]}", R.NON_FINITE_EMBEDDING),
    ('{"embeddings":[[Infinity' + ",0.5" * (DIMENSION - 1) + "]]}", R.NON_FINITE_EMBEDDING),
    ('{"embeddings":[' + ZEROS + "]}", R.NON_FINITE_EMBEDDING),
    ('{"embeddings":[[]]}', R.DIMENSION_MISMATCH),
    ('{"embeddings":[[0.5,0.5]]}', R.DIMENSION_MISMATCH),
    ('{"embeddings":[' + json.dumps(vec(1) + [0.5]) + "]}", R.DIMENSION_MISMATCH),
    ('{"model":"m"}', R.DIMENSION_UNRESOLVED),
    ('{"embeddings":[]}', R.DIMENSION_UNRESOLVED),
    ('{"embeddings":[["a"' + ",0.5" * (DIMENSION - 1) + "]]}", R.DIMENSION_UNRESOLVED),
    ('{"embeddings":[[true' + ",0.5" * (DIMENSION - 1) + "]]}", R.DIMENSION_UNRESOLVED),
    ('{"embeddings":[' + GOOD + "," + GOOD + "]}", R.EMBEDDING_PROVIDER_UNAVAILABLE),  # 2 vectors for 1 input
])
def test_invalid_vectors_map_to_the_spec_reasons(payload, expected):
    assert reason(adapter(Server(embed=raw_embed(payload))).embed(["a"], DOC)) is expected


def test_mixed_lengths_in_one_batch_are_dimension_mismatch():
    server = Server(embed=lambda request: embedded(vec(1), vec(2)[:-1]))
    assert reason(adapter(server).embed(["a", "b"], DOC)) is R.DIMENSION_MISMATCH
