# Monet — Media Management & Browsing App
## Architecture Document

---

## 1. System Overview

Monet is a self-hosted media management and browsing application running on a NAS Linux machine, accessed over the local LAN by a small team. It indexes images, audio, and video from one or more configurable root directories, generates thumbnails and previews, extracts all available metadata, reverse-geocodes GPS coordinates, and presents a web UI that mirrors the on-disk folder structure.

**Scale target**: up to 1,000 folders × 1,000 files per folder = up to 1M media files.
**Concurrency**: 4 ARQ worker processes for background indexing.
**Access**: LAN only in v1. Internet access (HTTPS, reverse proxy) added later.

```
NAS Disk
  ├── /mnt/photos/alice/          ← root folder 1
  └── /mnt/photos/bob/            ← root folder 2
        └── 2024/vacation/

Monet Backend (FastAPI)
  ├── REST API + JWT Auth
  ├── ARQ Worker × 4              ← background indexing + daily cron jobs
  ├── PostgreSQL                  ← metadata, users, root folder config
  └── Redis                       ← ARQ queue + token blacklist

  Cache (disk)
    ├── thumbnails/               ← sharded JPEG files
    └── previews/                 ← sharded JPEG files (on-demand)

Monet Frontend (Vite + React)
  └── Browser (LAN)
        ├── Sidebar: root folder tree + Trash link
        ├── Gallery: thumbnail grid with metadata captions
        ├── Lightbox: preview + side metadata panel
        ├── Trash: dedicated view for trashed files
        └── Settings: root folder management + per-user visibility prefs
```

---

## 2. Technology Stack

### Backend
| Concern | Choice | Rationale |
|---|---|---|
| API framework | **FastAPI** + Uvicorn | async, auto OpenAPI docs |
| Database | **PostgreSQL 16** via SQLAlchemy (async, asyncpg) | multi-user concurrency, JSONB+GIN for metadata |
| Migrations | **Alembic** | PostgreSQL schema versioning |
| Job queue | **ARQ** + Redis | async workers, cron jobs, BFS folder expansion |
| Auth | **PyJWT** + **passlib[bcrypt]** | stateless access tokens + Redis-backed refresh tokens |
| Image processing | **Pillow** + **pillow-heif** | JPEG/PNG/WebP/TIFF/HEIC thumbnails and previews |
| RAW image support | **rawpy** (LibRaw ≥ 0.20) | Canon CR2/CR3, Nikon NEF/NRW, DNG; LibRaw 0.20+ required for CR3 |
| Video thumbnails | **ffmpeg-python** | frame extraction from MOV, MP4, MKV, etc. |
| EXIF / metadata | **pyexiftool** (wraps ExifTool binary) | all tags, all formats, JSON output |
| Reverse geocoding | **Nominatim** (OpenStreetMap) | GPS → human-readable location; no API key; 1 req/sec rate limit |
| Filesystem watching | **watchdog** (inotify on Linux) | one watcher per root folder |
| Settings | **Pydantic Settings** | typed config from `.env` |

### Frontend
| Concern | Choice | Rationale |
|---|---|---|
| Build tool | **Vite** + TypeScript | fast HMR |
| UI framework | **React 18** | |
| Routing | **React Router v6** | folder path → URL, protected routes |
| Data fetching | **TanStack Query v5** | caching, background refetch |
| Component library | **shadcn/ui** + **Tailwind CSS** | composable, zero runtime overhead |
| Virtual lists | **TanStack Virtual** | render only visible tiles at 1M-file scale |
| Lightbox | **yet-another-react-lightbox** | keyboard nav, zoom, video support |
| Icons | **Lucide React** | |
| Global state | **Zustand** | auth, gallery selection/sort/filter state |
| HTTP client | **axios** | interceptors for JWT auto-refresh |

### System Dependencies (on NAS)
- `exiftool` — metadata extraction
- `ffmpeg` — video frame extraction
- `libraw` ≥ 0.20 — Canon CR3 and other RAW decode (rawpy links against this)

---

## 3. Multiple Root Folders

### 3.1 Concept

Root folders are the top-level media directories Monet watches. Each maps to an absolute path on the NAS. They are configured via the app's Settings page (admin only). All users can see all root folders; each user independently toggles which ones appear in their sidebar.

Example configuration:
```
Root folder 1 — "Alice"  →  /mnt/photos/alice
Root folder 2 — "Bob"    →  /mnt/photos/bob
Root folder 3 — "Shared" →  /mnt/shared/events
```

### 3.2 Database Tables

```sql
CREATE TABLE root_folders (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,           -- display label in sidebar
    path        TEXT UNIQUE NOT NULL,    -- absolute path on disk
    is_active   BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Per-user toggle: which root folders are shown in their sidebar
CREATE TABLE user_root_prefs (
    user_id        UUID REFERENCES users(id) ON DELETE CASCADE,
    root_folder_id UUID REFERENCES root_folders(id) ON DELETE CASCADE,
    is_visible     BOOLEAN NOT NULL DEFAULT true,
    PRIMARY KEY (user_id, root_folder_id)
);
```

Default: when a new root folder is added, all existing users see it (visible = true). User can hide it from their own view.

### 3.3 Root Folder API

```
GET    /api/root-folders              → list all (all authenticated users)
POST   /api/root-folders              → add new root folder (admin)
PATCH  /api/root-folders/{id}         → rename / change path (admin)
DELETE /api/root-folders/{id}         → remove + soft-delete its media (admin)

GET    /api/users/me/root-prefs       → current user's visibility prefs
PUT    /api/users/me/root-prefs       → update visibility prefs (toggle per root folder)

POST   /api/index/scan                → scan all active root folders
POST   /api/index/scan/{root_id}      → scan one root folder
GET    /api/index/status              → overall progress
GET    /api/index/status/{root_id}    → per-root progress
```

---

## 4. Data Models

Seven tables in total. The design principle: columns that the application queries, filters, or sorts on live directly on `media_files`; everything else lives in the `file_metadata` JSONB blob. This avoids a JOIN to the metadata table for every gallery page load.

---

### 4.1 `users`

Stores credentials and role. Refresh tokens are **not** in the DB — they live in Redis with a TTL, keeping this table append-only during normal operation.

```sql
CREATE TABLE users (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    email           TEXT        UNIQUE NOT NULL,
    hashed_password TEXT        NOT NULL,           -- bcrypt hash
    full_name       TEXT,
    role            TEXT        NOT NULL DEFAULT 'viewer', -- 'admin' | 'viewer'
    is_active       BOOLEAN     NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at   TIMESTAMPTZ                     -- updated on each successful login
);
```

