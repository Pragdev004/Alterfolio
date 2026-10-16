"""Feature 009 step 5: retrieval type surface and embedding-port purity (plan step 5; spec sections 5 and 7).

Type surface: across every dataclass the retrieval modules define, `float` appears only in the vector, score and distance fields
(an exact allowlist, so a new float field fails), and `Decimal` appears nowhere. Port purity: the port imports only the standard
library and `app.domain`, names no embedding vendor, URL or payload detail, and reports provider failures as values.
"""
import ast
import dataclasses
import importlib
import sys
import typing
from decimal import Decimal
from pathlib import Path

from sqlalchemy import Float, Numeric

from app.domain.retrieval import RetrievalInputError, Unavailable
from app.models.chunk import DocumentChunk
from app.providers.embedding import ollama
from app.providers.embedding.port import Embedder, EmbeddingBatch

APP = Path(__file__).resolve().parent.parent / "app"
PORT = APP / "providers" / "embedding" / "port.py"
RETRIEVAL_MODULES = (
    "app.domain.retrieval", "app.providers.embedding.port", "app.providers.embedding.ollama", "app.repositories.chunks",
    "app.services.retrieval",
)
# The only float-bearing fields, with their exact types: embedding vectors, the display score and the SQL cosine distance.
# `NewChunk.embedding` is the repository's input vector (one row of `EmbeddingBatch.vectors`).
FLOAT_FIELDS = {
    ("EmbeddingBatch", "vectors"): tuple[tuple[float, ...], ...],
    ("NewChunk", "embedding"): tuple[float, ...],
    ("RetrievedChunk", "score"): float,
    ("ChunkHit", "distance"): float,
    ("NearestHit", "distance"): float,
}
# Embedding vendors and transport details that must never cross the port; the adapter's own constants are added below.
VENDOR_WORDS = ("ollama", "nomic", "httpx", "http", "/api/", "localhost", "openai", "huggingface", "sentence_transformers")


def _mentions(tp, target) -> bool:
    return tp is target or any(_mentions(arg, target) for arg in typing.get_args(tp))


def _dataclasses() -> list[type]:
    found = []
    for name in RETRIEVAL_MODULES:
        module = importlib.import_module(name)
        found += [obj for obj in vars(module).values()
                  if isinstance(obj, type) and dataclasses.is_dataclass(obj) and obj.__module__ == name]
    return found


# ---- type surface ------------------------------------------------------------------------------------------------------------


def test_float_appears_only_in_vector_score_and_distance_fields():
    classes = _dataclasses()
    assert {c.__name__ for c in classes} >= {"EmbeddingBatch", "RetrievedChunk", "SearchResult", "CutoffAudit", "ChunkHit"}
    floats = {(c.__name__, field): hint for c in classes for field, hint in typing.get_type_hints(c).items()
              if _mentions(hint, float)}
    assert floats == FLOAT_FIELDS


def test_no_retrieval_type_or_annotation_uses_decimal():
    for cls in _dataclasses():
        for field, hint in typing.get_type_hints(cls).items():
            assert not _mentions(hint, Decimal), f"{cls.__name__}.{field}"
    for name in RETRIEVAL_MODULES:
        path = APP.joinpath(*name.split(".")[1:]).with_suffix(".py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            assert not (isinstance(node, ast.Name) and node.id == "Decimal"), f"{path.name} names Decimal"
            assert not (isinstance(node, ast.Attribute) and node.attr == "Decimal"), f"{path.name} names Decimal"


def test_the_chunk_table_has_no_float_or_numeric_column():
    for column in DocumentChunk.__table__.columns:
        assert not isinstance(column.type, (Float, Numeric)), column.name


# ---- embedding port purity ---------------------------------------------------------------------------------------------------


def test_the_port_imports_only_the_standard_library_and_domain():
    for node in ast.walk(ast.parse(PORT.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0, "the port uses a relative import"
            names = [node.module or ""]
        elif isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        else:
            continue
        for name in names:
            assert name.split(".")[0] in sys.stdlib_module_names or name == "app.domain" or name.startswith(
                "app.domain."), f"the port imports {name}"


def test_the_port_names_no_vendor_url_or_payload_detail():
    source = PORT.read_text(encoding="utf-8").lower()
    adapter_details = (ollama.MODEL_TAG, ollama.DOCUMENT_PREFIX, ollama.QUERY_PREFIX, ollama.DEFAULT_BASE_URL,
                       ollama.CONTEXT_LENGTH_ERROR, ollama.VERIFIED_MANIFEST_DIGEST.removeprefix("sha256:"), "truncate:")
    for word in VENDOR_WORDS + adapter_details:
        assert word.lower() not in source, f"the port mentions {word!r}"


def test_the_port_reports_provider_failures_as_values():
    """`embed` returns a batch or an `Unavailable`; the only exception the port itself raises is `RetrievalInputError`."""
    assert set(typing.get_args(typing.get_type_hints(Embedder.embed)["return"])) == {EmbeddingBatch, Unavailable}
    raises = [node for node in ast.walk(ast.parse(PORT.read_text(encoding="utf-8"))) if isinstance(node, ast.Raise)]
    assert raises
    for node in raises:
        assert isinstance(node.exc, ast.Call) and getattr(node.exc.func, "id", None) == RetrievalInputError.__name__, (
            f"line {node.lineno} raises something other than RetrievalInputError")
