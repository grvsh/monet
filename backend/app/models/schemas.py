from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

_VALID_ROLES = {"admin", "viewer"}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    full_name: str | None
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None
    allow_disk_deletion: bool = False
    face_cluster_min_size: int = 20


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


class UserCreate(BaseModel):
    email: str
    password: str
    full_name: str | None = None
    role: str = "viewer"

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in _VALID_ROLES:
            raise ValueError(f"role must be one of {_VALID_ROLES}")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("password must be at least 8 characters")
        return v


class UserUpdate(BaseModel):
    full_name: str | None = None
    role: str | None = None
    is_active: bool | None = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_ROLES:
            raise ValueError(f"role must be one of {_VALID_ROLES}")
        return v


# ---------------------------------------------------------------------------
# Root Folders
# ---------------------------------------------------------------------------


class RootFolderCreate(BaseModel):
    name: str
    path: str


class RootFolderUpdate(BaseModel):
    name: str | None = None
    path: str | None = None


class RootFolderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    path: str
    is_active: bool
    created_at: datetime
    last_scanned_at: datetime | None
    parent_root_id: UUID | None
    created_by: UUID | None = None


# ---------------------------------------------------------------------------
# Root Prefs
# ---------------------------------------------------------------------------


class RootPrefItem(BaseModel):
    root_folder_id: UUID
    is_visible: bool


class RootPrefsUpdateRequest(BaseModel):
    prefs: list[RootPrefItem]


class RootPrefsResponse(BaseModel):
    prefs: list[RootPrefItem]


# ---------------------------------------------------------------------------
# Filesystem Browse
# ---------------------------------------------------------------------------


class FsEntry(BaseModel):
    name: str
    path: str
    is_symlink: bool
    is_configured: bool


class FsBrowseResponse(BaseModel):
    path: str
    parent: str | None
    entries: list[FsEntry]
    path_is_configured: bool = False


# ---------------------------------------------------------------------------
# Folders
# ---------------------------------------------------------------------------


class FolderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    root_folder_id: UUID
    parent_id: UUID | None
    path: str
    name: str
    file_count: int
    child_folder_count: int
    indexed_at: datetime | None


# ---------------------------------------------------------------------------
# Files (gallery — lightweight)
# ---------------------------------------------------------------------------


class FileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    folder_id: UUID
    root_folder_id: UUID
    filename: str
    extension: str
    media_type: str
    mime_type: str
    is_raw: bool
    width: int | None
    height: int | None
    duration_sec: float | None
    taken_at: datetime | None
    camera_make: str | None
    camera_model: str | None
    has_gps: bool
    has_thumbnail: bool
    has_preview: bool
    size_bytes: int | None
    thumbnail_url: str
    preview_url: str
    lens_model: str | None
    location: str | None
    caption: str | None = None
    trashed_at: datetime | None = None
    missing_since: datetime | None = None


class FileDetailResponse(FileResponse):
    path: str
    focal_length_mm: float | None
    aperture: float | None
    shutter_speed: str | None
    iso: int | None
    gps_lat: float | None
    gps_lon: float | None
    gps_alt_m: float | None
    orientation: int | None
    indexed_at: datetime
    processed_at: datetime | None
    metadata: dict | None
    face_count: int | None = None
    clip_embedding: bool = False
    dino_embedding: bool = False
    ai_analyzed_at: datetime | None = None
    ai_versions: dict | None = None
    ml_error: str | None = None


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


class PaginatedFiles(BaseModel):
    items: list[FileResponse]
    total: int
    page: int
    page_size: int
    pages: int


class FolderTypeCounts(BaseModel):
    image: int
    video: int
    audio: int


# ---------------------------------------------------------------------------
# Albums
# ---------------------------------------------------------------------------


class AlbumResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    owner_id: UUID
    file_count: int
    cover_url: str | None
    created_at: datetime
    updated_at: datetime


class CreateAlbumRequest(BaseModel):
    name: str


class RenameAlbumRequest(BaseModel):
    name: str


class AlbumFilesRequest(BaseModel):
    file_ids: list[UUID]


# ---------------------------------------------------------------------------
# Scan Jobs
# ---------------------------------------------------------------------------


class ScanJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    root_folder_id: UUID | None
    trigger_type: str
    status: str
    folders_found: int
    folders_scanned: int
    files_found: int
    files_new: int
    files_updated: int
    files_deleted: int
    files_skipped: int
    files_failed: int
    ml_files_pending: int = 0
    ml_files_done: int = 0
    ml_files_failed: int = 0
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None


class ScanStatusResponse(BaseModel):
    jobs: list[ScanJobResponse]


class FailedFileInfo(BaseModel):
    id: UUID
    path: str
    error: str


class ProcessingStatusResponse(BaseModel):
    total: int
    processed: int
    pending: int
    failed: int
    failed_files: list[FailedFileInfo]
    ml_total: int = 0
    ml_done: int = 0
    ml_pending: int = 0
    ml_failed: int = 0
    ml_failed_files: list[FailedFileInfo] = []
    caption_pending: int = 0
    caption_done: int = 0


class ScanRequest(BaseModel):
    root_folder_id: UUID | None = None


class ScanEnqueueResponse(BaseModel):
    scan_job_ids: list[UUID]
    message: str


# ---------------------------------------------------------------------------
# Faces / People
# ---------------------------------------------------------------------------


class PersonResponse(BaseModel):
    id: UUID
    name: str | None
    face_count: int
    sample_thumbnail_urls: list[str]


class PeopleListResponse(BaseModel):
    people: list[PersonResponse]


class PersonUpdateRequest(BaseModel):
    name: str | None = None


class MergePeopleRequest(BaseModel):
    source_id: UUID
    target_id: UUID
