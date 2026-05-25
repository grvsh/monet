#!/usr/bin/env python3
"""
Create synthetic test fixture media files for Monet tests.
Run from project root: python scripts/create_test_fixtures.py
Output goes to backend/tests/fixtures/
"""
from __future__ import annotations

import io
import os
import struct
import sys
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent.parent / "backend" / "tests" / "fixtures"
FIXTURES_DIR.mkdir(parents=True, exist_ok=True)


# ── Pillow-based image fixtures ───────────────────────────────────────────────

def create_image_fixtures():
    try:
        from PIL import Image, ImageDraw
        import piexif
    except ImportError:
        print("Pillow not available — skipping image fixtures (install in venv first)")
        return

    def make_image(color: tuple, size: tuple = (100, 75)) -> Image.Image:
        img = Image.new("RGB", size, color)
        draw = ImageDraw.Draw(img)
        # Draw a simple grid so it's visually distinguishable
        for x in range(0, size[0], 10):
            draw.line([(x, 0), (x, size[1])], fill=(color[0]^0xFF, color[1], color[2]), width=1)
        return img

    def exif_bytes(make: str = "Canon", model: str = "Canon EOS R5",
                   date: str = "2024:07:14 09:22:41",
                   lat: float | None = None, lon: float | None = None) -> bytes:
        exif_dict: dict = {"0th": {}, "Exif": {}, "GPS": {}}
        exif_dict["0th"][piexif.ImageIFD.Make] = make.encode()
        exif_dict["0th"][piexif.ImageIFD.Model] = model.encode()
        exif_dict["0th"][piexif.ImageIFD.Software] = b"Monet Test"
        exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = date.encode()
        exif_dict["Exif"][piexif.ExifIFD.FNumber] = (28, 10)
        exif_dict["Exif"][piexif.ExifIFD.ExposureTime] = (1, 250)
        exif_dict["Exif"][piexif.ExifIFD.ISOSpeedRatings] = 400
        exif_dict["Exif"][piexif.ExifIFD.FocalLength] = (850, 10)
        exif_dict["Exif"][piexif.ExifIFD.LensModel] = b"RF 85mm F1.2 L USM"
        if lat is not None and lon is not None:
            def to_dms(val):
                d = int(abs(val))
                m = int((abs(val) - d) * 60)
                s = round(((abs(val) - d) * 60 - m) * 60 * 100)
                return [(d, 1), (m, 1), (s, 100)]
            exif_dict["GPS"][piexif.GPSIFD.GPSLatitudeRef] = b"N" if lat >= 0 else b"S"
            exif_dict["GPS"][piexif.GPSIFD.GPSLatitude] = to_dms(lat)
            exif_dict["GPS"][piexif.GPSIFD.GPSLongitudeRef] = b"E" if lon >= 0 else b"W"
            exif_dict["GPS"][piexif.GPSIFD.GPSLongitude] = to_dms(lon)
        return piexif.dump(exif_dict)

    # 1. Basic JPEG with EXIF (Canon, has GPS)
    img = make_image((200, 100, 80))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=90,
             exif=exif_bytes(lat=48.8566, lon=2.3522))
    (FIXTURES_DIR / "test_photo_canon.jpg").write_bytes(out.getvalue())
    print(f"  ✓ test_photo_canon.jpg ({len(out.getvalue())} bytes)")

    # 2. JPEG — Nikon, no GPS
    img = make_image((80, 120, 200), size=(75, 100))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=90,
             exif=exif_bytes(make="NIKON CORPORATION", model="NIKON D850",
                             date="2023:03:20 15:45:00"))
    (FIXTURES_DIR / "test_photo_nikon.jpg").write_bytes(out.getvalue())
    print(f"  ✓ test_photo_nikon.jpg ({len(out.getvalue())} bytes)")

    # 3. PNG
    img = make_image((80, 200, 80))
    img.save(FIXTURES_DIR / "test_image.png", "PNG")
    print(f"  ✓ test_image.png")

    # 4. WebP
    img = make_image((200, 80, 200))
    img.save(FIXTURES_DIR / "test_image.webp", "WEBP", quality=85)
    print(f"  ✓ test_image.webp")

    # 5. Landscape (for aspect-ratio testing)
    img = make_image((180, 160, 60), size=(200, 133))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=85)
    (FIXTURES_DIR / "test_landscape.jpg").write_bytes(out.getvalue())
    print(f"  ✓ test_landscape.jpg (200×133)")

    # 6. Portrait
    img = make_image((60, 160, 180), size=(133, 200))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=85)
    (FIXTURES_DIR / "test_portrait.jpg").write_bytes(out.getvalue())
    print(f"  ✓ test_portrait.jpg (133×200)")

    # 7. Large image (for preview downscaling test)
    img = Image.new("RGB", (4000, 3000), (100, 150, 200))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=85)
    (FIXTURES_DIR / "test_large.jpg").write_bytes(out.getvalue())
    print(f"  ✓ test_large.jpg (4000×3000)")

    # 8. HEIC (requires pillow-heif)
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
        img = make_image((220, 160, 60))
        heif_file = pillow_heif.from_pillow(img)
        out = io.BytesIO()
        heif_file.save(out, format="HEIF")
        (FIXTURES_DIR / "test_photo.heic").write_bytes(out.getvalue())
        print(f"  ✓ test_photo.heic")
    except Exception as e:
        print(f"  ⚠ HEIC skipped ({e})")

    print("  Image fixtures done")


