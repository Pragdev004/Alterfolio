"""Ollama adapter behind the embedding port (Feature 009, spec sections 6-7). The only module that knows Ollama's URLs,
JSON shapes, model tag, prefixes and error text. Imported only by tests in Feature 009 (there is no composition root).

Every call: GET /api/tags (the model must be listed with the verified manifest digest), then exactly one POST /api/embed
with every text joined to the role prefix by one space and `truncate: false`. No retry, no truncation, no shortening, no
partial batch, no caching of the listing; failures are `Unavailable` values.
"""

import hashlib
import json
import math
import re
from collections.abc import Sequence

import httpx

from app.domain.retrieval import EMBEDDING_DIMENSION, RetrievalInputError, Unavailable, UnavailableReason
from app.providers.embedding.port import (
    EmbeddingBatch,
    EmbeddingOutcome,
    EmbeddingRole,
    check_vectors,
    require_role,
    require_texts,
)

PROVIDER = "ollama"
MODEL_TAG = "nomic-embed-text:latest"
# The manifest digest verified on 2026-10-15 (spec section 10). A server listing another digest is refused, so a moved
# `latest` tag is an explicit EMBEDDING_INCOMPATIBLE, never silent drift. Matching it does not prove upstream provenance.
# Identity form (spec section 6: "full `sha256:`"): always "sha256:" + 64 lowercase hex. Ollama 0.24.0's /api/tags lists the
# digest as bare hex, so the adapter adds the "sha256:" prefix; a listing that already carries it is accepted unchanged.
VERIFIED_MANIFEST_DIGEST = "sha256:0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f"
DIMENSION = EMBEDDING_DIMENSION
DOCUMENT_PREFIX = "search_document:"
QUERY_PREFIX = "search_query:"
JOIN = "<prefix> <text>"  # exactly one space (owner-confirmed 2026-10-15)
TRUNCATE = False
# The exact error text observed on Ollama 0.24.0 for an input longer than the model context (spec section 7).
CONTEXT_LENGTH_ERROR = "the input length exceeds the context length"
DEFAULT_BASE_URL = "http://localhost:11434"

_PREFIX = {EmbeddingRole.DOCUMENT: DOCUMENT_PREFIX, EmbeddingRole.QUERY: QUERY_PREFIX}
_DIGEST = re.compile(r"(?:sha256:)?([0-9a-f]{64})")


