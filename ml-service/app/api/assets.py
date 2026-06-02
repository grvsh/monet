"""
/assets/generate        — single-file convenience wrapper
/assets/generate/batch  — batch: torchvision GPU pipeline for images,
                          NVDEC ffmpeg for videos

Image pipeline (GPU):
  All reads are submitted to a ThreadPoolExecutor upfront, so disk I/O for
  image N+1 runs while the GPU processes image N.  Writes are submitted
  immediately after each GPU resize so they overlap with the next resize.
  This is the same prefetch/overlap pattern as PyTorch DataLoader.

Video pipeline:
  ffmpeg with -hwaccel cuda (NVDEC) for frame extraction.
  Runs in thread pool so multiple videos decode concurrently.

RAW / HEIF / audio:
  Returns {"error": "unsupported"} per item — backend falls back to CPU.
"""
from __future__ import annotations

import json
import asyncio
import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import torch
import torchvision.transforms.functional as TF
from fastapi import APIRouter, HTTPException
from PIL import Image, ImageOps
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)

_RAW_EXTENSIONS = frozenset(
    {"cr2", "cr3", "nef", "nrw", "dng", "orf", "raf", "arw", "rw2", "pef", "srw"}
)
_HEIF_EXTENSIONS = frozenset({"heic", "heif"})

_DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
# Separate pools so writes never starve reads (or vice versa)
_READ_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="assets-read")
_WRITE_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="assets-write")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class AssetRequest(BaseModel):
    src: str
    thumb_path: str
    preview_path: str
    media_type: str  # "image" | "video"
    extension: str
    thumb_size: int = 400
    preview_max_w: int = 2048
    preview_max_h: int = 2048
    thumb_quality: int = 85
    preview_quality: int = 85


class BatchAssetRequest(BaseModel):
    items: list[AssetRequest]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/assets/generate")
async def generate_assets(req: AssetRequest) -> dict:
    """Single-file wrapper — delegates to the batch endpoint."""
    results = await generate_assets_batch(BatchAssetRequest(items=[req]))
    r = results[0]
    if err := r.get("error"):
        raise HTTPException(status_code=422 if err == "unsupported" else 500, detail=err)
    return r


@router.post("/assets/generate/batch")
async def generate_assets_batch(req: BatchAssetRequest) -> list[dict]:
    if not req.items:
        return []
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _run_batch, req.items)


# ---------------------------------------------------------------------------
# Batch dispatcher
# ---------------------------------------------------------------------------


def _run_batch(items: list[AssetRequest]) -> list[dict]:
    results: list[dict | None] = [None] * len(items)

    image_idxs, video_idxs = [], []
    for i, r in enumerate(items):
        ext = r.extension.lower().lstrip(".")
        if r.media_type == "audio" or ext in _RAW_EXTENSIONS or ext in _HEIF_EXTENSIONS:
            results[i] = {"error": "unsupported"}
        elif r.media_type == "video":
            video_idxs.append(i)
        else:
            image_idxs.append(i)

    # Videos: NVDEC, run concurrently
    if video_idxs:
        futs = {i: _READ_EXECUTOR.submit(_process_video, items[i]) for i in video_idxs}
        for i, fut in futs.items():
            try:
                results[i] = fut.result()
            except Exception as exc:
                logger.error("video asset failed %s: %s", items[i].src, exc)
                results[i] = {"error": str(exc)}

    # Images: GPU pipeline with I/O overlap
    if image_idxs:
        for idx, res in zip(image_idxs, _process_images_gpu([items[i] for i in image_idxs])):
            results[idx] = res

    return results  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Image GPU pipeline  (read → GPU resize → write, all overlapping)
# ---------------------------------------------------------------------------


def _process_images_gpu(items: list[AssetRequest]) -> list[dict]:
    # Submit all reads upfront — disk I/O for image N+1 runs while GPU
    # processes image N.
    read_futures = [_READ_EXECUTOR.submit(_read_image, r) for r in items]
    write_futures = []
    results: list[dict] = []

    for req, rfut in zip(items, read_futures):
        try:
            tensor, orig_w, orig_h = rfut.result()
        except Exception as exc:
            logger.error("read failed %s: %s", req.src, exc)
            results.append({"error": str(exc)})
            continue

        try:
            gpu = tensor.to(_DEVICE)
            thumb = _resize_fit(gpu, req.thumb_size, req.thumb_size)
            preview = _resize_fit(gpu, req.preview_max_w, req.preview_max_h)

            # Submit writes immediately — they run while GPU processes next image.
            write_futures.append(
                _WRITE_EXECUTOR.submit(_save_jpeg, thumb.cpu(), req.thumb_path, req.thumb_quality)
            )
            write_futures.append(
                _WRITE_EXECUTOR.submit(_save_jpeg, preview.cpu(), req.preview_path, req.preview_quality)
            )

            results.append({"width": orig_w, "height": orig_h})
        except Exception as exc:
            logger.error("GPU resize failed %s: %s", req.src, exc)
            results.append({"error": str(exc)})

    for fut in write_futures:
        try:
            fut.result()
        except Exception as exc:
            logger.error("write failed: %s", exc)

    return results


