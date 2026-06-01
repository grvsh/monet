from __future__ import annotations

import asyncio
import io
import os
import tempfile
from pathlib import Path

import ffmpeg
from PIL import Image, ImageOps

_RAW_EXTENSIONS = {"cr2", "cr3", "nef", "nrw", "dng", "orf", "raf", "arw", "rw2", "pef", "srw"}
_HEIF_EXTENSIONS = {"heic", "heif"}


async def generate_thumbnail_and_preview(
    abs_path: str,
    media_type: str,
    extension: str,
    thumb_path: Path,
    preview_path: Path,
    thumb_size: int,
    preview_max_w: int,
    preview_max_h: int,
    thumb_quality: int,
    preview_quality: int,
) -> tuple[int | None, int | None]:
    """Generate thumbnail and preview for a media file.

    Returns (width, height) of the original, or (None, None) for audio.
    Runs the blocking I/O work in a thread pool executor.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        _process_sync,
        abs_path,
        media_type,
        extension,
        thumb_path,
        preview_path,
        thumb_size,
        preview_max_w,
        preview_max_h,
        thumb_quality,
        preview_quality,
    )


def _process_sync(
    abs_path: str,
    media_type: str,
    extension: str,
    thumb_path: Path,
    preview_path: Path,
    thumb_size: int,
    preview_max_w: int,
    preview_max_h: int,
    thumb_quality: int,
    preview_quality: int,
) -> tuple[int | None, int | None]:
    """Synchronous dispatch by media type."""
    thumb_path.parent.mkdir(parents=True, exist_ok=True)
    preview_path.parent.mkdir(parents=True, exist_ok=True)

    if media_type == "image":
        return _process_image(
            abs_path,
            extension,
            thumb_path,
            preview_path,
            thumb_size,
            preview_max_w,
            preview_max_h,
            thumb_quality,
            preview_quality,
        )
    elif media_type == "video":
        return _process_video(
            abs_path,
            thumb_path,
            preview_path,
            thumb_size,
            preview_max_w,
            preview_max_h,
            thumb_quality,
            preview_quality,
        )
    elif media_type == "audio":
        _process_audio(abs_path, thumb_path, thumb_size, thumb_quality)
        return None, None
    else:
        return None, None


def _open_as_pil(abs_path: str, extension: str) -> Image.Image:
    """Open a media file as a PIL Image, handling special formats."""
    ext = extension.lower()

    if ext in _HEIF_EXTENSIONS:
        from pillow_heif import register_heif_opener
        register_heif_opener()
        return Image.open(abs_path)

    if ext in _RAW_EXTENSIONS:
        import rawpy
        import numpy as np

        with rawpy.imread(abs_path) as raw:
            rgb = raw.postprocess(
                use_camera_wb=True,
                half_size=False,
                output_color=rawpy.ColorSpace.sRGB,
                output_bps=8,
            )
        return Image.fromarray(rgb)

    return Image.open(abs_path)


def _to_srgb(img: Image.Image) -> Image.Image:
    """Apply EXIF orientation and convert to RGB (compositing over white for RGBA)."""
    img = ImageOps.exif_transpose(img)

    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        return bg

    if img.mode not in ("RGB",):
        img = img.convert("RGB")

    return img


def _save_thumb(img: Image.Image, thumb_path: Path, thumb_size: int, quality: int) -> None:
    """Save a thumbnail: longest side = thumb_size, JPEG."""
    thumb_path.parent.mkdir(parents=True, exist_ok=True)
    t = img.copy()
    t.thumbnail((thumb_size, thumb_size), Image.LANCZOS)
    t.save(str(thumb_path), "JPEG", quality=quality, optimize=True)


def _save_preview(
    img: Image.Image,
    preview_path: Path,
    max_w: int,
    max_h: int,
    quality: int,
) -> None:
    """Save a preview: fits within max_w × max_h, JPEG, aspect preserved."""
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    p = img.copy()
    p.thumbnail((max_w, max_h), Image.LANCZOS)
    p.save(str(preview_path), "JPEG", quality=quality, optimize=True)


def _process_image(
    abs_path: str,
    extension: str,
    thumb_path: Path,
    preview_path: Path,
    thumb_size: int,
    max_w: int,
    max_h: int,
    thumb_quality: int,
    preview_quality: int,
) -> tuple[int | None, int | None]:
    """Process a still image: open, convert, write thumbnail + preview."""
    img = _open_as_pil(abs_path, extension)
    orig_w, orig_h = img.size
    img = _to_srgb(img)
    _save_thumb(img, thumb_path, thumb_size, thumb_quality)
    _save_preview(img, preview_path, max_w, max_h, preview_quality)
    return orig_w, orig_h


def _process_video(
    abs_path: str,
    thumb_path: Path,
    preview_path: Path,
    thumb_size: int,
    max_w: int,
    max_h: int,
    thumb_quality: int,
    preview_quality: int,
) -> tuple[int | None, int | None]:
    """Process a video: extract frame at 10% duration, write thumbnail + preview."""
    probe = ffmpeg.probe(abs_path)
    video_stream = next(
        (s for s in probe["streams"] if s["codec_type"] == "video"), None
    )
    duration = float(probe["format"].get("duration", 0))
    t = max(duration * 0.1, 0)

    orig_w: int | None = int(video_stream["width"]) if video_stream else None
    orig_h: int | None = int(video_stream["height"]) if video_stream else None

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        (
            ffmpeg.input(abs_path, ss=t)
            .output(tmp_path, vframes=1, format="image2", vcodec="mjpeg")
            .overwrite_output()
            .run(quiet=True)
        )
        img = Image.open(tmp_path).convert("RGB")
        _save_thumb(img, thumb_path, thumb_size, thumb_quality)
        _save_preview(img, preview_path, max_w, max_h, preview_quality)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    return orig_w, orig_h


async def generate_video_preview(
    abs_src: str,
    abs_dst: Path,
    crf: int = 21,
    preset: str = "slow",
) -> None:
    """Transcode a video to a web-optimised 1080p H.264/AAC MP4 next to the original.

    Skips silently if the destination already exists (idempotent).
    Runs the blocking ffmpeg call in a thread-pool executor.
    """
    if abs_dst.exists():
        return
    abs_dst.parent.mkdir(parents=True, exist_ok=True)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _transcode_video, abs_src, abs_dst, crf, preset)


def _transcode_video(abs_src: str, abs_dst: Path, crf: int, preset: str) -> None:
    tmp = abs_dst.with_suffix(".tmp.mp4")
    try:
        (
            ffmpeg.input(abs_src)
            .output(
                str(tmp),
                vcodec="libx264",
                crf=crf,
                preset=preset,
                vf="scale=1920:1080:flags=lanczos",
                acodec="aac",
                audio_bitrate="192k",
                movflags="+faststart",
            )
            .overwrite_output()
            .run(quiet=True)
        )
        tmp.rename(abs_dst)
    except Exception:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise


def _process_audio(
    abs_path: str,
    thumb_path: Path,
    thumb_size: int,
    quality: int,
) -> None:
    """For audio: extract embedded cover art if available, otherwise write a placeholder."""
    img_data: bytes | None = None
    path_lower = abs_path.lower()

    try:
        if path_lower.endswith(".mp3"):
            from mutagen.id3 import APIC, ID3
            try:
                tags = ID3(abs_path)
                for tag in tags.values():
                    if isinstance(tag, APIC):
                        img_data = tag.data
                        break
            except Exception:
                pass

        elif path_lower.endswith((".m4a", ".aac", ".mp4")):
            from mutagen.mp4 import MP4
            try:
                tags = MP4(abs_path)
                covers = tags.get("covr", [])
                if covers:
                    img_data = bytes(covers[0])
            except Exception:
                pass

        elif path_lower.endswith(".flac"):
            from mutagen.flac import FLAC
            try:
                tags = FLAC(abs_path)
                if tags.pictures:
                    img_data = tags.pictures[0].data
            except Exception:
                pass

        elif path_lower.endswith(".ogg"):
            from mutagen.oggvorbis import OggVorbis
            try:
                tags = OggVorbis(abs_path)
                # OGG metadata covers are in a different format; skip for now
            except Exception:
                pass

    except ImportError:
        pass  # mutagen not installed

    if img_data:
        try:
            img = Image.open(io.BytesIO(img_data)).convert("RGB")
            _save_thumb(img, thumb_path, thumb_size, quality)
            return
        except Exception:
            pass

    # Fallback: solid colour placeholder
    placeholder = Image.new("RGB", (thumb_size, thumb_size), (40, 40, 60))
    placeholder.save(str(thumb_path), "JPEG", quality=quality)