| Column | Notes |
|---|---|
| `role` | Two values in v1. Add more roles later without schema change — it's a free text column with application-level validation. |
| `is_active` | Soft disable. Setting false immediately invalidates future logins; existing refresh tokens are purged from Redis separately by the deactivation API call. |
| `last_login_at` | Useful for spotting inactive accounts on a shared team install. |

---

### 4.2 `root_folders`

One row per configured media root. Paths are absolute on the NAS filesystem. Admins manage these via the Settings UI; the watcher and indexer read from this table at startup.

```sql
CREATE TABLE root_folders (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name           TEXT        NOT NULL,        -- display label, e.g. "Alice's Library"
    path           TEXT        UNIQUE NOT NULL, -- absolute path on NAS, e.g. /mnt/photos/alice
    is_active      BOOLEAN     NOT NULL DEFAULT true,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by     UUID        REFERENCES users(id) ON DELETE SET NULL,
    last_scanned_at TIMESTAMPTZ                -- set when a full scan of this root completes
);
```

| Column | Notes |
|---|---|
| `path` | Unique constraint prevents the same directory being added twice. |
| `is_active` | Inactive roots are not watched or scanned but their indexed data is retained. Lets an admin temporarily suspend a root without losing the index. |
| `created_by` | Audit trail for who added the root. SET NULL on user delete so the row survives. |
| `last_scanned_at` | Displayed in the Settings UI next to each root folder. |

---

### 4.3 `user_root_prefs`

Pure join table. Controls which root folders appear in a given user's sidebar. Defaults to visible for all roots — a row is only written when the user changes their preference away from the default.

```sql
CREATE TABLE user_root_prefs (
    user_id        UUID    REFERENCES users(id)        ON DELETE CASCADE,
    root_folder_id UUID    REFERENCES root_folders(id) ON DELETE CASCADE,
    is_visible     BOOLEAN NOT NULL DEFAULT true,
    PRIMARY KEY (user_id, root_folder_id)
);
```

| Column | Notes |
|---|---|
| `is_visible` | When a new root folder is added, no rows are inserted here — absence of a row means "use default (visible)". The API reads this as a LEFT JOIN and treats NULL as true. |

---

### 4.4 `folders`

Mirrors the on-disk directory hierarchy within each root folder. One row per directory. The `path` is relative to the root folder's `path`, making it root-portable.

```sql
CREATE TABLE folders (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    root_folder_id    UUID        NOT NULL REFERENCES root_folders(id) ON DELETE CASCADE,
    parent_id         UUID        REFERENCES folders(id) ON DELETE CASCADE, -- null = direct child of root
    path              TEXT        NOT NULL,   -- relative to root, e.g. "2024/vacation"
    name              TEXT        NOT NULL,   -- just the directory name, e.g. "vacation"
    file_count        INTEGER     NOT NULL DEFAULT 0,         -- cached; updated after each scan
    child_folder_count INTEGER    NOT NULL DEFAULT 0,         -- cached; for tree chevron display
    indexed_at        TIMESTAMPTZ,                            -- last time this folder was scanned
    UNIQUE (root_folder_id, path)
);

CREATE INDEX idx_folders_root   ON folders(root_folder_id);
CREATE INDEX idx_folders_parent ON folders(parent_id);
CREATE INDEX idx_folders_path   ON folders(path text_pattern_ops); -- prefix queries for subtree ops
```

| Column | Notes |
|---|---|
| `path` | Relative, not absolute. If the NAS mount point changes, only `root_folders.path` needs updating — all `folders.path` values remain valid. |
| `parent_id` | Enables the tree without recursive path parsing. NULL means the folder is a direct child of its root. |
| `file_count` | Cached on the folder row so the sidebar tree can show counts without aggregating `media_files`. Updated at end of each `scan_folder` job. Only counts active (non-trashed, non-missing) files. |
| `child_folder_count` | Tells the frontend whether to render a tree expand chevron, without fetching children. |
| `indexed_at` | Used by incremental scans: if `indexed_at` is recent and no watchdog event fired, the folder is skipped. |

---

### 4.5 `media_files`

The central table. One row per media file. Contains file-system facts, dimension/duration facts, and a set of **denormalized EXIF fields** (§4.7) for the queries the gallery makes constantly.

```sql
CREATE TABLE media_files (
    -- Identity
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    folder_id       UUID        NOT NULL REFERENCES folders(id)      ON DELETE CASCADE,
    root_folder_id  UUID        NOT NULL REFERENCES root_folders(id) ON DELETE CASCADE,

    -- Filesystem
    path            TEXT        NOT NULL,    -- relative to root folder, e.g. "2024/vacation/IMG_001.CR3"
    filename        TEXT        NOT NULL,    -- e.g. "IMG_001.CR3"
    extension       TEXT        NOT NULL,    -- lowercase, no dot: "cr3", "jpg", "mov"
    size_bytes      BIGINT,
    mtime           TIMESTAMPTZ,            -- filesystem mtime; change detection key

    -- Classification
    media_type      TEXT        NOT NULL,    -- 'image' | 'video' | 'audio'
    mime_type       TEXT        NOT NULL,    -- e.g. 'image/jpeg', 'video/quicktime'
    is_raw          BOOLEAN     NOT NULL DEFAULT false, -- true for CR2/CR3/NEF/DNG/etc.

    -- Dimensions (from ExifTool or ffprobe)
    width           INTEGER,                -- pixels; null for audio
    height          INTEGER,                -- pixels; null for audio
    orientation     SMALLINT,              -- EXIF orientation tag 1–8; thumbnails have this baked in
    duration_sec    REAL,                   -- null for images

    -- Denormalized EXIF fields (see §4.7)
    taken_at        TIMESTAMPTZ,           -- EXIF DateTimeOriginal (preferred) or file mtime fallback
    camera_make     TEXT,                  -- EXIF Make, e.g. "Canon"
    camera_model    TEXT,                  -- EXIF Model, e.g. "Canon EOS R5"
    lens_model      TEXT,                  -- EXIF LensModel, e.g. "RF 85mm F1.2 L USM"
    focal_length_mm REAL,                  -- EXIF FocalLength, normalized to mm
    aperture        REAL,                  -- EXIF FNumber, e.g. 2.8
    shutter_speed   TEXT,                  -- EXIF ExposureTime as string, e.g. "1/250"
    iso             INTEGER,               -- EXIF ISO
    gps_lat         DOUBLE PRECISION,      -- decimal degrees, positive = N
    gps_lon         DOUBLE PRECISION,      -- decimal degrees, positive = E
    gps_alt_m       REAL,                  -- metres above sea level
    location        TEXT,                  -- reverse-geocoded: "Fremont, California, US"

    -- Generated assets
    thumbnail_path  TEXT,                  -- relative to MONET_CACHE_DIR/thumbnails/
    preview_path    TEXT,                  -- relative to MONET_CACHE_DIR/previews/

    -- Lifecycle
    indexed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at    TIMESTAMPTZ,           -- set when thumbnail + preview are written
    is_deleted      BOOLEAN     NOT NULL DEFAULT false, -- true = user-initiated trash
    deleted_at      TIMESTAMPTZ,           -- when user moved file to trash
    missing_since   TIMESTAMPTZ,           -- set by scanner when file not found on disk (external move/delete)

    UNIQUE (root_folder_id, path)
);

CREATE INDEX idx_files_folder    ON media_files(folder_id);
CREATE INDEX idx_files_root      ON media_files(root_folder_id);
CREATE INDEX idx_files_taken_at  ON media_files(taken_at);
CREATE INDEX idx_files_type      ON media_files(media_type);
CREATE INDEX idx_files_camera    ON media_files(camera_make, camera_model);
CREATE INDEX idx_files_deleted   ON media_files(is_deleted) WHERE is_deleted = false; -- partial index
CREATE INDEX idx_files_pending   ON media_files(processed_at)  WHERE processed_at IS NULL; -- find unprocessed
```

