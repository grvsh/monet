from app.models.db import MediaFile
from app.models.schemas import FileResponse


def file_to_response(f: MediaFile, face_bbox: dict | None = None, face_detection_id: str | None = None) -> FileResponse:
    return FileResponse(
        id=f.id,
        folder_id=f.folder_id,
        root_folder_id=f.root_folder_id,
        filename=f.filename,
        extension=f.extension,
        media_type=f.media_type,
        mime_type=f.mime_type,
        is_raw=f.is_raw,
        width=f.width,
        height=f.height,
        duration_sec=f.duration_sec,
        taken_at=f.taken_at,
        camera_make=f.camera_make,
        camera_model=f.camera_model,
        has_gps=f.gps_lat is not None,
        has_thumbnail=f.thumbnail_path is not None,
        has_preview=f.preview_path is not None,
        size_bytes=f.size_bytes,
        thumbnail_url=f"/api/thumbnails/{f.id}",
        preview_url=f"/api/previews/{f.id}",
        lens_model=f.lens_model,
        location=f.location,
        caption=f.caption,
        trashed_at=f.deleted_at,
        missing_since=f.missing_since,
        face_bbox=face_bbox,
        face_detection_id=face_detection_id,
    )