# ── Minimal valid MP4 fixture ─────────────────────────────────────────────────

def create_video_fixtures():
    """Try to create a tiny test video with ffmpeg; fall back to a minimal MP4 container."""
    import shutil, subprocess, tempfile

    mp4_path = FIXTURES_DIR / "test_video.mp4"
    mov_path = FIXTURES_DIR / "test_video.mov"

    if shutil.which("ffmpeg"):
        # Create a 1-second, 10x10, solid-colour test video
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "color=c=blue:size=10x10:rate=1:duration=1",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
            "-t", "1",
            "-vcodec", "libx264", "-pix_fmt", "yuv420p",
            "-acodec", "aac",
            str(mp4_path),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            print(f"  ✓ test_video.mp4 (1s, 10×10 via ffmpeg)")
        except subprocess.CalledProcessError as e:
            print(f"  ⚠ ffmpeg mp4 failed: {e.stderr.decode()[:200]}")
            _write_minimal_mp4(mp4_path)

        # MOV
        cmd_mov = cmd[:-1] + [str(mov_path)]
        cmd_mov[cmd_mov.index(str(mp4_path))] = str(mov_path)
        try:
            subprocess.run(
                ["ffmpeg", "-y",
                 "-f", "lavfi", "-i", "color=c=red:size=10x10:rate=1:duration=1",
                 "-t", "1", "-vcodec", "libx264", "-pix_fmt", "yuv420p",
                 str(mov_path)],
                check=True, capture_output=True,
            )
            print(f"  ✓ test_video.mov")
        except Exception:
            mov_path.write_bytes(mp4_path.read_bytes())  # copy mp4 as mov for tests
            print(f"  ✓ test_video.mov (copied from mp4)")
    else:
        print("  ⚠ ffmpeg not found — writing minimal placeholder MP4")
        _write_minimal_mp4(mp4_path)
        mov_path.write_bytes(mp4_path.read_bytes())

    print("  Video fixtures done")


def _write_minimal_mp4(path: Path):
    """Write a syntactically valid but empty-content MP4 (ftyp + mdat boxes only).
    Enough for MIME detection and metadata extraction to not crash, but ffprobe
    will report 0 duration. Processor tests should mock ffmpeg for real video ops.
    """
    def box(fourcc: str, payload: bytes = b"") -> bytes:
        size = 8 + len(payload)
        return struct.pack(">I4s", size, fourcc.encode()) + payload

    ftyp = box("ftyp", b"isom" + struct.pack(">I", 0) + b"isomiso2mp41")
    mdat = box("mdat", b"\x00" * 8)
    path.write_bytes(ftyp + mdat)
    print(f"  ✓ {path.name} (minimal placeholder, {len(ftyp + mdat)} bytes)")


# ── Minimal MP3 with ID3 fixture ──────────────────────────────────────────────

