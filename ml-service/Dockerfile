# ML inference service for Monet.
# Base image: PyTorch 2.5.1 with CUDA 12.4 — matches RTX 4090 (sm_89).
# Models are stored in a named Docker volume (/models), NOT baked into the
# image. First run downloads models from HuggingFace/Ultralytics; subsequent
# starts load from volume in ~10-15 seconds.

FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime AS base

# libgl1 + libglib2.0-0: required by OpenCV (InsightFace/YOLO internal dep)
# libgomp1: required by numpy/torch OpenMP kernels
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# ffmpeg with NVENC support via conda-forge. The conda base is pre-installed
# in the pytorch/pytorch image. NVENC runtime libs come from the host NVIDIA
# driver via nvidia-container-toolkit — no extra packages needed.
RUN /opt/conda/bin/conda install -y -c conda-forge ffmpeg \
    && /opt/conda/bin/conda clean -afy

# Non-root user — matches the pattern used in the main backend image
RUN groupadd -r monet && useradd -r -g monet -d /app -s /sbin/nologin monet

WORKDIR /app

# ── Production stage ─────────────────────────────────────────────────────────
FROM base AS production

# Install Python dependencies before copying app code so this layer is cached
# across code-only changes.
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy application code
COPY app/ ./app/
COPY scripts/ ./scripts/

# /models is mounted as a named volume at runtime.
# The directory must exist and be writable by the monet user so that model
# download scripts can populate it.
RUN mkdir -p /models && chown -R monet:monet /models /app

USER monet

EXPOSE 8100

# Docker marks the container unhealthy until models finish loading.
# start_period gives the container 2 minutes to load models before the first
# health check fires (ViT-H-14 + DINOv2-giant cold-start takes ~90s).
HEALTHCHECK \
    --interval=30s \
    --timeout=10s \
    --start-period=120s \
    --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8100/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100", "--workers", "1"]
