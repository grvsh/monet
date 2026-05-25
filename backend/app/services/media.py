from __future__ import annotations

import mimetypes
import uuid
from pathlib import Path

MEDIA_EXTENSIONS: dict[str, set[str]] = {
    "image": {
        "jpg", "jpeg", "png", "webp", "tiff", "tif", "gif", "bmp",
        "heic", "heif",
        "cr2", "cr3", "nef", "nrw", "dng", "orf", "raf", "arw", "rw2", "pef", "srw",
    },
    "video": {
        "mp4", "mov", "mkv", "avi", "wmv", "flv", "webm", "m4v",
        "mpg", "mpeg", "3gp",
    },
    "audio": {
        "mp3", "flac", "wav", "aac", "m4a", "ogg", "wma", "aiff", "ape", "opus",
    },
}

RAW_EXTENSIONS: set[str] = {
    "cr2", "cr3", "nef", "nrw", "dng", "orf", "raf", "arw", "rw2", "pef", "srw",
}

# Extension-to-MIME fallbacks for types stdlib mimetypes may not know
_MIME_OVERRIDES: dict[str, str] = {
    "heic": "image/heic",
    "heif": "image/heif",
    "cr2": "image/x-canon-cr2",
    "cr3": "image/x-canon-cr3",
    "nef": "image/x-nikon-nef",
    "nrw": "image/x-nikon-nrw",
    "dng": "image/x-adobe-dng",
    "orf": "image/x-olympus-orf",
    "raf": "image/x-fuji-raf",
    "arw": "image/x-sony-arw",
    "rw2": "image/x-panasonic-rw2",
    "pef": "image/x-pentax-pef",
    "srw": "image/x-samsung-srw",
    "m4v": "video/x-m4v",
    "3gp": "video/3gpp",
    "opus": "audio/opus",
    "ape": "audio/x-ape",
    "aiff": "audio/aiff",
}


def get_media_type(path: str) -> tuple[str, str] | None:
    """Return (media_type, mime_type) for a media file, or None if not a known media format.

    Uses extension-only lookup — no disk I/O — so it is safe to call from the
    async event loop without blocking.
    """
    ext = Path(path).suffix.lower().lstrip(".")

    for media_type, exts in MEDIA_EXTENSIONS.items():
        if ext in exts:
            mime = (
                _MIME_OVERRIDES.get(ext)
                or mimetypes.guess_type(f"x.{ext}")[0]
                or "application/octet-stream"
            )
            return media_type, mime

    return None


def is_raw(ext: str) -> bool:
    """Return True if the file extension corresponds to a RAW image format."""
    return ext.lower() in RAW_EXTENSIONS


def thumbnail_cache_path(file_id: uuid.UUID, cache_dir: str) -> Path:
    """Return the full path for a thumbnail JPEG given the file UUID and cache directory.

    Uses a 2-level shard scheme: first 2 hex chars / next 2 hex chars / <uuid>.jpg
    """
    s = str(file_id).replace("-", "")
    return Path(cache_dir) / "thumbnails" / s[:2] / s[2:4] / f"{file_id}.jpg"


def preview_cache_path(file_id: uuid.UUID, cache_dir: str) -> Path:
    """Return the full path for a preview JPEG given the file UUID and cache directory."""
    s = str(file_id).replace("-", "")
    return Path(cache_dir) / "previews" / s[:2] / s[2:4] / f"{file_id}.jpg"
