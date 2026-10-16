"""document_chunks for Feature 009 (RAG date-cutoff)

Revision ID: 0003
Revises: 0002

PostgreSQL (authoritative): requires the pre-existing `vector` extension, checked before anything is created; it never
creates or drops the extension. A missing extension raises VectorExtensionMissingError (message VECTOR_EXTENSION_MISSING).
Offline `--sql` rendering cannot see the database, so it renders DDL only and claims nothing about the extension.
SQLite (test-only): the vector column is TEXT and no extension is required.
No vector index: search and audit use an exact cosine scan (spec section 6). Downgrade drops only this revision's objects.
"""
import sqlalchemy as sa
from alembic import context, op

from app.db.portable_types import Vector
from app.domain.retrieval import VectorExtensionMissingError

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

# Frozen with this revision; tests/test_chunk_migration.py asserts they agree with the model and app.domain.limits.
DIMENSION = 768
SOURCE_ID_LENGTH = 256
EMBEDDING_MODEL_LENGTH = 128
SHA256_HEX_LENGTH = 64


def _require_vector_extension() -> None:
    if context.is_offline_mode():
        return  # rendering only: there is no database to inspect
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # SQLite is test-only and stores the vector as TEXT
    if bind.execute(sa.text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")).first() is None:
        raise VectorExtensionMissingError()


def upgrade() -> None:
    _require_vector_extension()
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.String(SOURCE_ID_LENGTH), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(SHA256_HEX_LENGTH), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("embedding", Vector(DIMENSION), nullable=False),
        sa.Column("embedding_model", sa.String(EMBEDDING_MODEL_LENGTH), nullable=False),
        sa.Column("embedding_config_id", sa.String(SHA256_HEX_LENGTH), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_document_chunks"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_document_chunks_user_id_users"),
        sa.UniqueConstraint("user_id", "source_id", "chunk_index", name="uq_document_chunks_user_source_chunk"),
        sa.CheckConstraint("chunk_index >= 0", name="chunk_index_non_negative"),
        sa.CheckConstraint(f"embedding_dimension = {DIMENSION}", name="embedding_dimension"),
        sa.CheckConstraint(f"length(content_sha256) = {SHA256_HEX_LENGTH}", name="content_sha256_length"),
        sa.CheckConstraint(f"length(embedding_config_id) = {SHA256_HEX_LENGTH}", name="embedding_config_id_length"),
    )
    op.create_index("ix_document_chunks_user_published", "document_chunks", ["user_id", "published_at"])


def downgrade() -> None:
    op.drop_index("ix_document_chunks_user_published", table_name="document_chunks")
    op.drop_table("document_chunks")