def embedding_config_id(*, provider: str, model_tag: str, manifest_digest: str, dimension: int, document_prefix: str,
                        query_prefix: str, join: str, truncate: bool) -> str:
    """SHA-256 of the canonical JSON (sorted keys, no whitespace) of every embedding identity field (spec section 6)."""
    identity = {
        "provider": provider, "model_tag": model_tag, "manifest_digest": manifest_digest, "dimension": dimension,
        "document_prefix": document_prefix, "query_prefix": query_prefix, "join": join, "truncate": truncate,
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


CONFIG_ID = embedding_config_id(
    provider=PROVIDER, model_tag=MODEL_TAG, manifest_digest=VERIFIED_MANIFEST_DIGEST, dimension=DIMENSION,
    document_prefix=DOCUMENT_PREFIX, query_prefix=QUERY_PREFIX, join=JOIN, truncate=TRUNCATE,
)


def _unavailable(reason: UnavailableReason, detail: str) -> Unavailable:
    return Unavailable(reason, detail)


def _provider_down(detail: str) -> Unavailable:
    return _unavailable(UnavailableReason.EMBEDDING_PROVIDER_UNAVAILABLE, detail)


def _json(response: httpx.Response) -> object:
    try:
        return json.loads(response.content)
    except (ValueError, RecursionError):
        return None


def _error_text(response: httpx.Response) -> str | None:
    doc = _json(response)
    if isinstance(doc, dict) and isinstance(doc.get("error"), str):
        return doc["error"]
    return None


def _as_float(value: object) -> object:
    """JSON integers become exact floats; anything else is left for `check_vectors` to classify."""
    if isinstance(value, bool) or not isinstance(value, int):
        return value
    try:
        return float(value)
    except OverflowError:
        return math.inf  # beyond float range: classified as non-finite, never clamped


def _floats(raw: object) -> object:
    if not isinstance(raw, list):
        return raw
    return [[_as_float(x) for x in v] if isinstance(v, list) else v for v in raw]


class OllamaEmbedder:
    def __init__(self, *, base_url: str = DEFAULT_BASE_URL, client: httpx.Client | None = None,
                 timeout_seconds: float = 60) -> None:
        self._base = base_url.rstrip("/")
        self._client = client
        self._timeout = timeout_seconds

    def _http(self) -> httpx.Client:
        if self._client is None:  # built lazily: constructing the adapter must not touch the network
            self._client = httpx.Client(timeout=self._timeout)
        return self._client

    def embed(self, texts: Sequence[str], role: EmbeddingRole) -> EmbeddingOutcome:
        items = require_texts(texts)
        role = require_role(role)
        identity = self._check_model()
        if identity is not None:
            return identity
        payload = {"model": MODEL_TAG, "input": [f"{_PREFIX[role]} {text}" for text in items], "truncate": TRUNCATE}
        try:
            response = self._http().post(self._base + "/api/embed", json=payload)
        except httpx.TimeoutException:
            return _provider_down("timeout while embedding")
        except httpx.HTTPError:
            return _provider_down("network error while embedding")
        if response.status_code == 400 and _error_text(response) == CONTEXT_LENGTH_ERROR:
            raise RetrievalInputError(
                f"a {role.value} input exceeds the embedding model's context length "
                f"({len(items)} input(s) in the request; nothing was embedded, nothing was shortened)"
            )
        if response.status_code == 404 and "not found" in (_error_text(response) or "").lower():
            return _unavailable(UnavailableReason.EMBEDDING_MODEL_MISSING, "the server reports the model is not found")
        if response.status_code != 200:
            return _provider_down(f"the embedding request returned HTTP {response.status_code}")
        doc = _json(response)
        if not isinstance(doc, dict):
            return _provider_down("unusable embedding response")
        checked = check_vectors(_floats(doc.get("embeddings")), len(items), DIMENSION)
        if isinstance(checked, Unavailable):
            return checked
        # The tag this request named and whose digest `_check_model` verified; it is also a field of CONFIG_ID.
        return EmbeddingBatch(CONFIG_ID, DIMENSION, checked, model=MODEL_TAG)

    def _check_model(self) -> Unavailable | None:
        """The model must be listed exactly once, with the verified manifest digest. None means it is."""
        try:
            response = self._http().get(self._base + "/api/tags")
        except httpx.TimeoutException:
            return _provider_down("timeout while listing models")
        except httpx.HTTPError:
            return _provider_down("network error while listing models")
        if response.status_code != 200:
            return _provider_down(f"the model listing returned HTTP {response.status_code}")
        doc = _json(response)
        models = doc.get("models") if isinstance(doc, dict) else None
        if not isinstance(models, list):
            return _provider_down("unusable model listing")
        entries = [m for m in models if isinstance(m, dict) and m.get("name") == MODEL_TAG]
        if not entries:
            return _unavailable(UnavailableReason.EMBEDDING_MODEL_MISSING, f"{MODEL_TAG} is not listed by the server")
        if len(entries) > 1:
            return _provider_down("the model listing names the model more than once")
        digest = entries[0].get("digest")
        match = _DIGEST.fullmatch(digest) if isinstance(digest, str) else None
        if match is None:
            return _provider_down("the model listing has no usable digest")
        if "sha256:" + match.group(1) != VERIFIED_MANIFEST_DIGEST:
            return _unavailable(UnavailableReason.EMBEDDING_INCOMPATIBLE,
                                "the server's model digest differs from the verified manifest digest")
        return None
