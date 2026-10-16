from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.portable_types import ChunkUTCDateTime, Vector
from app.domain import limits
from app.domain.retrieval import EMBEDDING_DIMENSION
from app.models.base import Base

SHA256_HEX_LENGTH = 64


class DocumentChunk(Base):
    """Feature 009: one dated text chunk and its embedding (spec section 6). Append-only and user-scoped.

    `text` and `content_sha256` exclude the embedding role prefix. The `embedding` column is write-only: it is deferred with
    raiseload, so an accidental read raises instead of silently loading the vector.
    """

    __tablename__ = "document_chunks"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    source_id: Mapped[str] = mapped_column(String(limits.MAX_SOURCE_ID_LENGTH))
    chunk_index: Mapped[int] = mapped_column(Integer)  # PostgreSQL INTEGER: matches limits.MAX_CHUNK_INDEX
    text: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String(SHA256_HEX_LENGTH))
    published_at: Mapped[datetime] = mapped_column(ChunkUTCDateTime)
    recorded_at: Mapped[datetime] = mapped_column(ChunkUTCDateTime)
    embedding: Mapped[str] = mapped_column(Vector(EMBEDDING_DIMENSION), deferred=True, deferred_raiseload=True)
    embedding_model: Mapped[str] = mapped_column(String(limits.MAX_EMBEDDING_MODEL_LENGTH))
    embedding_config_id: Mapped[str] = mapped_column(String(SHA256_HEX_LENGTH))
    embedding_dimension: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        UniqueConstraint("user_id", "source_id", "chunk_index", name="uq_document_chunks_user_source_chunk"),
        CheckConstraint("chunk_index >= 0", name="chunk_index_non_negative"),
        CheckConstraint(f"embedding_dimension = {EMBEDDING_DIMENSION}", name="embedding_dimension"),
        CheckConstraint(f"length(content_sha256) = {SHA256_HEX_LENGTH}", name="content_sha256_length"),
        CheckConstraint(f"length(embedding_config_id) = {SHA256_HEX_LENGTH}", name="embedding_config_id_length"),
        Index("ix_document_chunks_user_published", "user_id", "published_at"),
    )
