# Monet — Security Review Report

**Date**: 2026-05-25  
**Reviewer**: Internal (AI-assisted)  
**Scope**: Full codebase review of Monet v0.1.0  
**Status**: All findings remediated  

---

## Executive Summary

A full security review was conducted against the Monet backend (FastAPI) and frontend (React) codebase prior to deployment. Nine findings were identified across four severity levels. All nine have been fixed in the same commit as this report. No findings remain open.

The core authentication architecture (JWT + Redis-backed refresh tokens, HttpOnly cookies, in-memory token storage on the frontend) is sound. The most significant risk was an overly broad filesystem browser that allowed any admin to enumerate the full server filesystem, including `/etc` and system directories containing secrets. This has been restricted to a configurable allowlist of NAS mount points.

| Severity | Count | Status |
|---|---|---|
| High | 1 | Fixed |
| Medium | 4 | Fixed |
| Low | 4 | Fixed |
| **Total** | **9** | **All fixed** |

---

## Scope

The review covered:

- All FastAPI route handlers and dependencies
- Authentication and session management
- Role-based access control
- Input validation and schema enforcement
- File serving and path construction
- CORS configuration
- Docker deployment configuration (Dockerfile, docker-compose)
- Frontend token storage and refresh logic

The review did **not** cover:
- Network-layer controls (firewall, VPN)
- OS-level hardening of the NAS host
- Third-party library CVEs (Pillow, rawpy, ffmpeg) — these should be monitored via Dependabot or equivalent

---

## Methodology

Each component was reviewed by reading the source code directly. Findings were assessed for exploitability in the target deployment context (small team, LAN-hosted NAS, no internet exposure in v1). Fixes were applied and verified by re-reading the modified files and confirming all Python sources remain syntax-clean.

---

## Findings

---

### FIND-01 — Unbounded Filesystem Browser

**Severity**: High  
**Status**: Fixed  
**File**: `app/api/fs_browse.py`

#### Description

The `GET /api/fs/browse?path=` endpoint accepted any absolute path on the server filesystem. An admin with valid credentials — or an attacker who compromised an admin session — could browse `/etc`, `/root`, `/proc`, and any other directory the backend process could read, including the directory containing the `.env` file with the JWT secret and database password.

#### Evidence

```python
# Before fix
resolved = Path(path).resolve()
with os.scandir(str(resolved)) as it:   # no restriction on resolved
    ...
```

#### Fix Applied

A `MONET_BROWSE_ROOTS` configuration setting was introduced (default: `/mnt,/media,/srv,/data`). The endpoint now resolves the requested path and rejects it with HTTP 403 if it does not fall within an allowed root. Path traversal sequences (`..`) are neutralised by `Path.resolve()` before the check, so `/mnt/../etc` resolves to `/etc` and is blocked.

```python
# After fix
_ALLOWED_ROOTS = [Path(p).resolve() for p in settings.monet_browse_roots]

def _is_within_allowed_root(resolved: Path) -> bool:
    return any(
        resolved == root or root in resolved.parents
        for root in _ALLOWED_ROOTS
    )

if not _is_within_allowed_root(resolved):
    raise HTTPException(status_code=403, detail="Path outside allowed browse roots")
```

The default browse view (no `path` parameter) now shows only the allowed roots themselves, not `/`.

#### Operator Action Required

Set `MONET_BROWSE_ROOTS` in `.env` to the NAS mount points where media actually lives (e.g. `/mnt/photos,/mnt/shared`). The default covers common NAS layouts but may need to be tightened.

---

### FIND-02 — No Rate Limiting on Login Endpoint

**Severity**: Medium  
**Status**: Fixed  
**File**: `app/api/auth.py`

#### Description

The `POST /api/auth/login` endpoint had no rate limiting, account lockout, or artificial delay. An attacker on the local network could attempt passwords in a loop. bcrypt's natural ~100 ms/hash provides some resistance, but allows approximately 600 attempts per minute per attacker thread.

#### Evidence

```python
# Before fix — no rate limiting decorator or middleware
@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, response: Response, ...):
    ...
```

#### Fix Applied

`slowapi` was added as a dependency and a rate limiter configured at 10 attempts per minute per client IP address. This is adjustable via the `LOGIN_RATE_LIMIT` setting. The limiter is a singleton in `app/core/limiter.py` registered on the FastAPI app at startup.