| Column | Notes |
|---|---|
| `root_folder_id` | Denormalized from `folder.root_folder_id`. Lets the API filter by root without a JOIN to `folders`. |
| `extension` | Lowercase, no dot. Faster for format-based filtering than parsing `mime_type` or `filename`. |
| `mtime` | The change-detection key. During incremental scans, if `mtime` matches the stored value, the file is skipped entirely. |
| `is_raw` | Derived from extension at index time. Lets users filter "RAW only" without touching the JSONB. |
| `orientation` | EXIF orientation 1–8. Stored for display in the metadata panel. Generated thumbnails/previews have orientation baked in via `ImageOps.exif_transpose()` so the frontend doesn't need to rotate. |
| `taken_at` | Populated from `EXIF:DateTimeOriginal` first, `EXIF:CreateDate` second, `File:FileModifyDate` as fallback. This is the primary sort key for chronological gallery views. |
| `gps_lat / gps_lon / gps_alt_m` | Decimal degrees. Converted from the DMS+reference format ExifTool returns. Stored here so a future map view can query them without hitting the JSONB. |
| `location` | Human-readable location string from Nominatim reverse geocoding ("City, State, Country"). Populated asynchronously after metadata extraction if GPS coordinates are present. Displayed on gallery tile captions and in the metadata panel. |
| `is_deleted` | **User-initiated trash only.** Set to true when the user explicitly moves a file to Trash via the UI. Files trashed this way are auto-purged after 30 days. Never set by the scanner — see `missing_since` for that. |
| `deleted_at` | Timestamp when the user moved the file to Trash. The 30-day auto-purge window is calculated from this value. |
| `missing_since` | Set by the scanner when a file cannot be found on disk but was NOT user-trashed. Indicates the file was likely moved or deleted outside the app. Cleared automatically if the file reappears on disk. Separate from `is_deleted` to avoid conflating external reorganization with intentional deletion. |
| `processed_at` | NULL means thumbnail/preview generation is pending. The partial index on `processed_at IS NULL` makes it fast to find the backlog queue. |

**File state matrix**:

| `is_deleted` | `missing_since` | State | Shown in |
|---|---|---|---|
| false | NULL | Active | Folder gallery |
| true | NULL | User-trashed | Trash page, folder "Recently Deleted" section |
| false | set | Missing from disk | Folder "Missing from disk" section |

---

### 4.6 `file_metadata`

Full ExifTool JSON output, stored verbatim as JSONB. One row per file. Contains every tag ExifTool can extract — hundreds per file — without any schema. The GIN index makes arbitrary tag searches efficient.

```sql
CREATE TABLE file_metadata (
    file_id UUID PRIMARY KEY REFERENCES media_files(id) ON DELETE CASCADE,
    data    JSONB NOT NULL   -- ExifTool output with -j -G1 (grouped tag names)
);

CREATE INDEX idx_metadata_gin ON file_metadata USING GIN (data);
```

**ExifTool output shape** (`exiftool -j -G1 -n file.cr3`):

```json
{
  "SourceFile": "/mnt/photos/alice/2024/vacation/IMG_001.CR3",
  "ExifTool:ExifToolVersion": "12.76",
  "File:FileName": "IMG_001.CR3",
  "File:FileSize": 28311552,
  "File:MIMEType": "image/x-canon-cr3",
  "EXIF:Make": "Canon",
  "EXIF:Model": "Canon EOS R5",
  "EXIF:DateTimeOriginal": "2024:07:14 09:22:41",
  "EXIF:ExposureTime": 0.004,
  "EXIF:FNumber": 2.8,
  "EXIF:ISO": 400,
  "EXIF:FocalLength": 85.0,
  "EXIF:LensModel": "RF 85mm F1.2 L USM",
  "EXIF:ImageWidth": 8192,
  "EXIF:ImageHeight": 5464,
  "GPS:GPSLatitude": 48.8566,
  "GPS:GPSLongitude": 2.3522,
  "XMP:Rating": 4
}
```

**Example JSONB queries**:

```sql
-- All Canon R5 shots
SELECT mf.* FROM media_files mf
JOIN file_metadata fm ON fm.file_id = mf.id
WHERE fm.data->>'EXIF:Model' = 'Canon EOS R5';

-- Photos rated 4 or 5 stars (XMP)
WHERE (fm.data->>'XMP:Rating')::int >= 4;

-- Contain a specific lens
WHERE fm.data @> '{"EXIF:LensModel": "RF 85mm F1.2 L USM"}';
```

Most gallery queries (sort by date, filter by type, filter by folder) never touch this table — they use the denormalized columns on `media_files`. The JSONB table is used for the detail/metadata panel and for advanced search.

---

### 4.7 Denormalization Rationale

These EXIF fields are copied to `media_files` columns in addition to living in the JSONB blob:

| Field | Reason for denormalization |
|---|---|
| `taken_at` | Primary sort key for every gallery view. A JOIN + JSONB cast on every page load would be expensive. |
| `camera_make / camera_model` | Very common filter ("show only Canon shots"). Cheap to index as plain text columns. |
| `lens_model` | Displayed on every gallery tile caption; common filter for photographers reviewing a specific lens. |
| `focal_length_mm / aperture / shutter_speed / iso` | The "exposure quad" — displayed in the metadata panel and needed for future filtering. |
| `gps_lat / gps_lon / gps_alt_m` | Required for the future map view; JSONB can't be used with spatial indexes. Stored now at zero cost. |
| `location` | Reverse-geocoded string derived from GPS coords. Displayed on gallery tile captions without a JSONB lookup. |
| `is_raw` | Frequent filter. Faster as a boolean column than parsing `mime_type` or `extension` at query time. |

