"""Add AI/ML features: embeddings, captions, faces, people, ML scan counters

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-30 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector extension (idempotent)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── media_files: AI columns ───────────────────────────────────────────────
    op.add_column("media_files", sa.Column("clip_embedding", sa.Text(), nullable=True))
    op.add_column("media_files", sa.Column("dino_embedding", sa.Text(), nullable=True))
    op.add_column("media_files", sa.Column("caption", sa.Text(), nullable=True))
    op.add_column("media_files", sa.Column("ai_objects", postgresql.JSONB(), nullable=True))
    op.add_column("media_files", sa.Column("aesthetic_score", sa.Float(), nullable=True))
    op.add_column("media_files", sa.Column("ai_versions", postgresql.JSONB(), nullable=True))
    op.add_column("media_files", sa.Column("ai_analyzed_at", sa.DateTime(timezone=True), nullable=True))

    # Convert text placeholder columns to proper vector types.
    # We add as Text first so Alembic doesn't complain about unknown types,
    # then ALTER to the vector type immediately after.
    op.execute("ALTER TABLE media_files ALTER COLUMN clip_embedding TYPE vector(1024) USING clip_embedding::vector(1024)")
    op.execute("ALTER TABLE media_files ALTER COLUMN dino_embedding TYPE vector(1536) USING dino_embedding::vector(1536)")

    # Full-text search index on captions
    op.execute("""
        CREATE INDEX idx_files_caption_fts
        ON media_files
        USING gin(to_tsvector('english', coalesce(caption, '')))
    """)

    # HNSW vector indexes (cosine similarity)
    op.execute("""
        CREATE INDEX idx_files_clip_embedding
        ON media_files
        USING hnsw (clip_embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)
    op.execute("""
        CREATE INDEX idx_files_dino_embedding
        ON media_files
        USING hnsw (dino_embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)

    # GIN index for ai_versions JSONB (enables staleness queries per feature)
    op.create_index("idx_files_ai_versions", "media_files", ["ai_versions"], postgresql_using="gin")

    # ── scan_jobs: ML progress counters ──────────────────────────────────────
    op.add_column("scan_jobs", sa.Column(
        "ml_files_pending", sa.Integer(), nullable=False, server_default=sa.text("0")
    ))
    op.add_column("scan_jobs", sa.Column(
        "ml_files_done", sa.Integer(), nullable=False, server_default=sa.text("0")
    ))
    op.add_column("scan_jobs", sa.Column(
        "ml_files_failed", sa.Integer(), nullable=False, server_default=sa.text("0")
    ))

    # ── albums: auto-generated album support ─────────────────────────────────
    op.add_column("albums", sa.Column(
        "is_auto", sa.Boolean(), nullable=False, server_default=sa.text("false")
    ))
    op.add_column("albums", sa.Column("auto_type", sa.Text(), nullable=True))
    op.create_index(
        "idx_albums_auto", "albums", ["is_auto"],
        postgresql_where=sa.text("is_auto = true"),
    )

    # ── people table ─────────────────────────────────────────────────────────
    op.create_table(
        "people",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column(
            "cover_face_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # ── face_detections table ────────────────────────────────────────────────
    op.create_table(
        "face_detections",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("media_files.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("bbox", postgresql.JSONB(), nullable=False),
        sa.Column("embedding", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "person_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("people.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # Convert face embedding to vector(512)
    op.execute("ALTER TABLE face_detections ALTER COLUMN embedding TYPE vector(512) USING embedding::vector(512)")

    # HNSW index on face embeddings for similarity search
    op.execute("""
        CREATE INDEX idx_face_detections_embedding
        ON face_detections
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)

    op.create_index("idx_faces_file", "face_detections", ["file_id"])
    op.create_index("idx_faces_person", "face_detections", ["person_id"])

    # Add FK from people.cover_face_id → face_detections.id (deferred to avoid
    # circular dependency during table creation above)
    op.create_foreign_key(
        "fk_people_cover_face",
        "people", "face_detections",
        ["cover_face_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_people_cover_face", "people", type_="foreignkey")
    op.drop_index("idx_faces_person", "face_detections")
    op.drop_index("idx_faces_file", "face_detections")
    op.drop_table("face_detections")
    op.drop_table("people")

    op.drop_index("idx_albums_auto", "albums")
    op.drop_column("albums", "auto_type")
    op.drop_column("albums", "is_auto")

    op.drop_column("scan_jobs", "ml_files_failed")
    op.drop_column("scan_jobs", "ml_files_done")
    op.drop_column("scan_jobs", "ml_files_pending")

    op.drop_index("idx_files_ai_versions", "media_files")
    op.drop_index("idx_files_dino_embedding", "media_files")
    op.drop_index("idx_files_clip_embedding", "media_files")
    op.drop_index("idx_files_caption_fts", "media_files")
    op.drop_column("media_files", "ai_analyzed_at")
    op.drop_column("media_files", "ai_versions")
    op.drop_column("media_files", "aesthetic_score")
    op.drop_column("media_files", "ai_objects")
    op.drop_column("media_files", "caption")
    op.drop_column("media_files", "dino_embedding")
    op.drop_column("media_files", "clip_embedding")
