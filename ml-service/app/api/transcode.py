"""POST /video/transcode — GPU-accelerated H.264 transcoding via NVENC.

Called by the monet ml-worker when generating web-preview MP4s. The
ml-worker falls back to local CPU transcoding when this endpoint is
unavailable.

Concurrency is bounded by the number of NVENC encoder engines detected
at startup (typically 2 per RTX 4000-series GPU). Override via the
ML_VIDEO_ENCODER_CONCURRENCY env var.
"""
from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# NVENC availability + concurrency detection
# ---------------------------------------------------------------------------


def _detect_nvenc() -> tuple[bool, int]:
    """Return (nvenc_available, max_concurrent_sessions).

    Queries nvidia-smi for GPU names and infers NVENC engine count:
    - Ada Lovelace / RTX 4000-series: 2 NVENC engines per card
    - All other NVIDIA GPUs: 1 NVENC engine per card

    Override with ML_VIDEO_ENCODER_CONCURRENCY env var (set on the service).
    """
    override = settings.ml_video_encoder_concurrency
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            text=True,
            timeout=10,
        ).strip()
    except Exception:
        logger.warning("nvidia-smi unavailable — NVENC transcoding disabled")
        return False, 0

    gpus = [l.strip() for l in out.splitlines() if l.strip()]
    if not gpus:
        return False, 0

    if override > 0:
        count = override
    else:
        count = 0
        for name in gpus:
            upper = name.upper()
            # Ada Lovelace (RTX 40xx) ships with dual NVENC
            if "RTX 40" in upper or " ADA " in upper:
                count += 2
            else:
                count += 1

    logger.info(
        "NVENC available: %d concurrent session(s) across %d GPU(s): %s",
        count,
        len(gpus),
        ", ".join(gpus),
    )
    return True, max(1, count)


_NVENC_AVAILABLE, _NVENC_COUNT = _detect_nvenc()
_NVENC_SEM: asyncio.Semaphore | None = None


def _get_sem() -> asyncio.Semaphore:
    global _NVENC_SEM
    if _NVENC_SEM is None:
        _NVENC_SEM = asyncio.Semaphore(_NVENC_COUNT)
    return _NVENC_SEM


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


class TranscodeRequest(BaseModel):
    src: str
    dst: str
    crf: int = 21
    # NVENC preset: p1 (fastest) … p7 (slowest/best quality). p5 ≈ x264 "slow".
    preset: str = "p5"


@router.post("/video/transcode")
async def video_transcode(req: TranscodeRequest) -> dict:
    if not _NVENC_AVAILABLE:
        raise HTTPException(status_code=503, detail="NVENC not available on this host")

    src = Path(req.src)
    if not src.exists():
        raise HTTPException(status_code=404, detail=f"Source not found: {req.src}")

    async with _get_sem():
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, _run_nvenc, src, Path(req.dst), req.crf, req.preset
            )
        except subprocess.CalledProcessError as exc:
            logger.error("NVENC transcode failed for %s: %s", src, exc.stderr)
            raise HTTPException(status_code=500, detail="GPU transcode failed") from exc

    return {"status": "ok", "dst": req.dst}


def _run_nvenc(src: Path, dst: Path, crf: int, preset: str) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".nvenc_tmp.mp4")
    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-hwaccel", "cuda",
                "-i", str(src),
                "-vf", "scale=1920:1080:flags=lanczos",
                "-vcodec", "h264_nvenc",
                "-cq:v", str(crf),
                "-preset:v", preset,
                "-acodec", "aac",
                "-b:a", "192k",
                "-movflags", "+faststart",
                str(tmp),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        tmp.rename(dst)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