Fields **not** denormalized (accessed only via JSONB):
- White balance, colour temperature, flash mode, metering mode
- Lens serial number, camera serial number
- Copyright, artist, caption (IPTC/XMP)
- Software, processing history
- XMP ratings and labels
- All Makernote fields (Canon-specific, Nikon-specific, etc.)

---

### 4.8 `scan_jobs`

Audit log of every indexing run. Gives admins visibility into scan history, duration, and how many new/changed/deleted files were found. Also used to drive the live progress indicator while a scan is running (alongside the Redis hash for real-time updates).

```sql
CREATE TABLE scan_jobs (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    root_folder_id  UUID        REFERENCES root_folders(id) ON DELETE SET NULL, -- null = all roots
    triggered_by    UUID        REFERENCES users(id) ON DELETE SET NULL,        -- null = system
    trigger_type    TEXT        NOT NULL, -- 'startup' | 'manual' | 'watcher' | 'scheduled'
    status          TEXT        NOT NULL DEFAULT 'running', -- 'running' | 'completed' | 'failed'

    -- Progress counters (updated incrementally as jobs complete)
    folders_found   INTEGER     NOT NULL DEFAULT 0,
    folders_scanned INTEGER     NOT NULL DEFAULT 0,
    files_found     INTEGER     NOT NULL DEFAULT 0,
    files_new       INTEGER     NOT NULL DEFAULT 0,
    files_updated   INTEGER     NOT NULL DEFAULT 0,
    files_deleted   INTEGER     NOT NULL DEFAULT 0,  -- now counts newly-missing files
    files_skipped   INTEGER     NOT NULL DEFAULT 0,  -- unchanged, no reprocessing needed

    error_message   TEXT,                            -- set on failure

    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX idx_scan_jobs_root   ON scan_jobs(root_folder_id);
CREATE INDEX idx_scan_jobs_status ON scan_jobs(status);
```

| Column | Notes |
|---|---|
| `root_folder_id` | NULL means the job covers all active roots (triggered by "Scan All"). |
| `triggered_by` | NULL for system-initiated scans (startup, watcher). SET NULL on user delete so history is not lost. |
| `trigger_type` | Distinguishes manual admin action from automated behaviour in the history view. |
| `files_deleted` | Now counts files newly marked `missing_since` (externally moved/deleted), not `is_deleted`. |
| `files_skipped` | Files where `mtime` matched and `processed_at` was already set. Visible in the UI to confirm the incremental scan is working. |
| Progress counters | Written by ARQ workers after each `scan_folder` / `generate_assets` job completes. The Settings page polls `GET /api/index/status/{root_folder_id}` which reads both the live Redis hash (for in-progress runs) and the latest completed `scan_jobs` row (for history). |

---

### 4.9 Entity Relationship Summary

```
users ──────────────────────────────────── scan_jobs
  │                                            │ (triggered_by)
  │ user_root_prefs                            │
  └──────────────┐                             │
                 ▼                             │
           root_folders ◄─────────────────────┘
                 │
                 │ 1:many
                 ▼
            folders (self-referential parent_id)
                 │
                 │ 1:many
                 ▼
           media_files ──── file_metadata
            (denorm EXIF)    (full JSONB)
```

**Cascade rules**:
- Delete `root_folder` → cascades to `folders` → cascades to `media_files` → cascades to `file_metadata`
- Delete `user` → cascades `user_root_prefs`; SET NULL on `scan_jobs.triggered_by` and `root_folders.created_by`

---

## 5. Authentication

### 5.1 Token Design

```
Login: POST /api/auth/login  {email, password}
  → verify bcrypt hash
  → issue Access Token (JWT, HS256, 15 min expiry) → returned in response body
  → issue Refresh Token (opaque UUID, 7 days) → stored in Redis, sent as HttpOnly cookie

Authenticated request:
  Authorization: Bearer <access_token>

Auto-refresh (axios interceptor):
  on 401 → POST /api/auth/refresh (cookie sent automatically)
         → receive new access token → retry original request

Logout: POST /api/auth/logout → delete refresh token from Redis
```

Access tokens are verified by signature only (stateless). Refresh tokens are stored in Redis so they can be revoked immediately on logout or when an admin deactivates a user.

Access token stored in-memory in Zustand (not localStorage) — inaccessible to XSS. Refresh token in HttpOnly cookie — inaccessible to JavaScript entirely.

### 5.2 Roles

Two roles for v1 (no per-folder RBAC):
- **admin** — manage users, manage root folders, trigger re-index, read all media
- **viewer** — read all media, manage their own root folder visibility prefs

Admin creates users. No self-registration.

### 5.3 Auth Endpoints

```
POST /api/auth/login
POST /api/auth/refresh
POST /api/auth/logout
GET  /api/auth/me

GET    /api/users        (admin)
POST   /api/users        (admin)
PATCH  /api/users/{id}   (admin)
DELETE /api/users/{id}   (admin)
```

---

## 6. Backend Architecture

### 6.1 Directory Layout

```
backend/
├── app/
│   ├── main.py              ← FastAPI app, lifespan, CORS
│   ├── config.py            ← Pydantic Settings
│   ├── database.py          ← SQLAlchemy async engine + session factory
│   ├── redis.py             ← Redis connection pool
│   ├── models/
│   │   ├── db.py            ← ORM models
│   │   └── schemas.py       ← Pydantic request/response schemas
│   ├── api/
│   │   ├── auth.py
│   │   ├── users.py
│   │   ├── root_folders.py
│   │   ├── fs_browse.py         ← directory browser (admin only)
│   │   ├── folders.py
│   │   ├── files.py
│   │   ├── thumbnails.py
│   │   ├── previews.py
│   │   └── index.py
│   ├── core/
│   │   ├── auth.py          ← JWT encode/decode, FastAPI dependencies
│   │   └── security.py      ← bcrypt helpers
│   ├── services/
│   │   ├── indexer.py       ← scan orchestration, mark_missing_files
│   │   ├── geocoder.py      ← Nominatim reverse geocoding (rate-limited)
│   │   ├── watcher.py       ← one watchdog observer per root folder
│   │   ├── processor.py     ← thumbnail + preview generation
│   │   ├── metadata.py      ← ExifTool wrapper, JSONB normalisation
│   │   └── media.py         ← MIME detection, format routing
│   └── workers/
│       ├── tasks.py         ← ARQ task definitions
│       └── worker.py        ← ARQ WorkerSettings (concurrency=4, cron jobs)
├── alembic/
│   └── versions/
│       ├── 0001_initial_schema.py
│       ├── 0002_add_location.py      ← location TEXT on media_files
│       └── 0003_add_missing_since.py ← missing_since TIMESTAMPTZ on media_files
├── pyproject.toml
└── .env.example
```

### 6.2 Media Processing Pipeline