def _read_image(req: AssetRequest) -> tuple[torch.Tensor, int, int]:
    """Open, orient (EXIF), convert to float RGB tensor [3,H,W] in [0,1]."""
    ext = req.extension.lower().lstrip(".")
    if ext in _HEIF_EXTENSIONS:
        from pillow_heif import register_heif_opener
        register_heif_opener()
    img = Image.open(req.src)
    img = ImageOps.exif_transpose(img)
    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    return TF.to_tensor(img), w, h


def _resize_fit(t: torch.Tensor, max_w: int, max_h: int) -> torch.Tensor:
    """Downscale to fit within max_w × max_h, aspect-ratio preserved. Never upscales."""
    _, h, w = t.shape
    scale = min(max_w / w, max_h / h, 1.0)
    if scale >= 1.0:
        return t
    return TF.resize(
        t.unsqueeze(0),
        [round(h * scale), round(w * scale)],
        interpolation=TF.InterpolationMode.BICUBIC,
        antialias=True,
    ).squeeze(0)


def _save_jpeg(tensor: torch.Tensor, path: str, quality: int) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp.jpg")
    try:
        TF.to_pil_image(tensor.clamp(0, 1)).save(str(tmp), "JPEG", quality=quality, optimize=True)
        tmp.rename(p)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


# ---------------------------------------------------------------------------
# Video: NVDEC ffmpeg
# ---------------------------------------------------------------------------


def _process_video(req: AssetRequest) -> dict:
    if not Path(req.src).exists():
        raise FileNotFoundError(req.src)
    w, h = _ffprobe_dimensions(req.src)
    seek = str(max(0.0, _ffprobe_duration(req.src) * 0.1))
    size = req.thumb_size
    tq = _pil_q_to_ffmpeg(req.thumb_quality)
    pq = _pil_q_to_ffmpeg(req.preview_quality)
    thumb, preview = Path(req.thumb_path), Path(req.preview_path)
    thumb.parent.mkdir(parents=True, exist_ok=True)
    preview.parent.mkdir(parents=True, exist_ok=True)
    tmp_t, tmp_p = thumb.with_suffix(".tmp.jpg"), preview.with_suffix(".tmp.jpg")
    try:
        _ffmpeg(["-hwaccel", "cuda", "-ss", seek, "-i", req.src,
                 "-vf", f"scale={size}:{size}:force_original_aspect_ratio=decrease:flags=lanczos",
                 "-vframes", "1", "-q:v", str(tq), "-y", str(tmp_t)])
        _ffmpeg(["-hwaccel", "cuda", "-ss", seek, "-i", req.src,
                 "-vf", f"scale={req.preview_max_w}:{req.preview_max_h}:force_original_aspect_ratio=decrease",
                 "-vframes", "1", "-q:v", str(pq), "-y", str(tmp_p)])
        tmp_t.rename(thumb)
        tmp_p.rename(preview)
    except Exception:
        tmp_t.unlink(missing_ok=True)
        tmp_p.unlink(missing_ok=True)
        raise
    return {"width": w, "height": h}


# ---------------------------------------------------------------------------
# ffprobe helpers
# ---------------------------------------------------------------------------


def _ffprobe_dimensions(src: str) -> tuple[int, int]:
    out = subprocess.check_output(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_streams", "-select_streams", "v:0", src],
        text=True,
    )
    streams = json.loads(out).get("streams", [])
    if not streams:
        raise ValueError(f"No video stream in {src}")
    return int(streams[0]["width"]), int(streams[0]["height"])


def _ffprobe_duration(src: str) -> float:
    out = subprocess.check_output(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", src],
        text=True,
    )
    return float(out.strip() or "0")


def _pil_q_to_ffmpeg(q: int) -> int:
    return max(1, min(31, round((100 - q) / 3) + 1))


def _ffmpeg(args: list[str]) -> None:
    subprocess.run(["ffmpeg"] + args, check=True, capture_output=True, text=True)
