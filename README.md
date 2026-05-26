# Monet

Self-hosted media management for personal photo and video libraries. Browse, search, and organize your files through a web UI backed by automatic indexing, thumbnail generation, and EXIF metadata extraction.

---

## What it does

- **Indexes** folders on disk recursively, detecting new, modified, and removed files on rescan or via filesystem watch
- **Generates** thumbnails and web-quality previews for images (JPEG, PNG, HEIC, RAW), videos (MP4, MOV, MKV, …), and audio
- **Extracts** EXIF metadata (camera, lens, exposure, GPS) using ExifTool and reverse-geocodes GPS coordinates to a human-readable location
- **Gallery** — infinite-scroll grid with lightbox, folder tree navigation, per-root visibility preferences
- **Search** — filter by media type, camera, date range, location, and free-text across filenames and metadata
- **Trash** — soft-delete with 30-day auto-purge; separates user-deleted files from files externally moved off disk
- **Auth** — JWT-based with role separation (admin / viewer), httpOnly refresh-token cookie

---

## Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, Vite, TanStack Query, Zustand, Tailwind CSS |
| Backend | FastAPI, SQLAlchemy async, Alembic |
| Workers | ARQ (async Redis queue) — separate scan and asset-processing queues |
| Database | PostgreSQL 16 |
| Cache / Queue | Redis 7 |
| Media | Pillow, pillow-heif, rawpy, ffmpeg-python, PyExifTool |
| Serving | nginx (SPA + `/api/*` reverse proxy) |

---

## Repository layout

```
monet/
├── backend/
│   ├── app/
│   │   ├── api/          # FastAPI route handlers
│   │   ├── models/       # SQLAlchemy ORM models + Pydantic schemas
│   │   ├── services/     # indexer, metadata, processor, geocoder, watcher
│   │   └── workers/      # ARQ task definitions + worker settings
│   ├── alembic/          # database migrations
│   └── tests/
├── frontend/
│   ├── src/
│   │   ├── api/          # Axios API clients
│   │   ├── components/   # React components (gallery, lightbox, settings, …)
│   │   ├── hooks/        # TanStack Query hooks
│   │   └── store/        # Zustand stores
│   └── nginx.conf        # production nginx config
├── docker-compose.yml
└── docker-compose.test.yml
```

---

## Setup on a fresh Ubuntu machine

### 1. System dependencies

```bash
# Docker (official install)
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin

# Allow your user to run Docker without sudo
sudo usermod -aG docker $USER
newgrp docker
```

> All media processing (ffmpeg, ExifTool, libraw, Pillow) runs inside the backend container — no additional packages needed on the host.

### 2. Clone the repository

```bash
git clone https://github.com/grvsh/monet.git
cd monet
```

### 3. Create the cache directory

Thumbnails and previews are stored here. The backend container writes to it via a bind mount.

```bash
mkdir -p ~/.monet/cache
```

### 4. Configure environment

```bash
cp .env.example .env
```

Open `.env` and set at minimum:

| Variable | Description |
|---|---|
| `REDIS_PASSWORD` | Any strong random string — `python3 -c "import secrets; print(secrets.token_hex(24))"` |
| `JWT_SECRET_KEY` | 32-byte random hex — `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `MONET_BROWSE_ROOTS` | Comma-separated paths the admin may browse when adding folders (e.g. `/mnt,/media`) |
| `MONET_CORS_ORIGINS` | Allowed origins — set to your server's hostname/IP if accessing from another machine |

All other values have sensible defaults and can be left as-is to start.

### 5. Update volume mounts in `docker-compose.yml`

The backend containers mount the directories that hold your media. Edit the `volumes` blocks under `backend`, `worker`, and `asset-worker` to match your setup:

```yaml
volumes:
  - ~/.monet/cache:/var/monet/cache
  - /path/to/your/media:/path/to/your/media:ro   # add your media paths here