```
File change detected (watcher or scan job)
        │
        ▼
1. MIME detection (python-magic)
2. Media type check — skip non-media files
3. Enqueue: extract_metadata + generate_assets

extract_metadata(file_id):
  pyexiftool → parse all tags → upsert file_metadata JSONB
  update media_files.width, height, duration_sec, taken_at, camera_*, lens_model, etc.
  if GPS coords present AND location not yet set:
    → call geocoder.reverse_geocode(lat, lon) (rate-limited, async)
    → update media_files.location

generate_assets(file_id):
  Route by format:

  JPEG / PNG / WebP / TIFF / GIF / BMP
    └── Pillow → apply ICC profile → sRGB
          ├── thumbnail: longest side 480px, JPEG q85
          └── preview: fit within 3840×2160, aspect preserved, JPEG q90

  HEIC / HEIF  (iPhone photos)
    └── pillow-heif → Pillow Image → same pipeline as above

  RAW — Canon CR2 / CR3 / Nikon NEF / NRW
    └── rawpy.imread() → postprocess(
              use_camera_wb=True,
              half_size=False,
              output_color=rawpy.ColorSpace.sRGB,
              output_bps=8
          )
        → numpy array → Pillow.fromarray()
        → same thumbnail + preview pipeline as above

  MOV / MP4 / MKV / AVI / WebM / other video  (includes iPhone MOV)
    └── ffmpeg-python: extract frame at 10% of duration
        → same thumbnail + preview pipeline

  Audio (MP3 / FLAC / AAC / M4A / OGG / WAV / AIFF)
    └── pyexiftool: check for embedded cover art
          → if present: extract → image pipeline
          → if absent:  placeholder thumbnail (no preview generated)
```

**Preview sizing**: `Image.thumbnail((3840, 2160), Image.LANCZOS)` fits within the 4K bounding box maintaining aspect ratio. A 6000×4000 landscape becomes 3240×2160; a 4000×6000 portrait becomes 1440×2160. No upscaling occurs if the original is smaller than 4K.

**Color management**: Pillow `ImageCms` applies the embedded ICC profile and converts to sRGB before export. rawpy is configured to output sRGB directly.

**CR3 note**: LibRaw 0.20+ is required for Canon CR3 support. Verify the system LibRaw version before deploying; older distro packages may need a manual build.

### 6.3 REST API — Full Endpoint List

```
-- Auth (public)
POST   /api/auth/login
POST   /api/auth/refresh
POST   /api/auth/logout

-- Profile (all authenticated)
GET    /api/auth/me
GET    /api/users/me/root-prefs
PUT    /api/users/me/root-prefs

-- User management (admin)
GET    /api/users
POST   /api/users
PATCH  /api/users/{id}
DELETE /api/users/{id}

-- Filesystem browser (admin only — for picking root folder paths)
GET    /api/fs/browse?path=/              → list directories at path (default: /)

-- Root folder management (admin: write; all: read)
GET    /api/root-folders
POST   /api/root-folders
PATCH  /api/root-folders/{id}
DELETE /api/root-folders/{id}

-- Folder browsing (all authenticated)
GET    /api/folders                                    → root-level folder list (filtered by user prefs)
GET    /api/folders/by-path?root_folder_id=X&path=Y   → resolve folder by path (used by frontend routing)
GET    /api/folders/{folder_id}/children               → child folders
GET    /api/folders/{folder_id}/files                  → active files in folder (paginated; excludes trashed + missing)
GET    /api/folders/{folder_id}/trashed-files          → user-trashed files for this folder
GET    /api/folders/{folder_id}/missing-files          → externally-missing files for this folder

-- File operations (all authenticated)
GET    /api/files/trash                  → all trashed files across visible roots (paginated)
POST   /api/files/bulk-delete            → move files to user trash (sets is_deleted=true, deleted_at=now)
POST   /api/files/bulk-restore           → restore files from trash (clears is_deleted, deleted_at)
POST   /api/files/bulk-trash-missing     → move externally-missing files into trash
POST   /api/files/bulk-dismiss-missing   → permanently delete missing-file records from the library
GET    /api/files/{file_id}              → file detail + full metadata

-- Media assets (all authenticated)
GET    /api/thumbnails/{file_id}         → 480px JPEG thumbnail
GET    /api/previews/{file_id}           → fit-4K JPEG preview
GET    /api/stream/{file_id}             → original, range-request aware
GET    /api/original/{file_id}           → download original

-- Indexing (admin)
POST   /api/index/scan                           → scan all active root folders
POST   /api/index/scan/{root_folder_id}          → scan one root folder
GET    /api/index/status                         → overall progress
GET    /api/index/status/{root_folder_id}        → per-root progress
```

**Route ordering note**: In `files.py`, literal routes (`/trash`, `/bulk-delete`, etc.) are registered before the `/{file_id}` path-parameter route. This is required because FastAPI/Starlette matches routes in registration order; a UUID-typed path parameter would otherwise intercept literal paths and return 422. The same pattern applies to `/api/folders/by-path` being registered before `/{folder_id}`.

### 6.4 Filesystem Browser Endpoint

```
GET /api/fs/browse?path=/mnt/photos    (admin only)

Response:
{
  "path": "/mnt/photos",
  "parent": "/mnt",          -- null when at filesystem root
  "entries": [
    {
      "name": "alice",
      "path": "/mnt/photos/alice",
      "is_symlink": false,
      "is_configured": false   -- true if already a Monet root folder
    },
    ...
  ]
}
```

**Security**:
- Admin role required — regular users cannot browse the NAS filesystem.
- Path is resolved with `Path(path).resolve()` before use; `..` components are collapsed by the OS before listing, preventing traversal tricks.
- Only directories are returned — files are never listed.
- Directories that are unreadable (permission denied) are silently omitted from `entries` rather than returning an error, so partially accessible paths still work.
- Symlinks are followed but flagged with `is_symlink: true` so the admin can make an informed choice.
- No path restriction to a configured root — the admin needs full filesystem access to pick new root folders.

---

## 7. ARQ Job Queue — Indexing Architecture

### 7.1 Queue Design

Three queues in priority order:

| Queue | Jobs | Priority |
|---|---|---|
| `folder_scan` | `scan_folder` | High — tree discovery first |
| `metadata` | `extract_metadata` | Medium |
| `processing` | `generate_assets` | Low — thumbnail/preview last |

### 7.2 BFS Folder Expansion

