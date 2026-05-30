"""Pre-download all ML models to the /models volume before first API start.

Run this once to avoid first-request latency:

    docker run --rm -v ml_models:/models ghcr.io/grvsh/monet-ml:latest \
        python /app/scripts/download_models.py

The script uses the same loading logic as the main app so the downloaded
artifacts are in exactly the format the app expects.
"""
from __future__ import annotations

import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# config.py sets cache env vars — must be imported before any ML library
import app.config  # noqa: F401
from app.loader import load_all_models


async def main() -> None:
    logging.info("Downloading all enabled models to %s ...", app.config.settings.model_cache_dir)
    models = await load_all_models()
    if not models.loaded:
        logging.error("No models loaded successfully.")
        sys.exit(1)
    logging.info("Done. Loaded: %s", sorted(models.loaded))


if __name__ == "__main__":
    asyncio.run(main())
