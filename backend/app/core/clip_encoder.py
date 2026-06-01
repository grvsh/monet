from __future__ import annotations

import gc
import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_ready = False
_model = None
_tokenizer = None


def preload() -> None:
    """Kick off background load of the CLIP ViT-H-14 text encoder. Non-blocking."""
    t = threading.Thread(target=_load, daemon=True, name="clip-preload")
    t.start()


def _load() -> None:
    global _model, _tokenizer, _ready
    try:
        import open_clip
        import torch  # noqa: F401 — needed to initialise the module

        logger.info("Loading CLIP ViT-H-14 text encoder on CPU…")
        model, _, _ = open_clip.create_model_and_transforms(
            "ViT-H-14", pretrained="laion2b_s32b_b79k", device="cpu"
        )
        model.eval()

        # Drop the vision tower — we only need encode_text().
        # ViT-H-14 visual weights are ~2.5 GB; text encoder is ~500 MB.
        model.visual = None
        gc.collect()

        tokenizer = open_clip.get_tokenizer("ViT-H-14")

        with _lock:
            _model = model
            _tokenizer = tokenizer
            _ready = True

        logger.info("CLIP text encoder ready")
    except Exception:
        logger.exception("Failed to load CLIP text encoder — semantic search unavailable")


def encode(text: str) -> Optional[list[float]]:
    """Return a normalised 1024-dim CLIP text embedding, or None if not ready.

    Intended to be called in a thread-pool executor from async handlers so the
    CPU work doesn't block the event loop.
    """
    if not _ready:
        return None
    import torch

    tokens = _tokenizer([text])
    with torch.no_grad():
        features = _model.encode_text(tokens)
        features = features / features.norm(dim=-1, keepdim=True)
    return features[0].float().numpy().tolist()