```
POST /api/index/scan
  │
  └─ for each active root folder → enqueue scan_folder(root_folder_id, "")

scan_folder(root_folder_id, relative_path):
  1. Resolve absolute path = root.path / relative_path
  2. Upsert folder row in DB
  3. List directory:
     ├─ subdirs  → enqueue scan_folder(root_folder_id, subdir_path)
     └─ files    → detect MIME
                   skip non-media
                   if mtime unchanged + processed_at set → skip
                   upsert media_files row (clears missing_since if set)
                   enqueue extract_metadata(file_id)
                   enqueue generate_assets(file_id)
  4. mark_missing_files(): files in DB not seen on disk → set missing_since=now()
     (only if is_deleted=false; already-trashed files are left untouched)
  5. Update Redis progress hash for this root folder

extract_metadata(file_id):
  → pyexiftool → upsert file_metadata JSONB
  → update width/height/duration on media_files
  → if GPS present and location not set → reverse_geocode() → update location

generate_assets(file_id):
  → processor.py → write thumbnail JPEG + preview JPEG to cache dir
  → update media_files.thumbnail_path, preview_path, processed_at
```

**`mark_missing_files` vs the old `mark_deleted_files`**: The scanner previously set `is_deleted=True` for any file not found on disk, conflating external reorganization with user-initiated deletion. The current implementation sets `missing_since=now()` instead, preserving the distinction. `is_deleted` is now exclusively set by user action through the API.

**Progress tracking**: Redis hash `monet:progress:{root_folder_id}` stores `{total_files, processed_files, status, started_at}`. `/api/index/status` aggregates across all roots.

### 7.3 Worker Configuration

```python
# workers/worker.py
class WorkerSettings:
    functions = [scan_folder, extract_metadata, generate_assets, geocode_missing, purge_old_trash]
    cron_jobs = [
        cron(purge_old_trash, hour=2, minute=0),  # daily at 2 AM
    ]
    queue_name = "arq:queue"
    max_jobs = 4          # matches NAS thread budget
    job_timeout = 300
    keep_result = 3600

async def startup(ctx):
    ctx["redis"] = await create_pool(RedisSettings.from_dsn(settings.redis_url))
```

**Task inventory**:

| Task | Trigger | Purpose |
|---|---|---|
| `scan_folder` | API / watcher | Scan one directory level; upsert folders + files |
| `extract_metadata` | After upsert | Run ExifTool; populate JSONB + denormalized columns |
| `generate_assets` | After upsert | Generate thumbnail + preview JPEG |
| `geocode_missing` | On-demand | Geocode all GPS-tagged files without a `location` value |
| `purge_old_trash` | Cron (2 AM daily) | Permanently delete DB rows + cached assets for files trashed > 30 days ago |

### 7.4 Reverse Geocoding

`services/geocoder.py` wraps the Nominatim (OpenStreetMap) reverse geocoding API:

```
GPS coords (lat, lon)
  → asyncio rate-limiter (1 req/sec global lock)
  → urllib.request in thread executor (non-blocking)
  → Nominatim /reverse?lat=X&lon=Y&format=json&zoom=10
  → parse: city, state, country
  → return "Fremont, California, US"
```

- **Rate limit**: enforced with a module-level `asyncio.Lock` and 1-second minimum interval between requests, complying with Nominatim's usage policy.
- **No API key** required.
- **Populated**: during `extract_metadata` for newly-indexed GPS-tagged files. Batch backfill available via the `geocode_missing` on-demand task.
- **Stored**: in `media_files.location` as a plain text string. Displayed on thumbnail captions and in the metadata panel.

### 7.5 Filesystem Watcher

One `watchdog` Observer is started per active root folder at application startup. Adding a new root folder via the API starts a new observer immediately without restart. Events are debounced 2 seconds (MOV/RAW files can take time to finish copying) before enqueuing.

---

## 8. File Lifecycle & Trash System

### 8.1 Three File States

```
Active         → is_deleted=false, missing_since=NULL
User Trash     → is_deleted=true,  missing_since=NULL
Missing (ext.) → is_deleted=false, missing_since=<timestamp>
```

**Active**: Normal state. Returned by `GET /api/folders/{id}/files`.

**User Trash**: The user explicitly selected files in the gallery and clicked "Move to Trash". Files remain in the database and cache. Auto-purged after 30 days by the `purge_old_trash` cron job.

**Missing (externally moved/deleted)**: The scanner ran and couldn't find the file on disk, but the user did not trash it. This happens when files are reorganized outside the app (moved to a subfolder, renamed, deleted from the filesystem). The `missing_since` timestamp records when the scanner first noticed the absence.
- If the file reappears on disk (e.g., the user moves it back), `missing_since` is cleared on the next scan.
- The user can promote a missing file to trash (`POST /api/files/bulk-trash-missing`) or permanently remove its DB record (`POST /api/files/bulk-dismiss-missing`).

### 8.2 Trash Auto-Purge

The `purge_old_trash` ARQ cron job runs daily at 2 AM:

```python
cutoff = now() - 30 days
SELECT * FROM media_files WHERE is_deleted=true AND deleted_at <= cutoff
→ delete thumbnail + preview cache files from disk
→ DELETE FROM media_files (cascades to file_metadata)
```

### 8.3 API Operations

| Action | Endpoint | Effect |
|---|---|---|
| Move to trash | `POST /api/files/bulk-delete` | `is_deleted=true`, `deleted_at=now()` |
| Restore from trash | `POST /api/files/bulk-restore` | `is_deleted=false`, `deleted_at=NULL` |
| Trash a missing file | `POST /api/files/bulk-trash-missing` | `is_deleted=true`, `deleted_at=now()`, `missing_since=NULL` |
| Remove missing record | `POST /api/files/bulk-dismiss-missing` | Permanently deletes DB row |
| List all trash | `GET /api/files/trash` | Returns all `is_deleted=true` files for user's visible roots |
| List folder trash | `GET /api/folders/{id}/trashed-files` | Folder-scoped user trash |
| List folder missing | `GET /api/folders/{id}/missing-files` | Folder-scoped externally-missing files |

---

## 9. Frontend Architecture

### 9.1 Directory Layout

