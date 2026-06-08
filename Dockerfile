# ── Stage 1: build the React frontend ──────────────────────────────────────
FROM node:20-alpine AS frontend-builder

WORKDIR /build

COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN npm ci --prefix frontend

COPY frontend/ ./frontend/
# vite.config.js writes to ../app/static/dist — create the target path first
RUN mkdir -p app/static/dist
RUN npm run build --prefix frontend


# ── Stage 2: Python runtime ─────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /discordforge

# System deps needed by gevent / cryptography
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY app/requirements.txt ./app/requirements.txt
RUN pip install --no-cache-dir -r app/requirements.txt

# Copy application source
COPY app/ ./app/
COPY discord-server-setup-template/ ./discord-server-setup-template/

# Overwrite the placeholder dist with the real frontend build
COPY --from=frontend-builder /build/app/static/dist/ ./app/static/dist/

# server.py must run from the app/ directory (imports `from app import app`)
WORKDIR /discordforge/app

EXPOSE 5000

CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "5000"]