def create_audio_fixtures():
    mp3_path = FIXTURES_DIR / "test_audio.mp3"

    # Minimal valid ID3v2.3 + MPEG frame
    def syncsafe(n: int, length: int = 4) -> bytes:
        result = bytearray(length)
        for i in range(length - 1, -1, -1):
            result[i] = n & 0x7F
            n >>= 7
        return bytes(result)

    def id3_frame(frame_id: str, data: bytes) -> bytes:
        return frame_id.encode() + struct.pack(">IH", len(data), 0) + data

    frames = b"".join([
        id3_frame("TIT2", b"\x00Test Track"),
        id3_frame("TPE1", b"\x00Test Artist"),
        id3_frame("TALB", b"\x00Test Album"),
        id3_frame("TYER", b"\x00 2024"),
    ])

    padding = b"\x00" * 128
    tag_size = len(frames) + len(padding)
    id3_header = b"ID3" + bytes([3, 0, 0]) + syncsafe(tag_size)
    id3_tag = id3_header + frames + padding

    # Minimal valid MPEG1 Layer3 silent frame (sync word + header)
    mpeg_frame = bytes([0xFF, 0xFB, 0x90, 0x00]) + b"\x00" * 413

    mp3_path.write_bytes(id3_tag + mpeg_frame)
    print(f"  ✓ test_audio.mp3 ({len(id3_tag + mpeg_frame)} bytes)")

    # FLAC: just write the fLaC marker + STREAMINFO block
    flac_path = FIXTURES_DIR / "test_audio.flac"
    streaminfo = struct.pack(
        ">HHI3s3sQH",
        4410, 4410,  # min/max block size
        0,           # min/max frame size (unknown)
        b"\x04\xe1\x00"[:3],  # sample rate 44100Hz + channels + bit depth
        b"\x00\x00\x00"[:3],  # sample count high
        0,           # sample count low
        0,           # MD5 (zeroed)
    ) + b"\x00" * 8  # pad to 34 bytes
    streaminfo = b"\x00" * 34  # simplified
    flac_header = b"fLaC"
    flac_path.write_bytes(flac_header + b"\x80" + struct.pack(">I", 34)[1:] + streaminfo)
    print(f"  ✓ test_audio.flac (minimal)")

    print("  Audio fixtures done")


# ── Directory structure fixture ───────────────────────────────────────────────

def create_media_tree():
    """Create a sample media directory tree for integration tests."""
    tree_root = FIXTURES_DIR / "media_tree"

    structure = {
        "2023/summer_vacation": ["IMG_001.jpg", "IMG_002.jpg", "video_001.mp4"],
        "2023/christmas": ["IMG_010.jpg", "IMG_011.jpg"],
        "2024/spring": ["IMG_100.jpg", "IMG_101.jpg", "IMG_102.jpg", "song.mp3"],
        "2024/autumn": ["IMG_200.jpg"],
        "misc": ["document.pdf", "notes.txt", "IMG_300.jpg"],  # mixed — PDF/txt should be ignored
    }

    try:
        from PIL import Image
        import io

        def small_jpeg(color=(100, 100, 200)) -> bytes:
            buf = io.BytesIO()
            Image.new("RGB", (10, 10), color).save(buf, "JPEG")
            return buf.getvalue()

        def small_mp4() -> bytes:
            import struct
            def box(fc, payload=b""):
                return struct.pack(">I4s", 8 + len(payload), fc.encode()) + payload
            return box("ftyp", b"isom" + struct.pack(">I", 0) + b"isommp41") + box("mdat", b"\x00" * 8)

        def small_mp3() -> bytes:
            return b"ID3" + b"\x03\x00\x00\x00\x00\x00\x00" + b"\xFF\xFB\x90\x00" + b"\x00" * 100

        def small_pdf() -> bytes:
            return b"%PDF-1.4\n%%EOF\n"

        colors = [(200,100,80), (80,200,100), (80,100,200), (200,200,80), (200,80,200)]
        for ci, (folder, files) in enumerate(structure.items()):
            folder_path = tree_root / folder
            folder_path.mkdir(parents=True, exist_ok=True)
            for fi, filename in enumerate(files):
                fp = folder_path / filename
                ext = filename.rsplit(".", 1)[-1].lower()
                if ext in ("jpg", "jpeg"):
                    fp.write_bytes(small_jpeg(colors[(ci + fi) % len(colors)]))
                elif ext == "mp4":
                    fp.write_bytes(small_mp4())
                elif ext == "mp3":
                    fp.write_bytes(small_mp3())
                elif ext == "pdf":
                    fp.write_bytes(small_pdf())
                else:
                    fp.write_text("test content")

        print(f"  ✓ media_tree/ created at {tree_root}")
        print(f"    {sum(len(v) for v in structure.values())} files across {len(structure)} folders")
    except ImportError:
        print("  ⚠ Pillow not available — media_tree skipped")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"Creating test fixtures in {FIXTURES_DIR}")
    print()

    print("Images:")
    create_image_fixtures()
    print()

    print("Video:")
    create_video_fixtures()
    print()

    print("Audio:")
    create_audio_fixtures()
    print()

    print("Media tree:")
    create_media_tree()
    print()

    files = list(FIXTURES_DIR.rglob("*"))
    print(f"Done. {len([f for f in files if f.is_file()])} fixture files created.")