```python
# After fix
@router.post("/login", response_model=TokenResponse)
@limiter.limit(settings.login_rate_limit)   # default: "10/minute"
async def login(request: Request, body: LoginRequest, ...):
    ...
```

Excess requests receive HTTP 429 Too Many Requests.

---

### FIND-03 — User Enumeration via Response Timing

**Severity**: Medium  
**Status**: Fixed  
**File**: `app/api/auth.py`

#### Description

When a login attempt used an email address not in the database, the endpoint returned immediately (no bcrypt computation). When the email existed but the password was wrong, bcrypt ran (~100 ms). An attacker could distinguish between "unknown email" and "wrong password" by measuring response latency, enabling them to enumerate valid accounts before attempting to brute-force passwords.

#### Evidence

```python
# Before fix
user = result.scalar_one_or_none()
if not user or not user.is_active or not verify_password(...):
    raise HTTPException(status_code=401, detail="Invalid credentials")
# If user is None, verify_password never runs → instant response
```

#### Fix Applied

`DUMMY_HASH` — a precomputed bcrypt hash of a sentinel string — is computed once at module import time in `app/core/security.py`. When the email is not found, `verify_password(body.password, DUMMY_HASH)` runs before the 401 is returned, making the timing indistinguishable from a real wrong-password response.

```python
# After fix
DUMMY_HASH: str = hash_password("__monet_constant_time_sentinel__")

# In login handler:
if user is None:
    verify_password(body.password, DUMMY_HASH)   # ~100 ms constant-time check
    raise HTTPException(status_code=401, detail="Invalid credentials")
```

Both "unknown email" and "wrong password" paths now return the same HTTP status, the same detail string, and take approximately the same wall-clock time.

---

### FIND-04 — Docker Containers Running as Root

**Severity**: Medium  
**Status**: Fixed  
**File**: `backend/Dockerfile`

#### Description

Both the backend API container and the worker container ran as root (the Docker default when no `USER` directive is present). The worker processes untrusted media files using Pillow, rawpy, and ffmpeg — all of which have had CVEs involving malformed input files triggering memory-safety issues. Code execution achieved via a crafted RAW or video file would have root privileges inside the container, increasing the risk of container escape.

The NAS media directory was already mounted `:ro` (read-only), which was the correct mitigation for the mount itself, but did not address the in-container privilege level.

#### Evidence

```dockerfile
# Before fix — no USER directive
FROM python:3.12-slim AS production
COPY pyproject.toml .
RUN pip install --no-cache-dir .
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", ...]
```

#### Fix Applied

A dedicated `monet` system user and group are created in the base image. Both development and production stages switch to this user before the application starts.

```dockerfile
# After fix
RUN groupadd -r monet && useradd -r -g monet -d /app -s /sbin/nologin monet
RUN mkdir -p /var/monet/cache && chown -R monet:monet /var/monet /app
USER monet
```

---

### FIND-05 — `UserUpdate` Schema Accepted Arbitrary Role Strings

**Severity**: Medium  
**Status**: Fixed  
**File**: `app/models/schemas.py`

#### Description

`UserCreate` validated that `role` must be `"admin"` or `"viewer"`. However, `UserUpdate` — which shares the same `role` field and is used by `PATCH /api/users/{id}` — had no such validator. An admin could PATCH any user with `{"role": "superuser"}` and it would be written to the database verbatim. While the arbitrary role would not grant additional access (auth only checks `== "admin"`), the data integrity was violated and future role checks could behave unexpectedly.

#### Evidence

```python
# Before fix
class UserUpdate(BaseModel):
    full_name: str | None = None
    role: str | None = None          # no validator — any string accepted
    is_active: bool | None = None
```

#### Fix Applied

The same `@field_validator("role")` used in `UserCreate` was added to `UserUpdate`. It accepts `None` (field omitted, no change) or a member of `{"admin", "viewer"}`, and raises a 422 for anything else.

```python
# After fix
class UserUpdate(BaseModel):
    ...
    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_ROLES:
            raise ValueError(f"role must be one of {_VALID_ROLES}")
        return v
```

---

### FIND-06 — Refresh Token Cookie `Secure` Flag Hardcoded to `False`

**Severity**: Low  
**Status**: Fixed  
**File**: `app/api/auth.py`

#### Description

The refresh token cookie was set with `secure=False` and a comment saying "Switch to True when served over HTTPS". This required a code change at the time of internet deployment, creating a risk that the flag would be forgotten. If the cookie is `Secure=False` when HTTPS is added, the refresh token would be transmitted in plaintext in any HTTP redirect or fallback scenario.

