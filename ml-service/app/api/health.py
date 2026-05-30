from __future__ import annotations

from fastapi import APIRouter

from app.loader import DEVICE, get_models
from app.manifest import MANIFEST

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    try:
        models = get_models()
        loaded = models.loaded
        status = "ready" if loaded else "degraded"
    except RuntimeError:
        return {"status": "loading", "models": {}, "device": DEVICE}

    import torch

    vram_used = vram_total = 0.0
    if torch.cuda.is_available():
        vram_used = torch.cuda.memory_allocated() / 1024**3
        vram_total = torch.cuda.get_device_properties(0).total_memory / 1024**3

    model_status = {
        feature: ("ready" if feature in loaded else "disabled")
        for feature in MANIFEST
    }

    return {
        "status": status,
        "models": model_status,
        "device": DEVICE,
        "vram_used_gb": round(vram_used, 2),
        "vram_total_gb": round(vram_total, 2),
    }


@router.get("/manifest")
async def manifest() -> dict:
    """Return the current model version manifest.

    The backend compares each file's stored ai_versions against this to
    determine which features are stale and need recomputation.
    """
    return {
        feature: {
            "version": meta["version"],
            "depends_on": meta.get("depends_on", []),
            "description": meta.get("description", ""),
        }
        for feature, meta in MANIFEST.items()
    }
