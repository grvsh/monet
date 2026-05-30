"""Model loading and in-memory cache.

All models are loaded once at startup into GPU memory and kept warm for the
lifetime of the process. The loader is called from the FastAPI lifespan hook.

Model download strategy: each library uses its own cache env var (set in
config.py) pointing to the /models named volume. First run downloads from
the internet; subsequent runs load from disk in ~10-15 seconds.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import torch

from app.config import settings

logger = logging.getLogger(__name__)

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


@dataclass
class Models:
    # OpenCLIP ViT-H-14 (clip_embedding)
    clip_model: Any = None
    clip_preprocess: Any = None
    clip_tokenizer: Any = None

    # CLIP ViT-L-14/openai — used only for aesthetic scoring
    clip_l14_model: Any = None
    clip_l14_preprocess: Any = None

    # Aesthetic predictor: linear head over CLIP L/14 features
    aesthetic_model: Any = None

    # DINOv2-giant (dino_embedding)
    dino_model: Any = None
    dino_processor: Any = None

    # Moondream2 (caption)
    caption_model: Any = None
    caption_tokenizer: Any = None

    # InsightFace buffalo_l (faces)
    face_analyzer: Any = None

    # YOLOv8x (objects)
    yolo_model: Any = None

    # Which features successfully loaded
    loaded: set[str] = field(default_factory=set)


_models: Models | None = None


def get_models() -> Models:
    if _models is None:
        raise RuntimeError("Models not loaded — call load_all_models() first")
    return _models


async def load_all_models() -> Models:
    global _models
    m = Models()
    enabled = settings.enabled_features

    if "clip_embedding" in enabled:
        _load_clip_h14(m)

    if "aesthetic_score" in enabled:
        _load_aesthetic(m)

    if "dino_embedding" in enabled:
        _load_dino(m)

    if "caption" in enabled:
        _load_moondream(m)

    if "faces" in enabled:
        _load_insightface(m)

    if "objects" in enabled:
        _load_yolo(m)

    _models = m
    logger.info("Models loaded: %s (device=%s)", sorted(m.loaded), DEVICE)
    _log_vram()
    return m


def _load_clip_h14(m: Models) -> None:
    try:
        import open_clip
        logger.info("Loading OpenCLIP ViT-H-14...")
        model, _, preprocess = open_clip.create_model_and_transforms(
            "ViT-H-14",
            pretrained="laion2b_s32b_b79k",
            device=DEVICE,
        )
        model.eval()
        tokenizer = open_clip.get_tokenizer("ViT-H-14")
        m.clip_model = model
        m.clip_preprocess = preprocess
        m.clip_tokenizer = tokenizer
        m.loaded.add("clip_embedding")
        logger.info("CLIP ViT-H-14 ready")
    except Exception:
        logger.exception("Failed to load CLIP ViT-H-14")


def _load_aesthetic(m: Models) -> None:
    """Load CLIP ViT-L-14 and the LAION aesthetic predictor linear head."""
    try:
        import open_clip
        import torch.nn as nn
        from huggingface_hub import hf_hub_download

        logger.info("Loading CLIP ViT-L-14 for aesthetic scoring...")
        l14_model, _, l14_preprocess = open_clip.create_model_and_transforms(
            "ViT-L-14",
            pretrained="openai",
            device=DEVICE,
        )
        l14_model.eval()
        m.clip_l14_model = l14_model
        m.clip_l14_preprocess = l14_preprocess

        logger.info("Loading LAION aesthetic predictor...")
        weights_path = hf_hub_download(
            repo_id="shunk031/aesthetics-predictor-v2-sac-logos-ava1-l14-linearMSE",
            filename="pytorch_model.bin",
            cache_dir=f"{settings.model_cache_dir}/hf",
        )
        # The predictor is a single linear layer: Linear(768, 1)
        aesthetic_head = nn.Linear(768, 1)
        state = torch.load(weights_path, map_location=DEVICE, weights_only=True)
        aesthetic_head.load_state_dict(state)
        aesthetic_head.eval()
        aesthetic_head.to(DEVICE)
        m.aesthetic_model = aesthetic_head
        m.loaded.add("aesthetic_score")
        logger.info("Aesthetic predictor ready")
    except Exception:
        logger.exception("Failed to load aesthetic predictor")


def _load_dino(m: Models) -> None:
    try:
        from transformers import AutoFeatureExtractor, AutoModel

        logger.info("Loading DINOv2-giant...")
        m.dino_processor = AutoFeatureExtractor.from_pretrained(
            "facebook/dinov2-giant",
            cache_dir=f"{settings.model_cache_dir}/hf",
        )
        m.dino_model = AutoModel.from_pretrained(
            "facebook/dinov2-giant",
            cache_dir=f"{settings.model_cache_dir}/hf",
        ).to(DEVICE).eval()
        m.loaded.add("dino_embedding")
        logger.info("DINOv2-giant ready")
    except Exception:
        logger.exception("Failed to load DINOv2-giant")


def _load_moondream(m: Models) -> None:
    try:
        from transformers import AutoModelForCausalLM, AutoTokenizer

        logger.info("Loading Moondream2...")
        m.caption_tokenizer = AutoTokenizer.from_pretrained(
            "vikhyatk/moondream2",
            revision="2024-08-06",
            cache_dir=f"{settings.model_cache_dir}/hf",
        )
        m.caption_model = AutoModelForCausalLM.from_pretrained(
            "vikhyatk/moondream2",
            revision="2024-08-06",
            trust_remote_code=True,
            cache_dir=f"{settings.model_cache_dir}/hf",
            torch_dtype=torch.float16,
            device_map={"": DEVICE},
        ).eval()
        m.loaded.add("caption")
        logger.info("Moondream2 ready")
    except Exception:
        logger.exception("Failed to load Moondream2")


def _load_insightface(m: Models) -> None:
    try:
        import insightface
        from insightface.app import FaceAnalysis

        logger.info("Loading InsightFace buffalo_l...")
        providers = (
            ["CUDAExecutionProvider", "CPUExecutionProvider"]
            if DEVICE == "cuda"
            else ["CPUExecutionProvider"]
        )
        analyzer = FaceAnalysis(
            name="buffalo_l",
            root=f"{settings.model_cache_dir}/insightface",
            providers=providers,
        )
        analyzer.prepare(ctx_id=0 if DEVICE == "cuda" else -1, det_size=(640, 640))
        m.face_analyzer = analyzer
        m.loaded.add("faces")
        logger.info("InsightFace buffalo_l ready")
    except Exception:
        logger.exception("Failed to load InsightFace")


def _load_yolo(m: Models) -> None:
    try:
        from ultralytics import YOLO

        logger.info("Loading YOLOv8x...")
        yolo = YOLO("yolov8x.pt")
        yolo.to(DEVICE)
        m.yolo_model = yolo
        m.loaded.add("objects")
        logger.info("YOLOv8x ready")
    except Exception:
        logger.exception("Failed to load YOLOv8x")


def _log_vram() -> None:
    if not torch.cuda.is_available():
        return
    used = torch.cuda.memory_allocated() / 1024**3
    total = torch.cuda.get_device_properties(0).total_memory / 1024**3
    logger.info("VRAM: %.1f / %.1f GB used after model load", used, total)
