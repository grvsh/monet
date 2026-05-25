from __future__ import annotations

import asyncio
import json
import time
import urllib.request
from typing import Optional

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
_USER_AGENT = "monet-photo-library/1.0"
_last_call: float = 0.0
_lock: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


async def reverse_geocode(lat: float, lon: float) -> Optional[str]:
    """Return a human-readable location string for GPS coordinates using Nominatim.

    Respects the Nominatim 1 req/sec rate limit via an asyncio lock.
    """
    global _last_call
    lock = _get_lock()
    async with lock:
        elapsed = time.monotonic() - _last_call
        if elapsed < 1.0:
            await asyncio.sleep(1.0 - elapsed)
        _last_call = time.monotonic()

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch, lat, lon)


def _fetch(lat: float, lon: float) -> Optional[str]:
    url = f"{_NOMINATIM_URL}?format=json&lat={lat}&lon={lon}&zoom=10"
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        address = data.get("address", {})
        locality = (
            address.get("suburb")
            or address.get("city")
            or address.get("town")
            or address.get("village")
            or address.get("county")
        )
        state = address.get("state")
        country_code = address.get("country_code", "").upper() or None
        parts = [p for p in (locality, state, country_code) if p]
        return ", ".join(parts) if parts else None
    except Exception:
        return None
