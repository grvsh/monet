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
FROM base AS builder
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# ── Production stage (static files served by FastAPI) ────────────────────────
# The built dist/ is copied into the backend image at build time via compose,
# or served by nginx if added later. This stage is a reference artifact.
FROM nginx:alpine AS production
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 80
