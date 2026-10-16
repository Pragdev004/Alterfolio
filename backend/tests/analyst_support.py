"""Shared fakes for the Feature 010 analyst tests. No network, no database."""
from datetime import date, datetime, timezone
from types import SimpleNamespace
from uuid import UUID

from app.analyst.types import Fact

USER = UUID("00000000-0000-0000-0000-000000000001")
D = date(2026, 10, 10)
CHUNK_OK = "11111111-1111-1111-1111-111111111111"
CHUNK_LATE = "22222222-2222-2222-2222-222222222222"


def fact(name="bias_cost.cost_inr", value="1234.50", source="bias_cost", unit="INR", as_of=D):
    return Fact(name=name, value=value, source=source, as_of=as_of, unit=unit)


class FakeTools(dict):
    """intent -> callable(user_id, as_of) -> facts; records calls."""

    def __init__(self, by_intent):
        super().__init__({k: self._wrap(k, v) for k, v in by_intent.items()})
        self.calls = []

    def _wrap(self, intent, facts):
        def call(user_id, as_of):
            self.calls.append((intent, user_id, as_of))
            return tuple(facts)
        return call


def chunk(chunk_id, text, published, source_id="note"):
    return SimpleNamespace(chunk_id=chunk_id, source_id=source_id, chunk_index=0, text=text,
                           published_at=published, score=0.5, rank=1)


class FakeRetriever:
    """Duck-typed SearchResult; may return chunks a real SearchResult would refuse (late ones)."""

    def __init__(self, chunks, cutoff_echo=None):
        self.chunks = chunks
        self.cutoff_echo = cutoff_echo
        self.calls = []

    def search(self, *, user_id, query_text, cutoff, k):
        self.calls.append({"user_id": user_id, "query_text": query_text, "cutoff": cutoff, "k": k})
        prov = SimpleNamespace(cutoff=self.cutoff_echo or cutoff)
        return SimpleNamespace(provenance=prov, chunks=tuple(self.chunks))


def dt(y, m, d, h=12):
    return datetime(y, m, d, h, tzinfo=timezone.utc)