```
frontend/
├── src/
│   ├── main.tsx
│   ├── App.tsx                      ← router + protected route wrapper
│   ├── api/
│   │   ├── client.ts                ← axios instance with JWT interceptor
│   │   ├── auth.ts
│   │   ├── rootFolders.ts
│   │   ├── folders.ts               ← listFolderFiles, resolveFolderByPath,
│   │   │                               listFolderTrashedFiles, listFolderMissingFiles
│   │   ├── files.ts                 ← getFile, bulkDeleteFiles, bulkRestoreFiles,
│   │   │                               bulkTrashMissingFiles, bulkDismissMissingFiles,
│   │   │                               listTrashFiles
│   │   └── index.ts
│   ├── components/
│   │   ├── auth/
│   │   │   └── LoginPage.tsx
│   │   ├── layout/
│   │   │   ├── AppShell.tsx         ← sidebar + main area + topbar
│   │   │   └── Sidebar.tsx          ← folder tree + Trash link + Settings link
│   │   ├── folder/
│   │   │   ├── FolderTree.tsx       ← multi-root tree; one top-level node per root folder
│   │   │   └── FolderTreeNode.tsx   ← lazy-loaded children
│   │   ├── gallery/
│   │   │   ├── GalleryGrid.tsx      ← virtualized thumbnail grid + missing/trash sections
│   │   │   ├── MediaTile.tsx        ← tile with checkbox for multi-select
│   │   │   ├── GalleryToolbar.tsx   ← sort/filter + selection action bar
│   │   │   ├── FolderMissingSection.tsx  ← "Missing from disk" tiles per folder
│   │   │   ├── FolderTrashSection.tsx    ← "Recently Deleted" tiles per folder
│   │   │   └── TrashView.tsx        ← full-page trash grid (/trash route)
│   │   ├── lightbox/
│   │   │   └── MediaLightbox.tsx    ← YARL lightbox + side metadata panel (portal)
│   │   ├── metadata/
│   │   │   └── MetadataPanel.tsx    ← file detail panel (camera, date, GPS, EXIF)
│   │   ├── settings/
│   │   │   ├── SettingsPage.tsx
│   │   │   ├── RootFolderAdmin.tsx
│   │   │   ├── AddRootFolderModal.tsx
│   │   │   ├── DirectoryBrowser.tsx
│   │   │   └── VisibilityPrefs.tsx
│   │   └── ui/                      ← shadcn/ui re-exports
│   ├── store/
│   │   ├── auth.ts                  ← current user, access token
│   │   └── gallery.ts               ← lightboxIndex, sort/filter, selectedIds (Set<string>)
│   ├── hooks/
│   │   ├── useAuth.ts
│   │   ├── useFolderTree.ts
│   │   └── useInfiniteGallery.ts
│   ├── types/
│   │   └── api.ts                   ← FileResponse includes trashed_at, missing_since
│   └── lib/utils.ts
├── index.html
├── vite.config.ts
└── tailwind.config.ts
```

### 9.2 Routing

```
/login                         → LoginPage (public)
/                              → redirect to /browse  (auth required)
/browse                        → root-level gallery (all visible root folders)
/browse/:rootFolderId          → root folder gallery
/browse/:rootFolderId/*path    → subfolder gallery (arbitrary depth)
/trash                         → TrashView — all trashed files
/settings                      → settings page (auth required)
```

**Subfolder navigation**: The `useFolderIdForRoute` hook calls `GET /api/folders/by-path?root_folder_id=X&path=Y` to resolve the current URL's folder. This supports arbitrary nesting depth. Paths are relative to the root folder (e.g., `2024/vacation` for `/browse/{rootId}/2024/vacation`).

### 9.3 Sidebar

The sidebar has three sections:
1. **Folder tree** — one collapsible top-level node per visible root folder. Children lazy-load on first expand. Tree expand state persisted in `sessionStorage`.
2. **Trash** — fixed link to `/trash` (Trash2 icon), highlighted when active.
3. **Settings** — link to `/settings`.

### 9.4 Gallery Grid

`GalleryGrid` renders up to 500 files per folder using TanStack Virtual (row virtualizer). Each row contains `columnCount` tiles calculated from the container width. Tiles include a checkbox for multi-select.

Below the virtualized grid, two additional sections are rendered (non-virtualized, shown only when non-empty):

1. **Missing from disk** (`FolderMissingSection`) — files where `missing_since` is set. Shown with amber dashed border, grayscale thumbnail, and "Not found on disk" caption. Hover reveals "Move to Trash" and "Remove record" buttons.

2. **Recently Deleted** (`FolderTrashSection`) — user-trashed files for this folder. Shown with grayscale/dimmed thumbnails, days-remaining caption (color-coded: green → orange → red as the 30-day deadline approaches), and a "Restore" hover button.

### 9.5 Selection & Bulk Actions

Multi-select state (`selectedIds: Set<string>`) lives in the Zustand gallery store. Actions:
- **Checkbox on tile**: visible on hover; always visible when any file is selected (selection mode).
- **Selection bar** in `GalleryToolbar`: appears when `selectedIds.size > 0`. Shows count, "Select all" / "Deselect all" / "Clear", and a red "Move to Trash" button.
- Moving to trash shows a confirmation dialog noting the 30-day auto-purge.
- Selection is cleared when the folder or filters change.

### 9.6 Lightbox & Metadata Panel

`MediaLightbox` wraps `yet-another-react-lightbox` (YARL) with a right-side metadata panel:

```
┌────────────────────────────────────┬────────────┐
│                                    │  File Info │
│        YARL image/video            │  ────────  │
│                                    │  Camera    │
│                                    │  Date/Time │
│                                    │  GPS/Loc   │
│                                    │  EXIF...   │
└────────────────────────────────────┴────────────┘
```

**Portal architecture**: The metadata panel is rendered via `React.createPortal` into `document.body` rather than inside YARL's DOM. YARL's overlay element (`z-index: 9999`, `pointer-events: auto`) would intercept all clicks on elements inside its stacking context regardless of their `z-index`. Portaling to `body` places the panel in the root stacking context at `z-index: 99999`, fully outside YARL's hierarchy.

**Animation sync**: Three state flags track YARL's animation lifecycle:
- `isEntering` (set by `on.entering`) — panel becomes visible in sync with image fade-in
- `isEntered` (set by `on.entered`) — Info toggle button appears after animation completes
- `isClosing` (set by `on.exiting`) — everything hidden at the start of close animation

**Panel controls**:
- Close button in the panel header hides the panel; a `PanelRight` icon button at top-right reopens it.
- "Info" button at bottom-right of the image area (visible only when `isEntered && !isClosing`).
- `I` keyboard shortcut toggles the panel.
- YARL's image area `right` is set to `360px` when the panel is open so the image is not cropped behind the panel.

### 9.7 Trash View

`TrashView` (`/trash`) shows all user-trashed files across the user's visible roots:

- Grid layout using CSS `auto-fill` (no virtualizer — trash is typically small).
- Each tile shows filename and days-remaining caption (color-coded as above; "Purging soon" when 0 days remain).
- Checkbox multi-select with "Restore X" bulk action.
- Header shows total count and the 30-day policy reminder.
- Lightbox preview available.

### 9.8 JWT Handling

```
Login → access_token stored in Zustand (memory only, not localStorage)
      → refresh_token in HttpOnly cookie (browser sends automatically)

axios request interceptor  → attach Authorization: Bearer <token>
axios response interceptor → on 401: call POST /api/auth/refresh
                                    → update Zustand token
                                    → retry original request once
                                    → on second 401: redirect to /login
```

---

## 10. Storage Layout on Disk