#### Evidence

```python
# Before fix
response.set_cookie(
    ...
    secure=False,  # Switch to True when served over HTTPS
)
```

#### Fix Applied

The flag is now driven by a `MONET_SECURE_COOKIES` setting (default `False` for LAN, set `True` for internet). No code change is needed when adding TLS — only a one-line change to `.env`.

```python
# After fix
response.set_cookie(
    ...
    secure=settings.monet_secure_cookies,   # set MONET_SECURE_COOKIES=true with HTTPS
)
```

---

### FIND-07 — `Content-Disposition` Header Injection via Filename

**Severity**: Low  
**Status**: Fixed  
**File**: `app/api/thumbnails.py`

#### Description

The download endpoint constructed the `Content-Disposition` header by interpolating `media_file.filename` directly into a format string:

```python
# Before fix
"Content-Disposition": f'attachment; filename="{media_file.filename}"'
```

A filename containing a double-quote character (`"`) — which is valid on Linux filesystems — would break the header syntax. While the filename originates from the NAS filesystem (not direct user input), photo libraries commonly contain files with non-ASCII characters and unusual punctuation. Malformed headers can cause browser inconsistencies and, in edge cases, header injection.

#### Fix Applied

Encoding now follows RFC 5987 using `urllib.parse.quote`. The `filename*=UTF-8''<encoded>` form handles all Unicode and special characters unambiguously and is supported by all modern browsers.

```python
# After fix
from urllib.parse import quote

def _content_disposition(filename: str) -> str:
    encoded = quote(filename, safe="")
    return f"attachment; filename*=UTF-8''{encoded}"
```

---

### FIND-08 — CORS Allowed All HTTP Methods and Headers

**Severity**: Low  
**Status**: Fixed  
**File**: `app/main.py`

#### Description

The CORS middleware was configured with `allow_methods=["*"]` and `allow_headers=["*"]` alongside `allow_credentials=True`. While CORS does not protect against same-origin requests, overly permissive CORS configuration combined with credentials is a recognised misconfiguration category. It allows any HTTP method (including `PUT`, `OPTIONS`, `CONNECT`) and any header from listed origins — wider than the application actually uses.

#### Evidence

```python
# Before fix
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.monet_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

#### Fix Applied

Restricted to the exact methods and headers the frontend uses.

```python
# After fix
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.monet_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
```

---

### FIND-09 — Redis Had No Authentication

**Severity**: Low  
**Status**: Fixed  
**File**: `docker-compose.yml`, `docker-compose.test.yml`

#### Description

Redis was started without a password (`requirepass`). Although Redis is on an internal Docker bridge network and not exposed to the host beyond the mapped port, any container on the same Docker network could read and write the Redis store without credentials. This includes the ability to write arbitrary refresh token entries (`monet:refresh:{uuid}`) and impersonate any user.

#### Evidence

```yaml
# Before fix
redis:
  image: redis:7-alpine
  # No authentication
```

#### Fix Applied

Redis is now started with `--requirepass` driven by `REDIS_PASSWORD` from `.env`. The connection URL in both `backend` and `worker` services includes the password. Health checks pass `-a` for authentication.

```yaml
# After fix
redis:
  command: redis-server --requirepass ${REDIS_PASSWORD:?REDIS_PASSWORD must be set}
