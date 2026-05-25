from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import exiftool

# Serialises all concurrent calls to a shared ExifToolHelper.
# ExifTool communicates over a stdin/stdout pipe; concurrent writes from
# multiple threads garble the protocol and cause hangs.
_exiftool_lock = threading.Lock()


async def extract_metadata(file_path: str, et: exiftool.ExifToolHelper | None = None) -> dict:
    """Run ExifTool on a file and return the parsed metadata as a dict.

    If a persistent ExifToolHelper instance is provided it is reused (fast path,
    serialised via _exiftool_lock so concurrent workers don't corrupt the pipe).
    Otherwise a temporary process is spawned per call (safe fallback).
    Uses run_in_executor to avoid blocking the async event loop.
    """
    loop = asyncio.get_event_loop()

    if et is not None:
        def _run_shared() -> dict:
            with _exiftool_lock:
                results = et.get_metadata([file_path])
                return results[0] if results else {}
        return await loop.run_in_executor(None, _run_shared)

    def _run() -> dict:
        with exiftool.ExifToolHelper() as _et:
            results = _et.get_metadata([file_path])
            return results[0] if results else {}

    return await loop.run_in_executor(None, _run)


def parse_denormalized(meta: dict) -> dict:
    """Extract the key fields we store directly on media_files from an ExifTool dict.

    Returns a dict with keys matching the MediaFile columns. Values may be None
    if the tag was not present in the metadata.
    """

    def get(*keys: str) -> Any:
        for k in keys:
            v = meta.get(k)
            if v is not None:
                return v
        return None

    def safe_float(v: Any) -> float | None:
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def safe_int(v: Any) -> int | None:
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    # Parse taken_at from EXIF date strings (format: "YYYY:MM:DD HH:MM:SS")
    taken_at_str = get("EXIF:DateTimeOriginal", "EXIF:CreateDate", "File:FileModifyDate")
    taken_at: datetime | None = None
    if taken_at_str:
        # Normalize: take the first 19 chars, which is "YYYY:MM:DD HH:MM:SS"
        raw = str(taken_at_str)[:19]
        for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                taken_at = datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
                break
            except ValueError:
                continue

    # ExposureTime may be a float like 0.004 — convert to fractional string
    exposure_raw = get("EXIF:ExposureTime")
    shutter_speed: str | None = None
    if exposure_raw is not None:
        try:
            ev = float(exposure_raw)
            if ev > 0 and ev < 1:
                # e.g. 0.004 → "1/250"
                denominator = round(1 / ev)
                shutter_speed = f"1/{denominator}"
            else:
                shutter_speed = str(exposure_raw)
        except (TypeError, ValueError):
            shutter_speed = str(exposure_raw) if exposure_raw else None

    return {
        "taken_at": taken_at,
        "camera_make": get("EXIF:Make"),
        "camera_model": get("EXIF:Model"),
        "lens_model": get("EXIF:LensModel"),
        "focal_length_mm": safe_float(get("EXIF:FocalLength")),
        "aperture": safe_float(get("EXIF:FNumber")),
        "shutter_speed": shutter_speed,
        "iso": safe_int(get("EXIF:ISO")),
        "gps_lat": safe_float(get("GPS:GPSLatitude", "Composite:GPSLatitude")),
        "gps_lon": safe_float(get("GPS:GPSLongitude", "Composite:GPSLongitude")),
        "gps_alt_m": safe_float(get("GPS:GPSAltitude")),
        "width": safe_int(
            get("EXIF:ImageWidth", "File:ImageWidth", "PNG:ImageWidth", "EXIF:ExifImageWidth")
        ),
        "height": safe_int(
            get(
                "EXIF:ImageHeight",
                "File:ImageHeight",
                "PNG:ImageHeight",
                "EXIF:ExifImageHeight",
            )
        ),
        "orientation": safe_int(get("EXIF:Orientation")),
        "duration_sec": safe_float(
            get("QuickTime:Duration", "Matroska:Duration", "RIFF:Duration")
        ),
    }
