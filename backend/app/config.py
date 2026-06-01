from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    redis_url: str = "redis://localhost:6379/0"
    monet_cache_dir: str = "/var/monet/cache"
    monet_host: str = "0.0.0.0"
    monet_port: int = 8000
    monet_log_level: str = "info"
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    monet_thumb_size: int = 480
    monet_preview_max_width: int = 3840
    monet_preview_max_height: int = 2160
    monet_thumb_quality: int = 85
    monet_preview_quality: int = 90
    monet_worker_concurrency: int = 4
    monet_watch_enabled: bool = True
    monet_scan_on_startup: bool = True
    monet_file_settle_seconds: int = 2
    monet_cors_origins: list[str] = ["http://localhost:5173", "http://localhost:8000"]

    # ── Video preview transcoding ──────────────────────────────────────────────
    monet_video_preview_enabled: bool = True
    monet_video_preview_crf: int = 21
    monet_video_preview_preset: str = "slow"
    monet_video_preview_concurrency: int = 3

    # ── ML service ─────────────────────────────────────────────────────────────
    # URL of the monet-ml FastAPI service. Leave empty to disable ML features.
    monet_ml_service_url: str = ""
    # Bearer token sent to the ML service. Leave empty when running on an
    # isolated Docker network where no auth is needed.
    monet_ml_api_key: str = ""
    # Images in each batch POST to /analyze (tune for VRAM vs latency).
    monet_ml_batch_size: int = 32
    # Longest side in pixels for the ML analysis image generated from the preview.
    monet_ml_image_size: int = 768

    # ── Security ───────────────────────────────────────────────────────────────
    # Directories the admin may browse via /api/fs/browse. Defaults to common
    # NAS mount points. Set to a tighter list in production.
    monet_browse_roots: list[str] = ["/mnt", "/media", "/srv", "/data", "/home"]
    # Set True when running behind HTTPS (nginx + TLS). Marks the refresh-token
    # cookie as Secure so it is never sent over plain HTTP.
    monet_secure_cookies: bool = False
    # Max login attempts per IP per minute before 429 is returned.
    login_rate_limit: str = "10/minute"


settings = Settings()