```

The `:?` modifier in the variable expansion causes docker compose to refuse to start if `REDIS_PASSWORD` is unset or empty, preventing accidental unauthenticated deployments.

---

## What Was Not Changed (and Why)

### JWT Algorithm (HS256)

HS256 was retained. RS256 (asymmetric) is only advantageous when multiple independent services need to verify tokens without sharing the signing key. Monet is a single-service deployment. HS256 with a 256-bit random key is cryptographically appropriate.

### No Per-User Audit Log

Access logging (who streamed or downloaded which file) is not implemented in v1. This is acceptable for the initial LAN deployment but should be added before any internet-facing deployment with multiple users, particularly given that media libraries may contain personal photographs.

### GPS/EXIF Exposure to All Viewers

All authenticated users can see GPS coordinates embedded in photo metadata. This is intentional (team sharing is the use case) but is worth communicating to users. A future enhancement could add a setting to strip GPS from API responses for viewer-role users.

### No Self-Deactivation Guard

An admin can deactivate their own account or demote themselves. For a small team deployment with a known-trustworthy admin this is acceptable. A future enhancement could require at least one active admin to exist at all times.

---

## Permissions Audit

The table below lists every privileged capability in the system and assesses whether it is necessary.

| Capability | Who Has It | Necessary? | Notes |
|---|---|---|---|
| Browse NAS filesystem | Admin only | Yes, scoped | Restricted to `MONET_BROWSE_ROOTS` after FIND-01 fix |
| Add / remove root folders | Admin only | Yes | Correct scope |
| Manage users | Admin only | Yes | Correct scope |
| Trigger re-index | Admin only | Yes | Correct scope |
| View all media in visible roots | All authenticated users | Yes | Team sharing is the purpose |
| Toggle own root folder visibility | All authenticated users | Yes | User preference, not a privilege |
| Stream / download original files | All authenticated users | Yes | Team access |
| Search all visible media | All authenticated users | Yes | Correct |
| CORS `allow_methods=["*"]` | N/A | **No** | Fixed — restricted to 4 methods |
| CORS `allow_headers=["*"]` | N/A | **No** | Fixed — restricted to 2 headers |
| Redis unauthenticated access | Any container on bridge | **No** | Fixed — password required |
| Backend runs as root | N/A | **No** | Fixed — runs as `monet` user |
| Browse `/etc`, `/root`, etc. | Admin | **No** | Fixed — `MONET_BROWSE_ROOTS` allowlist |

---

## Configuration Checklist for Deployment

Before going live, verify the following settings in `.env`:

```
# Must be a cryptographically random 32-byte hex string
JWT_SECRET_KEY=<output of: python3 -c "import secrets; print(secrets.token_hex(32))">

# Must be set — Redis will not start without it
REDIS_PASSWORD=<output of: python3 -c "import secrets; print(secrets.token_hex(24))">

# Tighten to the actual NAS mount points in use
MONET_BROWSE_ROOTS=/mnt/photos,/mnt/shared

# Set true when nginx + TLS is added
MONET_SECURE_COOKIES=false

# Tighten to the actual browser origin(s) in use
MONET_CORS_ORIGINS=http://<nas-ip>:8000

# Adjust downward if 10/min is too permissive for your threat model
LOGIN_RATE_LIMIT=10/minute
```

When internet access is later added:

1. Set `MONET_SECURE_COOKIES=true`
2. Set `MONET_CORS_ORIGINS` to the HTTPS domain only
3. Add nginx TLS termination (Let's Encrypt or Cloudflare)
4. Consider adding `MONET_BROWSE_ROOTS` to the tightest possible set since the admin panel will be remotely accessible

---

## Test Coverage for Security Controls

The following tests were added alongside the fixes. They live in the existing test suite and run as part of `make test`.

| Test | File | What It Verifies |
|---|---|---|
| `test_unknown_email_returns_401_not_404` | `test_auth.py` | User existence not revealed via status code |
| `test_unknown_email_same_error_message_as_wrong_password` | `test_auth.py` | Both failure paths return identical `detail` |
| `test_unknown_email_takes_measurable_time` | `test_auth.py` | Dummy bcrypt runs (response > 50 ms) |
| `test_refresh_cookie_present_after_login` | `test_auth.py` | HttpOnly cookie is set on successful login |
| `test_role_not_leaked_in_error` | `test_auth.py` | 401 message does not reveal account existence |
| `test_cannot_browse_etc` | `test_root_folders.py` | `/etc` blocked by browse root allowlist |
| `test_cannot_browse_root` | `test_root_folders.py` | `/` blocked by browse root allowlist |
| `test_cannot_browse_proc` | `test_root_folders.py` | `/proc` blocked by browse root allowlist |
| `test_path_traversal_rejected` | `test_root_folders.py` | `..` traversal to `/etc` is blocked after resolve |
| `test_viewer_cannot_browse` | `test_root_folders.py` | Viewer role cannot access filesystem browser |
| `test_unauthenticated_cannot_browse` | `test_root_folders.py` | Unauthenticated access rejected |
| `test_cannot_set_invalid_role` | `test_users.py` | `UserUpdate` rejects `"superuser"` etc. |
| `test_cannot_set_role_to_empty_string` | `test_users.py` | `UserUpdate` rejects empty string role |
| `test_valid_role_update_accepted` | `test_users.py` | `UserUpdate` accepts `"admin"` and `"viewer"` |