```

The `:ro` flag mounts media read-only — Monet never writes to your originals.

### 6. Start

```bash
docker compose up -d
```

This builds all images on first run (takes a few minutes — downloads Python/Node deps and ffmpeg). Subsequent starts are instant.

Services started:

| Service | Port | Description |
|---|---|---|
| `frontend` | `80` | nginx — serves the SPA and proxies `/api/*` |
| `backend` | `8000` | FastAPI — also directly accessible for dev |
| `worker` | — | ARQ scan worker |
| `asset-worker` | — | ARQ thumbnail/metadata worker |
| `db` | `5432` | PostgreSQL |
| `redis` | `6379` | Redis |

Alembic migrations run automatically on backend startup.

### 7. Create the first admin account

```bash
docker compose exec backend python scripts/create_admin.py
```

Follow the prompts to set an email and password.

### 8. Open the app

Navigate to `http://<your-server-ip>/` and log in. Go to **Settings → Root Folders**, add a folder path, and click **Scan** to kick off the first index.

---

## Development

### Backend (outside Docker)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Requires a running Postgres and Redis (use docker compose up db redis)
DATABASE_URL=postgresql+asyncpg://monet:${POSTGRES_PASSWORD}@localhost:5432/monet \
REDIS_URL=redis://:yourpassword@localhost:6379/0 \
JWT_SECRET_KEY=dev_secret \
  uvicorn app.main:app --reload
```

### Frontend (outside Docker)

```bash
cd frontend
npm install
npm run dev        # starts Vite on http://localhost:5173
                   # proxies /api/* to http://localhost:8000 automatically
```

The Vite dev proxy is configured in `vite.config.ts`. The backend container (`docker compose up backend`) can stay running while you iterate on the frontend.

### Tests

```bash
docker compose -f docker-compose.test.yml up --build --abort-on-container-exit
```

---

## Configuration reference

All settings are read from environment variables (or `.env`). Key options:

| Variable | Default | Description |
|---|---|---|
| `MONET_THUMB_SIZE` | `480` | Thumbnail longest edge in pixels |
| `MONET_PREVIEW_MAX_WIDTH` | `3840` | Preview image max width |
| `MONET_PREVIEW_MAX_HEIGHT` | `2160` | Preview image max height |
| `MONET_WORKER_CONCURRENCY` | `4` | Concurrent jobs per worker process |
| `MONET_WATCH_ENABLED` | `true` | Watch root folders for live filesystem changes |
| `MONET_SCAN_ON_STARTUP` | `true` | Trigger a scan of all active root folders on backend start |
| `MONET_FILE_SETTLE_SECONDS` | `2` | Wait time after a filesystem event before processing (debounce) |
| `MONET_SECURE_COOKIES` | `false` | Set `true` when serving over HTTPS |
| `LOGIN_RATE_LIMIT` | `10/minute` | Max login attempts per IP |
| `MONET_BROWSE_ROOTS` | `/mnt,/media,/srv,/data,/home` | Directories browsable when adding root folders |

---

## Running on a NAS OS (OMV, Unraid, TrueNAS)

Monet should run fine on NAS operating systems — they are standard Linux under the hood and support Docker the same way as Ubuntu. That said, we have not been able to test on these platforms directly as we don't have access to them. If you run into issues, please open a GitHub issue.

**OpenMediaVault:** Install the **OMV-Extras** plugin from the OMV web UI, which adds Docker and Portainer with one click. Then follow the standard setup steps above via SSH or the Portainer terminal. Your drives are already mounted (typically under `/srv/dev-disk-by-uuid-xxx/` or a path you configured in OMV's Shared Folders) — use those paths when adding root folders in Monet.

**Unraid:** Docker is built in. Create a new stack in the Compose Manager plugin and paste in the `docker-compose.yml`.

**TrueNAS Scale:** Use the **Custom App** option under Apps, or deploy via the built-in Compose support in newer releases.

### Port 80 conflict

OMV, Unraid, and TrueNAS all run their own admin web UI — typically on port 80. Monet's frontend also defaults to port 80, which will conflict.

**Fix:** move OMV's (or your NAS OS's) admin panel to a different port (e.g. 8080) in its network settings, or change Monet's frontend port in `docker-compose.yml`:

```yaml
  frontend:
    ports:
      - "8096:80"   # change 8096 to any free port
```

Then access Monet at `http://<your-nas-ip>:8096/`.
