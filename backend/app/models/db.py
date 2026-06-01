from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy import DateTime
from sqlalchemy.dialects.postgresql import JSONB, UUID

TIMESTAMPTZ = DateTime(timezone=True)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'viewer'")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=text("now()")
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ, nullable=True)
    allow_disk_deletion: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    face_cluster_min_size: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("20")
    )

    # Relationships
    root_prefs: Mapped[list[UserRootPref]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    created_root_folders: Mapped[list[RootFolder]] = relationship(
        back_populates="creator", foreign_keys="RootFolder.created_by"
    )
    triggered_scan_jobs: Mapped[list[ScanJob]] = relationship(
        back_populates="trigger_user", foreign_keys="ScanJob.triggered_by"
    )


class RootFolder(Base):
    __tablename__ = "root_folders"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=text("now()")
    )
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_scanned_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ, nullable=True)
    parent_root_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("root_folders.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    creator: Mapped[Optional[User]] = relationship(
        back_populates="created_root_folders", foreign_keys=[created_by]
    )
    user_prefs: Mapped[list[UserRootPref]] = relationship(
        back_populates="root_folder", cascade="all, delete-orphan"
    )
    folders: Mapped[list[Folder]] = relationship(
        back_populates="root_folder", cascade="all, delete-orphan"
    )
    media_files: Mapped[list[MediaFile]] = relationship(
        back_populates="root_folder", cascade="all, delete-orphan"
    )
    scan_jobs: Mapped[list[ScanJob]] = relationship(
        back_populates="root_folder", foreign_keys="ScanJob.root_folder_id"
    )


class UserRootPref(Base):
    __tablename__ = "user_root_prefs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    root_folder_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("root_folders.id", ondelete="CASCADE"),
        primary_key=True,
    )
    is_visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )

    # Relationships
    user: Mapped[User] = relationship(back_populates="root_prefs")
    root_folder: Mapped[RootFolder] = relationship(back_populates="user_prefs")


class Folder(Base):
    __tablename__ = "folders"
    __table_args__ = (
        UniqueConstraint("root_folder_id", "path", name="uq_folders_root_path"),
        Index("idx_folders_root", "root_folder_id"),
        Index("idx_folders_parent", "parent_id"),
        Index(
            "idx_folders_path",
            "path",
            postgresql_ops={"path": "text_pattern_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    root_folder_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("root_folders.id", ondelete="CASCADE"),
        nullable=False,
    )
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("folders.id", ondelete="CASCADE"),
        nullable=True,
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    file_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    child_folder_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    indexed_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ, nullable=True)

    # Relationships
    root_folder: Mapped[RootFolder] = relationship(back_populates="folders")
    parent: Mapped[Optional[Folder]] = relationship(
        "Folder",
        back_populates="children",
        primaryjoin="Folder.parent_id == Folder.id",
        foreign_keys="[Folder.parent_id]",
        remote_side="[Folder.id]",
    )
    children: Mapped[list[Folder]] = relationship(
        "Folder",
        back_populates="parent",
        primaryjoin="Folder.parent_id == Folder.id",
        foreign_keys="[Folder.parent_id]",
        cascade="all, delete-orphan",
    )
    media_files: Mapped[list[MediaFile]] = relationship(
        back_populates="folder", cascade="all, delete-orphan"
    )


class MediaFile(Base):
    __tablename__ = "media_files"
    __table_args__ = (
        UniqueConstraint("root_folder_id", "path", name="uq_media_files_root_path"),
        Index("idx_files_folder", "folder_id"),
        Index("idx_files_root", "root_folder_id"),
        Index("idx_files_taken_at", "taken_at"),
        Index("idx_files_type", "media_type"),
        Index("idx_files_camera", "camera_make", "camera_model"),
        Index(
            "idx_files_deleted",
            "is_deleted",
            postgresql_where=text("is_deleted = false"),
        ),
        Index(
            "idx_files_pending",
            "processed_at",
            postgresql_where=text("processed_at IS NULL"),
        ),
    )

    # Identity
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    folder_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("folders.id", ondelete="CASCADE"),
        nullable=False,
    )
    root_folder_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("root_folders.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Filesystem
    path: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    extension: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    mtime: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ, nullable=True)

    # Classification
    media_type: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    is_raw: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    # Dimensions
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    orientation: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    duration_sec: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Denormalized EXIF
    taken_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ, nullable=True)
    camera_make: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    camera_model: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    lens_model: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    focal_length_mm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    aperture: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    shutter_speed: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    iso: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    gps_lat: Mapped[Optional[float]] = mapped_column(
        Float(precision=53), nullable=True  # DOUBLE PRECISION
    )
    gps_lon: Mapped[Optional[float]] = mapped_column(
        Float(precision=53), nullable=True  # DOUBLE PRECISION
    )
    gps_alt_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    location: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Generated assets
    thumbnail_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    preview_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # AI / ML features
    clip_embedding: Mapped[Optional[list[float]]] = mapped_column(Vector(1024), nullable=True)
    dino_embedding: Mapped[Optional[list[float]]] = mapped_column(Vector(1536), nullable=True)
    caption: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_objects: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    aesthetic_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Keys are feature names, values are model version strings used to produce them.
    # Null means this file has never been through ML analysis.
    ai_versions: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    ai_analyzed_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ, nullable=True)

    # Lifecycle
    indexed_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=text("now()")
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ, nullable=True)
    processing_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ml_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ, nullable=True)
    # Set by the scanner when a file disappears from disk but was NOT user-trashed.
    # Cleared when the file is found again on disk.
    missing_since: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ, nullable=True)

    # Relationships
    folder: Mapped[Folder] = relationship(back_populates="media_files")
    root_folder: Mapped[RootFolder] = relationship(back_populates="media_files")
    metadata_entry: Mapped[Optional[FileMetadata]] = relationship(
        back_populates="media_file", cascade="all, delete-orphan", uselist=False
    )
    face_detections: Mapped[list[FaceDetection]] = relationship(
        back_populates="media_file", cascade="all, delete-orphan"
    )


