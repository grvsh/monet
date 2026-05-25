from __future__ import annotations

# Preview and stream endpoints are defined in thumbnails.py as a single router
# This module re-exports the router for clean import structure.
from app.api.thumbnails import router  # noqa: F401
