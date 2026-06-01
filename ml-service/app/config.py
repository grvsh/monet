from __future__ import annotations

import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ml_api_key: str = ""
    ml_batch_size: int = 32
    # Maximum concurrent NVENC transcode sessions. 0 = auto-detect from GPU.
    ml_video_encoder_concurrency: int = 0
    # Comma-separated list of features to enable. Remove a feature to skip
    # loading its model and free VRAM.
    ml_enabled_features: str = (
        "clip_embedding,dino_embedding,caption,faces,objects,aesthetic_score"
    )
    model_cache_dir: str = "/models"

    @property
    def enabled_features(self) -> set[str]:
        return {f.strip() for f in self.ml_enabled_features.split(",") if f.strip()}


settings = Settings()

# Point all ML library caches at the named volume so models persist across
# container restarts and are never baked into the image.
os.environ.setdefault("HF_HOME", f"{settings.model_cache_dir}/hf")
os.environ.setdefault("TORCH_HOME", f"{settings.model_cache_dir}/torch")
os.environ.setdefault("INSIGHTFACE_HOME", f"{settings.model_cache_dir}/insightface")
os.environ.setdefault("YOLO_CONFIG_DIR", f"{settings.model_cache_dir}/ultralytics")
