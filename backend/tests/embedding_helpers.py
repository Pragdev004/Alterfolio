"""Fake embedder for the Feature 009 tests: offline, deterministic, and bound by the same embedding port contract."""

import hashlib
from collections.abc import Sequence

from app.domain.retrieval import Unavailable
from app.providers.embedding.port import EmbeddingBatch, EmbeddingOutcome, EmbeddingRole, require_role, require_texts

FAKE_CONFIG_ID = hashlib.sha256(b"fake-embedder-v1").hexdigest()


def fake_vector(role: EmbeddingRole, text: str, dimension: int) -> tuple[float, ...]:
    """Deterministic, finite and never zero: derived from SHA-256 of (role, text); the first value is always >= 1."""
    digest = hashlib.sha256(f"{role.value}\x1f{text}".encode("utf-8")).digest()
    values = [(digest[i % len(digest)] - 127.5) / 128 for i in range(dimension)]
    values[0] = 1 + abs(values[0])
    return tuple(values)


class FakeEmbedder:
    """Records every call. `outcome` replaces the batch: an `Unavailable` is returned, an exception is raised."""

    def __init__(self, *, dimension: int = 8, config_id: str = FAKE_CONFIG_ID,
                 outcome: Unavailable | Exception | None = None) -> None:
        self.dimension = dimension
        self.config_id = config_id
        self.outcome = outcome
        self.calls: list[tuple[tuple[str, ...], EmbeddingRole]] = []

    def embed(self, texts: Sequence[str], role: EmbeddingRole) -> EmbeddingOutcome:
        items = require_texts(texts)
        role = require_role(role)
        self.calls.append((items, role))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        if isinstance(self.outcome, Unavailable):
            return self.outcome
        return EmbeddingBatch(self.config_id, self.dimension, tuple(fake_vector(role, t, self.dimension) for t in items))
