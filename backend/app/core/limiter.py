from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

# Singleton used by routers and registered on the FastAPI app in main.py.
# Key function: client IP address.  For deployments behind a trusted reverse
# proxy, replace get_remote_address with a function that reads X-Forwarded-For.
limiter = Limiter(key_func=get_remote_address)