```
/var/monet/cache/                  ← MONET_CACHE_DIR
├── thumbnails/
│   └── ab/cd/<file_uuid>.jpg      ← sharded by first 4 chars of file UUID
└── previews/
    └── ab/cd/<file_uuid>.jpg      ← same sharding scheme
```

Shard depth of 2 (`ab/cd/`) keeps directory entry counts well under filesystem limits at 1M files (max ~1000 entries per leaf directory at full scale).

Thumbnails and previews are served via `FileResponse` with `Cache-Control: max-age=31536000, immutable`. URL includes the file UUID; if the original changes, `processed_at` resets and a new thumbnail is generated under the same UUID path (overwriting).

Cache files for trashed files are retained until the `purge_old_trash` cron job runs (≤24 hours after the 30-day window closes). The purge job deletes both the DB row and the corresponding `thumbnail_path` / `preview_path` files on disk.

---

## 11. Configuration (`.env`)

```env
# Database
DATABASE_URL=postgresql+asyncpg://monet:password@localhost:5432/monet

# Redis
REDIS_URL=redis://localhost:6379/0

# Cache
MONET_CACHE_DIR=/var/monet/cache

# Server
MONET_HOST=0.0.0.0
MONET_PORT=8000
MONET_LOG_LEVEL=info

# Auth
JWT_SECRET_KEY=<random 256-bit hex — generate with: openssl rand -hex 32>
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7

# Processing
MONET_THUMB_SIZE=480            # longest side, px
MONET_PREVIEW_MAX_WIDTH=3840
MONET_PREVIEW_MAX_HEIGHT=2160
MONET_THUMB_QUALITY=85
MONET_PREVIEW_QUALITY=90

# Indexing
MONET_WORKER_CONCURRENCY=4
MONET_WATCH_ENABLED=true
MONET_SCAN_ON_STARTUP=true
MONET_FILE_SETTLE_SECONDS=2     # debounce before processing a new/changed file
```

Root folders are configured at runtime via the Settings UI (stored in the DB), not in `.env`.

---

## 12. Deployment (LAN)

```
NAS Linux machine
├── PostgreSQL 16
├── Redis 7
├── monet-backend.service    ← uvicorn, port 8000; serves API + static Vite build
└── monet-worker.service     ← arq app.workers.worker.WorkerSettings (4 concurrent jobs + cron)
```

FastAPI serves the built Vite frontend as static files at `/`. No nginx required for LAN-only use — plain HTTP on port 8000.

### Docker Compose (recommended)

```yaml
services:
  db:
    image: postgres:16-alpine
    volumes: [pgdata:/var/lib/postgresql/data]
    environment:
      POSTGRES_DB: monet
      POSTGRES_USER: monet
      POSTGRES_PASSWORD: changeme

  redis:
    image: redis:7-alpine

  backend:
    build: ./backend
    ports: ["8000:8000"]
    depends_on: [db, redis]
    volumes:
      - /mnt/photos:/mnt/photos:ro   # NAS media paths; add all mount points here
      - monet_cache:/var/monet/cache
    env_file: .env

  worker:
    build: ./backend
    command: python -m arq app.workers.worker.WorkerSettings
    depends_on: [db, redis]
    volumes:
      - /mnt/photos:/mnt/photos:ro
      - monet_cache:/var/monet/cache
    env_file: .env

volumes:
  pgdata:
  monet_cache:
```

**Note**: Backend code is baked into the Docker image (not volume-mounted). Any backend code change requires `docker compose build backend worker` followed by `docker compose up -d backend worker`.

**Adding internet access later**: add an nginx service to the compose file with Let's Encrypt or put Cloudflare Tunnel / Tailscale in front. No application code changes required.

---

## 13. Supported Media Formats

### Images
JPEG, PNG, WebP, TIFF, GIF, BMP

### RAW
Canon CR2, CR3 (LibRaw ≥ 0.20 required), Nikon NEF, NRW, DNG, ORF, RAF, ARW, RW2, PEF, SRW

### Apple / iPhone
HEIC, HEIF (still images via pillow-heif), MOV (video via ffmpeg)

### Video
MP4, MOV, MKV, AVI, WMV, FLV, WebM, M4V, MPG/MPEG, 3GP

### Audio
MP3, FLAC, WAV, AAC, M4A, OGG, WMA, AIFF, APE, OPUS

---

## 14. Key Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Database | PostgreSQL | Multi-user, JSONB+GIN for metadata without schema migrations |
| Metadata | JSONB (not flat KV) | ExifTool JSON stored verbatim; all tags queryable via GIN |
| Job queue | ARQ + Redis (concurrency=4) | Matches NAS thread budget; BFS folder-first expansion; built-in cron |
| Thumbnails | Filesystem JPEG (sharded) | Simple, fast, HTTP-cache-friendly; no operational complexity |
| Root folders | DB-configured, runtime | Multiple users/libraries; managed via UI, not config file |
| User visibility | Per-user preference table | Each user sees the roots they care about; no RBAC needed |
| Auth | JWT (memory) + HttpOnly refresh cookie | Revocable, XSS-safe; upgrade path to HTTPS is adding nginx |
| Preview sizing | `Image.thumbnail((3840,2160))` | Fills 4K screen regardless of portrait/landscape |
| LAN-only v1 | Plain HTTP on port 8000 | No nginx/TLS complexity; add later without app changes |
| Trash vs missing | Separate `is_deleted` / `missing_since` columns | Distinguishes intentional user action from external filesystem reorganization; prevents scan runs from polluting user trash |
| Reverse geocoding | Nominatim (no key, rate-limited) | Zero cost; 1 req/sec complies with OSM usage policy; populated async so it doesn't block indexing |
| Metadata panel portal | `React.createPortal` to `document.body` | YARL's overlay intercepts all pointer events inside its stacking context; portaling to body bypasses this without patching YARL |
| Subfolder routing | `/api/folders/by-path` lookup | Sidebar navigates to `/browse/:rootId/a/b/c`; resolving the folder ID requires a path→ID lookup that can't rely on a flat cache of root-level folders |

---

## 15. Future Considerations (out of scope for v1)

- **HTTPS / internet access** — nginx + Let's Encrypt or Cloudflare Tunnel; no app changes
- **Per-folder RBAC** — restrict root folders to specific users or groups
- **Duplicate detection** — perceptual hash (pHash) stored in DB, dedupe view
- **Map view** — GPS-tagged photo clustering on Leaflet/MapLibre (GPS coords already stored)
- **Face detection** — InsightFace or DeepFace for people albums
- **Smart albums / saved searches** — JSONB metadata filter presets saved per user
- **Masonry / justified gallery layout** — alternative to uniform grid
- **Audit log** — track who accessed which files
- **JPEG XL / AVIF preview output** — as Pillow support matures
- **Scheduled geocode refresh** — re-geocode when Nominatim data changes (low priority)
