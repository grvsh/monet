"""POST /analyze — batch image analysis endpoint.

Receives up to ML_BATCH_SIZE images as multipart form data alongside a
comma-separated list of feature names. Returns per-image results.

All GPU inference is serialised through a single asyncio.Lock so concurrent
HTTP requests queue rather than contending for CUDA memory.
"""
from __future__ import annotations

import asyncio
import io
import logging
from typing import Any

import numpy as np
import torch
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from PIL import Image

from app.config import settings
from app.loader import DEVICE, get_models
from app.manifest import MANIFEST

router = APIRouter()
logger = logging.getLogger(__name__)

_gpu_lock = asyncio.Lock()


@router.post("/analyze")
async def analyze(
    images: list[UploadFile] = File(...),
    features: str = Form(...),
) -> dict:
    models = get_models()
    requested = {f.strip() for f in features.split(",") if f.strip()}
    # Only compute features that are both requested and have a loaded model
    to_run = requested & models.loaded
    if not to_run:
        raise HTTPException(status_code=400, detail=f"No enabled features in: {requested}")

    if len(images) > settings.ml_batch_size:
        raise HTTPException(
            status_code=400,
            detail=f"Batch size {len(images)} exceeds limit {settings.ml_batch_size}",
        )

    # Read all image bytes and decode to PIL upfront (outside the GPU lock)
    pil_images: list[Image.Image] = []
    for upload in images:
        raw = await upload.read()
        try:
            img = Image.open(io.BytesIO(raw)).convert("RGB")
            pil_images.append(img)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Invalid image: {exc}") from exc

    async with _gpu_lock:
        results = await asyncio.get_event_loop().run_in_executor(
            None, _run_inference, pil_images, to_run, models
        )

    return {"results": results}


def _run_inference(
    pil_images: list[Image.Image],
    to_run: set[str],
    models,
) -> list[dict[str, Any]]:
    n = len(pil_images)
    results: list[dict[str, Any]] = [{"index": i, "model_versions": {}} for i in range(n)]

    with torch.no_grad():
        if "clip_embedding" in to_run and models.clip_model is not None:
            _infer_clip(pil_images, results, models)

        if "aesthetic_score" in to_run and models.aesthetic_model is not None:
            _infer_aesthetic(pil_images, results, models)

        if "dino_embedding" in to_run and models.dino_model is not None:
            _infer_dino(pil_images, results, models)

    # Captioning is autoregressive — sequential by nature
    if "caption" in to_run and models.caption_model is not None:
        _infer_captions(pil_images, results, models)

    # Face detection — sequential (InsightFace processes one image at a time)
    if "faces" in to_run and models.face_analyzer is not None:
        _infer_faces(pil_images, results, models)

    # Object detection — YOLOv8 accepts a list so it batches internally
    if "objects" in to_run and models.yolo_model is not None:
        _infer_objects(pil_images, results, models)

    return results


def _pre_resize(images: list[Image.Image], size: int) -> list[Image.Image]:
    """Pre-resize images to a small square so CLIP/aesthetic CPU transforms
    only handle a tiny input instead of the full 768px source.
    CLIP/CLIP-L14 both resize to 224px internally; 256px is close enough to
    avoid any quality loss from the two-step resize."""
    return [img.resize((size, size), Image.BICUBIC) for img in images]


def _infer_clip(pil_images: list[Image.Image], results: list[dict], models) -> None:
    small = _pre_resize(pil_images, 256)
    tensors = torch.stack([models.clip_preprocess(img) for img in small]).to(DEVICE)
    embeddings = models.clip_model.encode_image(tensors)
    embeddings = embeddings / embeddings.norm(dim=-1, keepdim=True)
    for i, emb in enumerate(embeddings.cpu().float()):
        results[i]["clip_embedding"] = emb.numpy().tolist()
        results[i]["model_versions"]["clip_embedding"] = MANIFEST["clip_embedding"]["version"]


def _infer_aesthetic(pil_images: list[Image.Image], results: list[dict], models) -> None:
    small = _pre_resize(pil_images, 256)
    tensors = torch.stack([models.clip_l14_preprocess(img) for img in small]).to(DEVICE)
    features = models.clip_l14_model.encode_image(tensors)
    features = features / features.norm(dim=-1, keepdim=True)
    scores = models.aesthetic_model(features.float()).squeeze(-1)
    for i, score in enumerate(scores.cpu()):
        results[i]["aesthetic_score"] = round(float(score), 4)
        results[i]["model_versions"]["aesthetic_score"] = MANIFEST["aesthetic_score"]["version"]


def _infer_dino(pil_images: list[Image.Image], results: list[dict], models) -> None:
    inputs = models.dino_processor(images=pil_images, return_tensors="pt").to(DEVICE)
    outputs = models.dino_model(**inputs)
    # Use the [CLS] token embedding as the image representation
    embeddings = outputs.last_hidden_state[:, 0, :]
    embeddings = embeddings / embeddings.norm(dim=-1, keepdim=True)
    for i, emb in enumerate(embeddings.cpu().float()):
        results[i]["dino_embedding"] = emb.numpy().tolist()
        results[i]["model_versions"]["dino_embedding"] = MANIFEST["dino_embedding"]["version"]


def _infer_captions(pil_images: list[Image.Image], results: list[dict], models) -> None:
    for i, img in enumerate(pil_images):
        try:
            enc = models.caption_model.encode_image(img)
            caption = models.caption_model.answer_question(
                enc, "Describe this image.", models.caption_tokenizer
            )
            results[i]["caption"] = caption
            results[i]["model_versions"]["caption"] = MANIFEST["caption"]["version"]
        except Exception:
            logger.exception("Caption inference failed for image %d", i)


def _infer_faces(pil_images: list[Image.Image], results: list[dict], models) -> None:
    for i, img in enumerate(pil_images):
        try:
            img_np = np.array(img)[:, :, ::-1]  # PIL RGB → BGR for InsightFace
            faces = models.face_analyzer.get(img_np)
            face_list = []
            for face in faces:
                bbox = face.bbox.tolist()  # [x1, y1, x2, y2]
                face_list.append({
                    "bbox": {
                        "x": int(bbox[0]),
                        "y": int(bbox[1]),
                        "w": int(bbox[2] - bbox[0]),
                        "h": int(bbox[3] - bbox[1]),
                    },
                    "embedding": face.embedding.tolist() if face.embedding is not None else None,
                    "confidence": float(face.det_score) if face.det_score is not None else None,
                })
            results[i]["faces"] = face_list
            results[i]["model_versions"]["faces"] = MANIFEST["faces"]["version"]
        except Exception:
            logger.exception("Face inference failed for image %d", i)


def _infer_objects(pil_images: list[Image.Image], results: list[dict], models) -> None:
    try:
        yolo_results = models.yolo_model(pil_images, verbose=False)
        for i, det in enumerate(yolo_results):
            objects = []
            for box in det.boxes:
                cls_id = int(box.cls[0])
                label = det.names[cls_id]
                conf = float(box.conf[0])
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                objects.append({
                    "label": label,
                    "confidence": round(conf, 4),
                    "bbox": {
                        "x": int(x1), "y": int(y1),
                        "w": int(x2 - x1), "h": int(y2 - y1),
                    },
                })
            results[i]["objects"] = objects
            results[i]["model_versions"]["objects"] = MANIFEST["objects"]["version"]
    except Exception:
        logger.exception("YOLO inference failed")
