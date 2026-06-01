FROM python:3.12-slim AS base

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libimage-exiftool-perl \
    ffmpeg \
    libmagic1 \
    libmagic-dev \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user so the process cannot write to system directories
# even if a malformed media file triggers a library vulnerability.
RUN groupadd -r monet && useradd -r -g monet -d /app -s /sbin/nologin monet

WORKDIR /app

# ── Development stage ────────────────────────────────────────────────────────
FROM base AS development

COPY pyproject.toml .
# Install CPU-only PyTorch before the rest of the deps so open-clip-torch
# reuses it instead of pulling in the much larger CUDA build.
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -e ".[dev]"

COPY . .

# Cache dir must be writable by the monet user
RUN mkdir -p /var/monet/cache && chown -R monet:monet /var/monet /app

USER monet

# ── Production stage ─────────────────────────────────────────────────────────
FROM base AS production

COPY pyproject.toml .
# Install CPU-only PyTorch before the rest of the deps so open-clip-torch
# reuses it instead of pulling in the much larger CUDA build.
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir .

COPY . .

RUN mkdir -p /var/monet/cache && chown -R monet:monet /var/monet /app

USER monet

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