class Album(Base):
    __tablename__ = "albums"
    __table_args__ = (
        Index("idx_albums_owner", "owner_id"),
        Index("idx_albums_auto", "is_auto", postgresql_where=text("is_auto = true")),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # Auto-generated albums (events, best-of sets). is_auto=True albums are managed
    # by the ML worker and may be recreated on rescan.
    is_auto: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # 'event' | 'best_of' | None
    auto_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=text("now()")
    )

    # Relationships
    owner: Mapped[User] = relationship("User")
    items: Mapped[list[AlbumFile]] = relationship(
        back_populates="album", cascade="all, delete-orphan",
        order_by="AlbumFile.position, AlbumFile.added_at",
    )


class AlbumFile(Base):
    __tablename__ = "album_files"
    __table_args__ = (
        Index("idx_album_files_album", "album_id"),
        Index("idx_album_files_file", "file_id"),
    )

    album_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("albums.id", ondelete="CASCADE"),
        primary_key=True,
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("media_files.id", ondelete="CASCADE"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    added_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=text("now()")
    )

    # Relationships
    album: Mapped[Album] = relationship(back_populates="items")
    file: Mapped[MediaFile] = relationship("MediaFile")


class FileMetadata(Base):
    __tablename__ = "file_metadata"
    __table_args__ = (
        Index("idx_metadata_gin", "data", postgresql_using="gin"),
    )

    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("media_files.id", ondelete="CASCADE"),
        primary_key=True,
    )
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Relationships
    media_file: Mapped[MediaFile] = relationship(back_populates="metadata_entry")


class ScanJob(Base):
    __tablename__ = "scan_jobs"
    __table_args__ = (
        Index("idx_scan_jobs_root", "root_folder_id"),
        Index("idx_scan_jobs_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    root_folder_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("root_folders.id", ondelete="SET NULL"),
        nullable=True,
    )
    triggered_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    trigger_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'running'")
    )

    folders_found: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    folders_scanned: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    files_found: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    files_new: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    files_updated: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    files_deleted: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    files_skipped: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    files_failed: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    pending_folders: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    # ML analysis progress — tracked separately from asset processing.
    ml_files_pending: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    ml_files_done: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    ml_files_failed: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=text("now()")
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ, nullable=True)

    # Relationships
    root_folder: Mapped[Optional[RootFolder]] = relationship(
        back_populates="scan_jobs", foreign_keys=[root_folder_id]
    )
    trigger_user: Mapped[Optional[User]] = relationship(
        back_populates="triggered_scan_jobs", foreign_keys=[triggered_by]
    )


class Person(Base):
    """A named identity built from clustered face embeddings."""
    __tablename__ = "people"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cover_face_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("face_detections.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Mean of all member face embeddings (L2-normalised). Used to match
    # clusters to existing persons across re-clustering runs so names are stable.
    centroid: Mapped[Optional[list[float]]] = mapped_column(Vector(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=text("now()")
    )

    # Relationships
    faces: Mapped[list[FaceDetection]] = relationship(
        back_populates="person",
        foreign_keys="FaceDetection.person_id",
    )


class FaceDetection(Base):
    """One detected face within a media file."""
    __tablename__ = "face_detections"
    __table_args__ = (
        Index("idx_faces_file", "file_id"),
        Index("idx_faces_person", "person_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("media_files.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Bounding box in original image pixel coordinates: {x, y, w, h}
    bbox: Mapped[dict] = mapped_column(JSONB, nullable=False)
    embedding: Mapped[Optional[list[float]]] = mapped_column(Vector(512), nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Assigned after clustering — null until a person identity is resolved.
    person_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("people.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    media_file: Mapped[MediaFile] = relationship(back_populates="face_detections")
    person: Mapped[Optional[Person]] = relationship(
        back_populates="faces",
        foreign_keys=[person_id],
    )
