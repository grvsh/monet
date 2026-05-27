FROM node:22-alpine AS base
WORKDIR /app

# ── Development stage ────────────────────────────────────────────────────────
FROM base AS development
COPY package*.json ./
RUN npm ci
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host"]

# ── Build stage ──────────────────────────────────────────────────────────────
# Run on the host's native platform (amd64 in CI) to avoid QEMU emulation
# issues with Node.js during cross-compilation. The output is platform-agnostic
# static assets, so the target platform only matters for the nginx stage below.
FROM --platform=$BUILDPLATFORM node:22-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# ── Production stage — nginx serves the built SPA and proxies /api/* ─────────
FROM nginx:1.27-alpine AS production
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
