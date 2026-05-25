"""Initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-25 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgcrypto for gen_random_uuid()
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # ------------------------------------------------------------------
    # users
    # ------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("email", sa.Text(), unique=True, nullable=False),
        sa.Column("hashed_password", sa.Text(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=True),
        sa.Column("role", sa.Text(), nullable=False, server_default=sa.text("'viewer'")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ------------------------------------------------------------------
    # root_folders
    # ------------------------------------------------------------------
    op.create_table(
        "root_folders",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), unique=True, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("last_scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "parent_root_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("root_folders.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # ------------------------------------------------------------------
    # user_root_prefs
    # ------------------------------------------------------------------
    op.create_table(
        "user_root_prefs",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "root_folder_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("root_folders.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("is_visible", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )

    # ------------------------------------------------------------------
    # folders
    # ------------------------------------------------------------------
    op.create_table(
        "folders",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "root_folder_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("root_folders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("folders.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("file_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("child_folder_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("root_folder_id", "path", name="uq_folders_root_path"),
    )
    op.create_index("idx_folders_root", "folders", ["root_folder_id"])
    op.create_index("idx_folders_parent", "folders", ["parent_id"])
    op.create_index(
        "idx_folders_path",
        "folders",
        ["path"],
        postgresql_ops={"path": "text_pattern_ops"},
    )

    # ------------------------------------------------------------------
    # media_files
    # ------------------------------------------------------------------
    op.create_table(
        "media_files",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "folder_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("folders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "root_folder_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("root_folders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Filesystem
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("extension", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("mtime", sa.DateTime(timezone=True), nullable=True),
        # Classification
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("is_raw", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        # Dimensions
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("orientation", sa.SmallInteger(), nullable=True),
        sa.Column("duration_sec", sa.Float(), nullable=True),
        # Denormalized EXIF
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("camera_make", sa.Text(), nullable=True),
        sa.Column("camera_model", sa.Text(), nullable=True),
        sa.Column("lens_model", sa.Text(), nullable=True),
        sa.Column("focal_length_mm", sa.Float(), nullable=True),
        sa.Column("aperture", sa.Float(), nullable=True),
        sa.Column("shutter_speed", sa.Text(), nullable=True),
        sa.Column("iso", sa.Integer(), nullable=True),
        sa.Column("gps_lat", sa.Float(precision=53), nullable=True),
        sa.Column("gps_lon", sa.Float(precision=53), nullable=True),
        sa.Column("gps_alt_m", sa.Float(), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        # Generated assets
        sa.Column("thumbnail_path", sa.Text(), nullable=True),
        sa.Column("preview_path", sa.Text(), nullable=True),
        # Lifecycle
        sa.Column(
            "indexed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_error", sa.Text(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("missing_since", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("root_folder_id", "path", name="uq_media_files_root_path"),
    )
    op.create_index("idx_files_folder", "media_files", ["folder_id"])
    op.create_index("idx_files_root", "media_files", ["root_folder_id"])
    op.create_index("idx_files_taken_at", "media_files", ["taken_at"])
    op.create_index("idx_files_type", "media_files", ["media_type"])
    op.create_index("idx_files_camera", "media_files", ["camera_make", "camera_model"])
    op.create_index(
        "idx_files_deleted",
        "media_files",
        ["is_deleted"],
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        "idx_files_pending",
        "media_files",
        ["processed_at"],
        postgresql_where=sa.text("processed_at IS NULL"),
    )

    # ------------------------------------------------------------------
    # file_metadata
    # ------------------------------------------------------------------
    op.create_table(
        "file_metadata",
        sa.Column(
            "file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("media_files.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("data", postgresql.JSONB(), nullable=False),
    )
    op.create_index("idx_metadata_gin", "file_metadata", ["data"], postgresql_using="gin")

    # ------------------------------------------------------------------
    # scan_jobs
    # ------------------------------------------------------------------
    op.create_table(
        "scan_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "root_folder_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("root_folders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "triggered_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("trigger_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'running'")),
        sa.Column("folders_found", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("folders_scanned", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("files_found", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("files_new", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("files_updated", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("files_deleted", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("files_skipped", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("files_failed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("pending_folders", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_scan_jobs_root", "scan_jobs", ["root_folder_id"])
    op.create_index("idx_scan_jobs_status", "scan_jobs", ["status"])


def downgrade() -> None:
    op.drop_table("scan_jobs")
    op.drop_table("file_metadata")
    op.drop_table("media_files")
    op.drop_table("folders")
    op.drop_table("user_root_prefs")
    op.drop_table("root_folders")
    op.drop_table("users")
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
