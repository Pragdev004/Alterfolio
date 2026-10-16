"""Embedding port: the provider-neutral surface the retrieval service may import (Feature 009, spec sections 5-7).

Stdlib + domain only; no vendor name, URL or payload crosses it. Contract, identical for every provider:
- `embed(texts, role)` embeds each original text with the role's prefix, which the provider applies (DOCUMENT for stored
  chunks, QUERY for search queries). Callers never add a prefix themselves.
- Exactly one embedding request per call: no retry, no truncation, no shortening, no partial batch.
- Provider failures are values (`Unavailable`), never exceptions, and never a zero vector or a fallback. The only exception
  is `RetrievalInputError`: an invalid argument, or an input the model rejects as longer than its context.
- An `EmbeddingBatch` holds exactly one finite, non-zero vector of `dimension` floats per input, in input order, and every
  vector stays finite with a finite non-zero norm once converted to float32 (how pgvector stores it).
"""

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from app.domain import limits
from app.domain.retrieval import RetrievalInputError, Unavailable, UnavailableReason, as_float32

_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


class EmbeddingRole(str, Enum):
    DOCUMENT = "DOCUMENT"  # stored chunks
    QUERY = "QUERY"  # search queries


def require_role(role: object) -> EmbeddingRole:
    if not isinstance(role, EmbeddingRole):
        raise RetrievalInputError("role must be an EmbeddingRole")
    return role


def require_texts(texts: object) -> tuple[str, ...]:
    """A non-empty sequence of non-blank, NUL-free, UTF-8-encodable strings, returned verbatim.

    The product length cap is not applied here; the service applies it before calling (spec section 4).
    """
    if isinstance(texts, (str, bytes)) or not isinstance(texts, Sequence) or not texts:
        raise RetrievalInputError("texts must be a non-empty sequence of strings")
    for text in texts:
        if not isinstance(text, str) or "\x00" in text or not text.strip():
            raise RetrievalInputError("each text must be a non-blank string without NUL characters")
        try:
            text.encode("utf-8")
        except UnicodeEncodeError:
            raise RetrievalInputError("each text must be encodable as UTF-8") from None
    return tuple(texts)


def check_vectors(raw: object, expected_count: int, dimension: int) -> tuple[tuple[float, ...], ...] | Unavailable:
    """Classify provider vectors (spec section 7). Returns them unchanged, or the `Unavailable` that applies.

    Never repairs, pads, truncates, normalises or reorders. Only floats are accepted; an adapter converts its own JSON
    integers first.
    """
    if not isinstance(raw, (list, tuple)) or not raw:
        return Unavailable(UnavailableReason.DIMENSION_UNRESOLVED, "the response holds no vectors")
    if len(raw) != expected_count:
        return Unavailable(UnavailableReason.EMBEDDING_PROVIDER_UNAVAILABLE,
                           f"the response holds {len(raw)} vectors for {expected_count} inputs")
    if not all(isinstance(v, (list, tuple)) and all(isinstance(x, float) for x in v) for v in raw):
        return Unavailable(UnavailableReason.DIMENSION_UNRESOLVED, "a vector is not a list of floating-point numbers")
    if any(len(v) != dimension for v in raw):
        return Unavailable(UnavailableReason.DIMENSION_MISMATCH, f"a vector does not have exactly {dimension} values")
    for v in raw:
        norm = math.hypot(*v)
        if not all(math.isfinite(x) for x in v) or not math.isfinite(norm) or norm == 0:
            return Unavailable(UnavailableReason.NON_FINITE_EMBEDDING,
                               "a vector has a NaN or infinite value, or a zero norm (its cosine distance is undefined)")
        if as_float32(v) is None:  # vectors are stored as float32 (pgvector): overflow or underflow is never clamped
            return Unavailable(UnavailableReason.NON_FINITE_EMBEDDING,
                               "a vector has a value or norm that is not finite and non-zero once converted to float32")
    return tuple(tuple(v) for v in raw)


@dataclass(frozen=True)
class EmbeddingBatch:
    """One provider answer: `config_id` is the provider's embedding identity (64 lowercase-hex SHA-256, spec section 6).

    `model` is the model name the provider itself used (stored as `embedding_model` provenance). It is reported by the
    provider, never guessed by a caller; None means the provider did not report it, and ingest then stores nothing.
    """

    config_id: str
    dimension: int
    vectors: tuple[tuple[float, ...], ...]
    model: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.config_id, str) or not _SHA256_HEX.fullmatch(self.config_id):
            raise RetrievalInputError("config_id must be 64 lowercase hexadecimal characters")
        if self.model is not None and (
            not isinstance(self.model, str) or not self.model.strip() or "\x00" in self.model
            or len(self.model) > limits.MAX_EMBEDDING_MODEL_LENGTH
        ):
            raise RetrievalInputError(
                f"model must be None or non-blank text of at most {limits.MAX_EMBEDDING_MODEL_LENGTH} characters"
            )
        if isinstance(self.dimension, bool) or not isinstance(self.dimension, int) or self.dimension < 1:
            raise RetrievalInputError("dimension must be a positive integer")
        if not isinstance(self.vectors, tuple) or not all(isinstance(v, tuple) for v in self.vectors):
            raise RetrievalInputError("vectors must be a tuple of tuples")
        checked = check_vectors(self.vectors, len(self.vectors), self.dimension)
        if isinstance(checked, Unavailable):
            raise RetrievalInputError(f"invalid embedding batch: {checked.reason.value}")


EmbeddingOutcome = EmbeddingBatch | Unavailable


@runtime_checkable
class Embedder(Protocol):
    def embed(self, texts: Sequence[str], role: EmbeddingRole) -> EmbeddingOutcome:
        """One vector per text, in order, for the given role.

        Must not raise for provider, network or response problems: return `Unavailable`. Raises `RetrievalInputError` only
        for invalid arguments or an input the model rejects as longer than its context.
        """
        ...
