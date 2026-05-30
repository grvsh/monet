"""Authoritative model version manifest.

This is the single file to edit when upgrading a model. The version string
is stored alongside each file's ML results in the database. On rescan, the
backend compares stored versions against this manifest to determine which
features need recomputation and which can be served from cache.

Version string format: "<source>/<model-id>/<variant>"
"""
from __future__ import annotations

MANIFEST: dict[str, dict] = {
    "clip_embedding": {
        "version": "openclip/ViT-H-14/laion2b_s32b_b79k",
        "depends_on": [],
        "description": "1024-dim image embedding via OpenCLIP ViT-H/14",
    },
    "dino_embedding": {
        "version": "dinov2/giant/1.0",
        "depends_on": [],
        "description": "1536-dim visual feature embedding via DINOv2-giant",
    },
    "caption": {
        "version": "moondream2/2024-08-06",
        "depends_on": [],
        "description": "Natural language image description via Moondream2",
    },
    "faces": {
        "version": "insightface/buffalo_l/1.0",
        "depends_on": [],
        "description": "Face bounding boxes + 512-dim embeddings via InsightFace buffalo_l",
    },
    "objects": {
        "version": "yolov8x/8.3.0",
        "depends_on": [],
        "description": "Object detection (80 COCO classes) via YOLOv8x",
    },
    "aesthetic_score": {
        "version": "laion-aesthetic/v2+openclip-l14",
        "depends_on": [],
        "description": "Aesthetic quality score via LAION predictor on CLIP ViT-L/14 features",
    },
}
