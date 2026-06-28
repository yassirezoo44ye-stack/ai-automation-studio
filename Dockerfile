# ── Stage 1: Build frontend ───────────────────────────────────────────────────
FROM node:20-slim AS frontend
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts
COPY index.html vite.config.ts tsconfig.json ./
COPY src ./src
COPY public ./public
RUN npm run build

# ── Stage 2: Python backend + serve frontend ──────────────────────────────────
FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY --from=frontend /app/dist ./dist
COPY --from=frontend /app/public ./public

# Create workspace and dist_packages directories
RUN mkdir -p workspaces dist_packages

EXPOSE 8000

CMD ["python", "main.py"]
