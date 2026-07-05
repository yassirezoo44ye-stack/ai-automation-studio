# ── Stage 1: Build frontend ───────────────────────────────────────────────────
FROM node:20-slim AS frontend
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts

COPY index.html vite.config.ts tsconfig.json ./
COPY src ./src
COPY public ./public
RUN npm run build

# ── Stage 2: Multi-runtime backend (Python 3.11 + Node.js 20 LTS) ─────────────
FROM python:3.11-slim AS backend
WORKDIR /app

# Copy Node.js binaries from the pinned node:20-slim image used in stage 1.
# This avoids the supply-chain risk of curl | bash (NodeSource setup script).
COPY --from=frontend /usr/local/bin/node /usr/local/bin/node
COPY --from=frontend /usr/local/bin/npm  /usr/local/bin/npm
COPY --from=frontend /usr/local/lib/node_modules /usr/local/lib/node_modules

# Install system deps in a single layer:
#   - gcc / libpq-dev: needed to build asyncpg (C extension)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc libpq-dev \
    && pip install --upgrade pip --quiet \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies (own layer — cached unless requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y --auto-remove gcc libpq-dev 2>/dev/null || true

# Copy application code
COPY main.py .
COPY app_main.py .
COPY app ./app

# Copy built frontend from stage 1
COPY --from=frontend /app/dist ./dist
COPY --from=frontend /app/public ./public

# Create runtime directories and a non-root user for security.
# Running as root in production is a security risk — if the app is compromised,
# the attacker has root inside the container.
RUN mkdir -p workspaces dist_packages \
    && groupadd -r axon \
    && useradd -r -g axon -u 1001 --no-create-home axon \
    && chown -R axon:axon /app

USER axon

EXPOSE 8000

# Docker-level health check (belt-and-suspenders alongside Render's /health check).
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT:-8000}/health')" \
    || exit 1

# Use uvicorn directly (better signal handling than python main.py).
CMD ["sh", "-c", "uvicorn app_main:app --host 0.0.0.0 --port ${PORT:-8000}"]
